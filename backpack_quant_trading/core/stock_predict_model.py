"""
A股 3~5 日涨跌预测模型：特征工程 + LightGBM 训练 + 推理。
用途：用历史日线算技术面特征，预测未来 N 日是否上涨，供选股/排序参考。

怎么训练：
  1) 安装依赖: pip install lightgbm scikit-learn akshare
  2) 命令行: 在 backpack_quant_trading 目录下执行
     python run_train_stock_model.py
     python run_train_stock_model.py --codes 000001 600000 --days 5 --lookback 500
  3) 或调用 API: POST /api/stock-ai/train-model
     body: { "stock_codes": ["000001","600000"], "forward_days": 5, "lookback_days": 500 }
  4) 或代码调用: run_train_with_akshare(stock_codes=["000001","600000"], forward_days=5)
 模型保存到 backpack_quant_trading/models/stock_predict_lgb.txt，推理时 load_model() 后 predict_proba(features)。

 每日推送（未来 3~5 日看涨）：
  调用 run_daily_predict() 或 POST /api/stock-ai/daily-predict，对股票池做预测并按看涨概率排序；
  结果缓存到 models/daily_predict.json（按日期），前端「获取今日预测」即可展示。可定时（如每日 18:00）执行一次并刷新缓存。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from concurrent.futures import TimeoutError as FuturesTimeoutError
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import lightgbm as lgb
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False
    lgb = None

try:
    import joblib
except ImportError:
    joblib = None

# 默认模型保存路径（项目下）
DEFAULT_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
DEFAULT_MODEL_PATH = os.path.join(DEFAULT_MODEL_DIR, "stock_predict_lgb.txt")
FEATURE_COLS = [
    "ret_1d", "ret_5d", "ret_20d",
    "volatility_5d", "volatility_20d",
    "rsi", "macd_hist", "macd_dif", "macd_dea",
    "kdj_k", "kdj_d", "kdj_j",
    "volume_ratio_5", "ma5_ma20_cross",
    "close_ma5_ratio", "close_ma20_ratio",
]


def _safe_series(df: pd.DataFrame, *cols: str) -> Optional[pd.Series]:
    for c in cols:
        if c in df.columns:
            s = df[c]
            if s is not None and len(s) > 0:
                return pd.to_numeric(s, errors="coerce")
    return None


def build_features_single(close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series) -> pd.DataFrame:
    """
    对单只股票的 OHLCV 序列，按日滚动计算特征，每行对应一个交易日。
    要求 close/high/low/volume 已按日期排序，且无缺失。
    """
    n = len(close)
    if n < 50:
        return pd.DataFrame()

    close = pd.Series(close).astype(float)
    high = pd.Series(high).astype(float) if high is not None else close
    low = pd.Series(low).astype(float) if low is not None else close
    volume = pd.Series(volume).astype(float) if volume is not None else pd.Series(1.0, index=close.index)

    ret = close.pct_change()
    ret_1d = ret
    ret_5d = close.pct_change(5)
    ret_20d = close.pct_change(20)

    volatility_5d = ret.rolling(5).std()
    volatility_20d = ret.rolling(20).std()

    # RSI(14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_dif = ema12 - ema26
    macd_dea = macd_dif.ewm(span=9, adjust=False).mean()
    macd_hist = macd_dif - macd_dea

    # KDJ
    low_min = low.rolling(9).min()
    high_max = high.rolling(9).max()
    rsv = (close - low_min) / (high_max - low_min + 1e-10) * 100
    rsv = rsv.fillna(50)
    kdj_k = rsv.ewm(com=2, adjust=False).mean()
    kdj_d = kdj_k.ewm(com=2, adjust=False).mean()
    kdj_j = 3 * kdj_k - 2 * kdj_d

    # 量比：当日量 / 过去5日均量
    vol_ma5 = volume.rolling(5).mean().shift(1)
    volume_ratio_5 = volume / vol_ma5.replace(0, np.nan)

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma5_ma20_cross = (ma5 > ma20).astype(float)
    close_ma5_ratio = close / ma5.replace(0, np.nan)
    close_ma20_ratio = close / ma20.replace(0, np.nan)

    out = pd.DataFrame({
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "volatility_5d": volatility_5d,
        "volatility_20d": volatility_20d,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "macd_dif": macd_dif,
        "macd_dea": macd_dea,
        "kdj_k": kdj_k,
        "kdj_d": kdj_d,
        "kdj_j": kdj_j,
        "volume_ratio_5": volume_ratio_5,
        "ma5_ma20_cross": ma5_ma20_cross,
        "close_ma5_ratio": close_ma5_ratio,
        "close_ma20_ratio": close_ma20_ratio,
    }, index=close.index)
    return out


def build_label_forward(close: pd.Series, forward_days: int = 5, threshold: float = 0.02) -> pd.Series:
    """
    未来 forward_days 日收益率 > threshold 则为 1，否则为 0。
    """
    if len(close) < forward_days + 1:
        return pd.Series(dtype=float)
    fwd_ret = close.shift(-forward_days) / close - 1.0
    label = (fwd_ret > threshold).astype(int)
    return label


def build_dataset_from_daily(
    daily_df: pd.DataFrame,
    forward_days: int = 5,
    label_threshold: float = 0.02,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    从单只股票的日线 DataFrame 构建 (特征表, 标签序列)。
    daily_df 需含 date/close，以及 high/low/volume（可选，缺失时用 close/1 填充）。
    """
    daily_df = daily_df.sort_values("date").reset_index(drop=True)
    close = _safe_series(daily_df, "close", "收盘")
    if close is None or len(close) < 60:
        return pd.DataFrame(), pd.Series()

    high = _safe_series(daily_df, "high", "最高")
    if high is None or len(high) == 0:
        high = close
    low = _safe_series(daily_df, "low", "最低")
    if low is None or len(low) == 0:
        low = close
    volume = _safe_series(daily_df, "volume", "成交量")
    if volume is None or (hasattr(volume, "isna") and volume.isna().all()):
        volume = pd.Series(1.0, index=close.index)

    features = build_features_single(close, high, low, volume)
    if features.empty:
        return pd.DataFrame(), pd.Series()

    label = build_label_forward(close, forward_days=forward_days, threshold=label_threshold)
    # 对齐：最后 forward_days 行没有未来收益，去掉
    valid_idx = label.notna()
    features = features.loc[valid_idx].copy()
    label = label.loc[valid_idx]
    features = features.dropna(how="all", axis=1)
    features = features.fillna(0)
    # 只保留我们列出的特征列（若存在）
    use_cols = [c for c in FEATURE_COLS if c in features.columns]
    features = features[use_cols]
    return features, label


def train_model(
    features: pd.DataFrame,
    label: pd.Series,
    val_ratio: float = 0.2,
    params: Optional[dict] = None,
) -> Any:
    """
    按时间顺序划分训练/验证集，训练 LightGBM 二分类模型。
    """
    if not HAS_LIGHTGBM:
        raise RuntimeError("请先安装: pip install lightgbm scikit-learn")

    n = len(features)
    if n < 100:
        raise ValueError("样本数过少，至少需要约 100 条")

    # 时间顺序：前 80% 训练，后 20% 验证
    split = int(n * (1 - val_ratio))
    X_train, X_val = features.iloc[:split], features.iloc[split:]
    y_train, y_val = label.iloc[:split], label.iloc[split:]

    default_params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "seed": 42,
        "n_estimators": 200,
        "early_stopping_rounds": 20,
    }
    if params:
        default_params.update(params)

    train_set = lgb.Dataset(X_train, label=y_train)
    val_set = lgb.Dataset(X_val, label=y_val, reference=train_set)

    model = lgb.train(
        default_params,
        train_set,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)],
    )

    pred_val = (model.predict(X_val) >= 0.5).astype(int)
    acc = accuracy_score(y_val, pred_val)
    auc = roc_auc_score(y_val, model.predict(X_val)) if len(np.unique(y_val)) > 1 else 0.5
    logger.info("验证集 accuracy=%.4f auc=%.4f", acc, auc)
    logger.info("\n%s", classification_report(y_val, pred_val, target_names=["跌/平", "涨"]))

    return model


def save_model(model: Any, path: Optional[str] = None) -> str:
    if path is None:
        path = DEFAULT_MODEL_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # LightGBM 的 C++ 端在 Windows 下对含非 ASCII 路径（如中文「副本」）写入会报错，先写到临时文件再复制
    if any(ord(c) > 127 for c in path):
        fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="lgb_")
        try:
            os.close(fd)
            model.save_model(tmp)
            shutil.copy2(tmp, path)
            logger.info("模型已保存: %s", path)
            return path
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    model.save_model(path)
    logger.info("模型已保存: %s", path)
    return path


def load_model(path: Optional[str] = None) -> Any:
    if not HAS_LIGHTGBM:
        raise RuntimeError("请先安装 lightgbm")
    if path is None:
        path = DEFAULT_MODEL_PATH
    if not os.path.isfile(path):
        raise FileNotFoundError("未找到模型文件: %s", path)
    # LightGBM 在 Windows 下对含非 ASCII 路径读取也可能失败，先复制到临时文件再加载
    if any(ord(c) > 127 for c in path):
        fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="lgb_")
        try:
            os.close(fd)
            shutil.copy2(path, tmp)
            return lgb.Booster(model_file=tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return lgb.Booster(model_file=path)


def predict_proba(model: Any, features: pd.DataFrame) -> np.ndarray:
    """预测上涨概率，形状 (n_samples,)"""
    use_cols = [c for c in FEATURE_COLS if c in features.columns]
    X = features[use_cols].fillna(0)
    return model.predict(X)


def get_latest_features_row(daily_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """从日线 DataFrame 计算特征，只返回最近一行的特征（用于当日预测）。"""
    daily_df = daily_df.sort_values("date").reset_index(drop=True)
    close = _safe_series(daily_df, "close", "收盘")
    if close is None or len(close) < 50:
        return None
    high = _safe_series(daily_df, "high", "最高")
    if high is None or len(high) == 0:
        high = close
    low = _safe_series(daily_df, "low", "最低")
    if low is None or len(low) == 0:
        low = close
    volume = _safe_series(daily_df, "volume", "成交量")
    if volume is None or (hasattr(volume, "isna") and volume.isna().all()):
        volume = pd.Series(1.0, index=close.index)
    features = build_features_single(close, high, low, volume)
    if features.empty:
        return None
    last = features.iloc[[-1]].copy()
    use_cols = [c for c in FEATURE_COLS if c in last.columns]
    last = last[use_cols].fillna(0)
    return last


# 每日预测结果缓存路径（按日期存 JSON）
def _daily_predict_cache_path() -> str:
    os.makedirs(DEFAULT_MODEL_DIR, exist_ok=True)
    return os.path.join(DEFAULT_MODEL_DIR, "daily_predict.json")


def run_daily_predict(
    stock_codes: Optional[list[str]] = None,
    model_path: Optional[str] = None,
    top_n: int = 20,
    use_cache: bool = True,
    max_stocks: int = 30,
    skip_cache_write: bool = False,
) -> dict[str, Any]:
    """
    用已训练模型对股票池做「未来 3~5 日看涨」预测，返回按看涨概率排序的列表。
    若 use_cache=True 且当日已有缓存，直接返回缓存；否则拉日线→算特征→预测→排序→缓存。
    skip_cache_write=True 时（如对选股结果预测）不写入缓存，避免覆盖「获取今日预测」的默认池结果。
    """
    if not HAS_LIGHTGBM:
        return {"ok": False, "error": "请先安装 lightgbm", "list": [], "date": None}
    try:
        import akshare as ak
    except ImportError:
        return {"ok": False, "error": "请先安装 akshare", "list": [], "date": None}

    import time
    import json

    today = datetime.now().strftime("%Y-%m-%d")
    cache_path = _daily_predict_cache_path()
    if use_cache and os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today and isinstance(data.get("list"), list):
                return {"ok": True, "list": data["list"], "date": today, "from_cache": True}
        except Exception:
            pass

    if not os.path.isfile(model_path or DEFAULT_MODEL_PATH):
        return {"ok": False, "error": "未找到模型文件，请先执行「模型训练」", "list": [], "date": today}

    code_to_name: dict[str, str] = {}
    if stock_codes is None or len(stock_codes) == 0:
        try:
            from backpack_quant_trading.core.stock_ai import _fetch_a_stock_list
            df_all = _fetch_a_stock_list()
            if df_all is not None and not df_all.empty:
                main = df_all[df_all["code"].astype(str).str.match(r"^(60|00)")].copy()
                codes = main["code"].astype(str).str.strip().tolist()
                codes = sorted(set(codes))  # 按代码顺序，去重
                code_to_name = dict(zip(main["code"].astype(str).str.strip(), main["name"].astype(str).fillna("")))
                # 按代码顺序取前 max_stocks 只参与预测，全部算完后按看涨概率排序，返回概率最高的 top_n 只（非随机）
                stock_codes = codes[:max_stocks]
            else:
                stock_codes = ["000001", "000002", "600000", "600519", "000858", "601318", "000333", "600036"]
        except Exception:
            stock_codes = ["000001", "000002", "600000", "600519", "000858", "601318", "000333", "600036"]
    if not code_to_name:
        try:
            from backpack_quant_trading.core.stock_ai import _fetch_a_stock_list
            df_all = _fetch_a_stock_list()
            if df_all is not None and not df_all.empty and "code" in df_all.columns and "name" in df_all.columns:
                code_to_name = dict(zip(df_all["code"].astype(str).str.strip(), df_all["name"].astype(str).fillna("")))
        except Exception:
            pass

    model = load_model(model_path)
    end_str = datetime.now().strftime("%Y%m%d")
    start_str = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
    codes_to_run = stock_codes[:max_stocks]

    def _predict_one(code: str) -> Optional[dict]:
        try:
            df = _fetch_daily_for_train(code, start_str, end_str, ak)
            if df is None or len(df) < 50:
                return None
            row = get_latest_features_row(df)
            if row is None or row.empty:
                return None
            proba = float(predict_proba(model, row)[0])
            close = _safe_series(df, "close", "收盘")
            last_close = float(close.iloc[-1]) if close is not None and len(close) else None
            name = ""
            try:
                if "name" in df.columns:
                    name = str(df.iloc[-1].get("name", ""))
                elif "名称" in df.columns:
                    name = str(df.iloc[-1].get("名称", ""))
            except Exception:
                pass
            name = (code_to_name.get(code.strip()) or name or code.strip()).strip()
            return {
                "code": code.strip(),
                "name": name or code.strip(),
                "proba_up": round(proba, 4),
                "close": last_close,
                "date": today,
            }
        except Exception as e:
            logger.debug("预测 %s 失败: %s", code, e)
            return None

    results = []
    max_workers = min(6, len(codes_to_run))
    _single_timeout = 8
    _total_timeout = 60
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_predict_one, c): c for c in codes_to_run}
        try:
            for future in as_completed(futures, timeout=_total_timeout):
                try:
                    r = future.result(timeout=_single_timeout)
                    if r is not None:
                        results.append(r)
                except Exception:
                    pass
        except (FuturesTimeoutError, TimeoutError):
            logger.warning("每日预测部分请求超时，已返回当前已完成的 %s 只", len(results))
    results.sort(key=lambda x: -(x.get("proba_up") or 0))
    list_out = results[:top_n]

    if not skip_cache_write:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"date": today, "list": list_out}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return {"ok": True, "list": list_out, "date": today, "from_cache": False}


def _fetch_daily_for_train(
    code: str, start_str: str, end_str: str, ak
) -> Optional[pd.DataFrame]:
    """拉取单只股票日线，腾讯→新浪→东财 依次尝试，统一为 date/close/high/low/volume。"""
    pre = "sh" if code.strip().startswith("6") else "sz"
    full = f"{pre}{code.strip()}"
    rename = {
        "日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume",
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
    }
    # 1) 腾讯
    try:
        df = ak.stock_zh_a_hist_tx(symbol=full, start_date=start_str, end_date=end_str, adjust="qfq")
        if df is not None and len(df) >= 60:
            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
            if "date" not in df.columns and "日期" in df.columns:
                df["date"] = df["日期"]
            df["date"] = pd.to_datetime(df["date"])
            return df
    except Exception:
        pass
    # 2) 新浪
    try:
        f = getattr(ak, "stock_zh_a_daily", None)
        if f:
            df = f(symbol=full, start_date=start_str, end_date=end_str, adjust="qfq")
            if df is not None and len(df) >= 60:
                df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
                if "date" not in df.columns:
                    df = df.reset_index()
                    if "date" not in df.columns and "index" in df.columns:
                        df["date"] = pd.to_datetime(df["index"])
                    elif "date" not in df.columns and len(df.columns):
                        df["date"] = pd.to_datetime(df.index)
                if "close" not in df.columns and "收盘" in df.columns:
                    df["close"] = df["收盘"].astype(float)
                df["date"] = pd.to_datetime(df["date"])
                return df
    except Exception:
        pass
    # 3) 东财（无前缀）
    try:
        df = ak.stock_zh_a_hist(symbol=code.strip(), period="daily", start_date=start_str, end_date=end_str, adjust="qfq")
        if df is not None and len(df) >= 60:
            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
            if "date" not in df.columns and "日期" in df.columns:
                df["date"] = df["日期"]
            df["date"] = pd.to_datetime(df["date"])
            return df
    except Exception:
        pass
    return None


def run_train_with_akshare(
    stock_codes: Optional[list[str]] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 500,
    forward_days: int = 5,
    label_threshold: float = 0.02,
    val_ratio: float = 0.2,
    save_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    使用 akshare 拉取多只股票日线，合并成数据集后训练模型。
    优先复用选股同款日线接口（stock_ai._fetch_daily），提高成功率。
    """
    if not HAS_LIGHTGBM:
        return {"ok": False, "error": "请先安装: pip install lightgbm scikit-learn joblib"}

    try:
        from backpack_quant_trading.core import stock_ai as stock_ai_mod
        use_stock_ai_fetch = hasattr(stock_ai_mod, "_fetch_daily")
    except Exception:
        use_stock_ai_fetch = False

    try:
        import akshare as ak
    except ImportError:
        return {"ok": False, "error": "请先安装 akshare"}

    import time

    def _norm_code(c: str) -> str:
        """统一为 6 位数字代码，便于各数据源识别"""
        s = "".join(x for x in str(c).strip() if x.isdigit())
        if len(s) > 6:
            s = s[-6:]
        return s.zfill(6) if s else ""

    # 与选股完全同源：若未指定股票列表，从 A 股列表取主板(60/00)并抽样
    if not stock_codes and use_stock_ai_fetch:
        try:
            df_all = stock_ai_mod._fetch_a_stock_list()
            if df_all is not None and not df_all.empty:
                pool = [_norm_code(c) for c in df_all["code"].astype(str).tolist()]
                pool = [c for c in pool if c and (c.startswith("60") or c.startswith("00"))]
                pool = list(dict.fromkeys(pool))
                if len(pool) >= 15:
                    import random
                    random.seed(42)
                    stock_codes = random.sample(pool, min(20, len(pool)))
                    logger.info("训练使用选股同源股票池，共 %s 只", len(stock_codes))
        except Exception as e:
            logger.debug("获取选股同源池失败: %s", e)
    if not stock_codes:
        stock_codes = ["000001", "000002", "600000", "600519", "000858", "601318", "000333", "600036"]
    # 统一为 6 位代码，过滤无效
    stock_codes = [_norm_code(c) for c in stock_codes if _norm_code(c)]
    if not stock_codes:
        return {"ok": False, "error": "没有有效的 6 位股票代码。请填写如 000001、600519。"}

    end_d = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
    start_d = end_d - timedelta(days=lookback_days)
    start_str = start_d.strftime("%Y%m%d")
    end_str = end_d.strftime("%Y%m%d")

    all_X = []
    all_y = []
    tried = []
    for i, code in enumerate(stock_codes[:50]):
        if i > 0:
            time.sleep(1.5)
        try:
            df = None
            if use_stock_ai_fetch:
                df = stock_ai_mod._fetch_daily(code, adjust="qfq")
                if df is not None and len(df) >= 60:
                    df = df.sort_values("date").reset_index(drop=True)
                    df = df.tail(lookback_days)
                    if len(df) < 60:
                        df = None
            if df is None:
                df = _fetch_daily_for_train(code, start_str, end_str, ak)
            if df is None or len(df) < 60:
                tried.append(code)
                logger.debug("跳过 %s: 数据不足", code)
                continue
            X, y = build_dataset_from_daily(df, forward_days=forward_days, label_threshold=label_threshold)
            if len(X) > 0 and len(y) > 0:
                all_X.append(X)
                all_y.append(y)
                logger.info("已拉取 %s 样本数 %s", code, len(X))
        except Exception as e:
            tried.append(code)
            logger.warning("获取 %s 日线失败: %s", code, e)
            continue

    if not all_X:
        hint = "已尝试: " + ", ".join(tried[:15]) + ("..." if len(tried) > 15 else "")
        return {
            "ok": False,
            "error": "没有成功拉取到足够日线数据。请检查：1) 网络与 akshare 版本 2) 股票代码为 6 位 3) 可先试 --codes 000001 600519。"
            + (" " + hint if tried else ""),
        }

    features = pd.concat(all_X, axis=0, ignore_index=True)
    label = pd.concat(all_y, axis=0, ignore_index=True)
    # 再对齐
    features = features.fillna(0)
    n_samples = len(features)
    if n_samples < 100:
        return {"ok": False, "error": f"有效样本数 {n_samples} 过少，请增加股票或时间范围"}

    model = train_model(features, label, val_ratio=val_ratio)
    path = save_model(model, save_path)

    return {
        "ok": True,
        "model_path": path,
        "n_samples": n_samples,
        "n_stocks": len(all_X),
        "forward_days": forward_days,
        "label_threshold": label_threshold,
    }

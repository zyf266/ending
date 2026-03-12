"""A股AI选股 API：板块/行业筛选 + 多指标综合打分 + 预测模型训练"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from backpack_quant_trading.api.deps import get_current_user
from backpack_quant_trading.core.stock_ai import (
    get_board_options,
    get_industry_options,
    run_ai_stock_screen,
    deepseek_analyze_stocks,
    deepseek_analyze_stocks_with_daily,
    deepseek_analyze_single_stock,
    StockAiConfig,
    HAS_AKSHARE,
)
from backpack_quant_trading.core.stock_predict_model import run_train_with_akshare, run_daily_predict
from backpack_quant_trading.core.stock_kline_cache import ensure_incremental

router = APIRouter()
logger = logging.getLogger(__name__)


class StockAiScreenRequest(BaseModel):
    boards: List[str] = []
    industries: List[str] = []
    top_n: int = 30
    min_score: float = 0.0
    lookback_days: int = 120


@router.get("/boards")
def list_boards():
    """板块选项：主板、创业板、科创板、北交所等（无需登录即可加载）"""
    try:
        options = get_board_options()
        return {"options": options or []}
    except Exception as e:
        logger.warning("获取板块列表失败: %s", e)
        return {"options": [{"value": "主板", "label": "主板（沪市+深市）"}, {"value": "创业板", "label": "创业板"}, {"value": "科创板", "label": "科创板"}, {"value": "北交所", "label": "北交所"}]}


@router.get("/industries")
def list_industries():
    """行业选项：化学原料、贵金属、电力等（无需登录即可加载，失败时返回默认列表）"""
    try:
        options = get_industry_options()
        return {"options": options or []}
    except Exception as e:
        logger.warning("获取行业列表失败: %s", e)
        return {"options": [{"value": "化学原料", "label": "化学原料"}, {"value": "电力", "label": "电力"}, {"value": "银行", "label": "银行"}, {"value": "半导体", "label": "半导体"}]}


@router.post("/refresh-cache")
def refresh_kline_cache(user: dict = Depends(get_current_user)):
    """刷新 K 线缓存：执行增量更新（优先 pytdx，可选 Tushare），只拉取比缓存更新的交易日数据。需登录。"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        result = ensure_incremental()
        return {
            "ok": result.get("ok", False),
            "message": result.get("message", ""),
            "rows_added": result.get("rows_added", 0),
            "max_date": result.get("max_date"),
            "source": result.get("source"),
        }
    except Exception as e:
        logger.exception("刷新 K 线缓存失败: %s", e)
        return {
            "ok": False,
            "message": f"刷新失败: {str(e)}",
            "rows_added": 0,
            "max_date": None,
            "source": None,
        }


@router.post("/screen")
def screen_stocks(req: StockAiScreenRequest, user: dict = Depends(get_current_user)):
    """执行 AI 选股：按板块/行业筛选，多指标打分排序，返回 top_n。任何异常均返回 200 + error，不返回 5xx。"""
    try:
        if not user:
            raise HTTPException(status_code=401, detail="请先登录")
        if not HAS_AKSHARE:
            return {
                "list": [],
                "total": 0,
                "boards": req.boards or [],
                "industries": req.industries or [],
                "error": "未安装 akshare，请先执行: pip install akshare",
            }
        config = StockAiConfig(
            boards=req.boards or [],
            industries=req.industries or [],
            top_n=min(100, max(1, req.top_n)),
            min_score=max(0.0, req.min_score),
            lookback_days=min(250, max(30, req.lookback_days)),
        )
        results, meta = run_ai_stock_screen(config)
        return {
            "list": results,
            "total": len(results),
            "boards": config.boards,
            "industries": config.industries,
            "candidates_count": meta.get("candidates_count", 0),
            "from_full_market": meta.get("from_full_market", False),
            "error": None,
        }
    except Exception as e:
        logger.exception("选股执行失败: %s", e)
        return {
            "list": [],
            "total": 0,
            "boards": getattr(req, "boards", []) or [],
            "industries": getattr(req, "industries", []) or [],
            "candidates_count": 0,
            "from_full_market": False,
            "error": f"选股执行失败: {str(e)}（请检查网络与 akshare，或查看后端日志）",
        }


class StockAiAnalyzeRequest(BaseModel):
    items: List[dict] = []  # 选股结果列表，每项含 code/name/score/details/close/pct_chg 等


@router.post("/analyze")
def analyze_with_deepseek(req: StockAiAnalyzeRequest, user: dict = Depends(get_current_user)):
    """用 DeepSeek 对当前选股结果做简要解读与操作建议（需配置 DEEPSEEK_API_KEY）"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    analysis = deepseek_analyze_stocks(req.items or [], max_items=15)
    return {"analysis": analysis}


@router.post("/analyze-with-daily")
def analyze_with_daily(req: StockAiAnalyzeRequest, user: dict = Depends(get_current_user)):
    """拉取选股日线后交给 DeepSeek：知识库 + 资深 A 股交易员角色，做日线技术分析（趋势/策略/交易参数）"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    analysis = deepseek_analyze_stocks_with_daily(req.items or [], max_items=10, daily_bars=55)
    return {"analysis": analysis}


class StockSingleAnalyzeRequest(BaseModel):
    stock_code: str = ""  # 6 位 A 股代码，如 000001、600519


@router.post("/analyze-single")
def analyze_single_stock(req: StockSingleAnalyzeRequest, user: dict = Depends(get_current_user)):
    """根据输入的股票代码从数据源拉取日 K，交给 DeepSeek 做单只股票分析。需登录并配置 DEEPSEEK_API_KEY。"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    code = (req.stock_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="请输入股票代码")
    analysis = deepseek_analyze_single_stock(code, daily_bars=55)
    return {"analysis": analysis}


class StockPredictTrainRequest(BaseModel):
    """预测模型训练请求：用多只股票历史日线训练 LightGBM 二分类（预测 N 日后是否上涨）"""
    stock_codes: List[str] = []  # 如 ["000001", "600000"]，空则用默认池
    end_date: Optional[str] = None  # YYYY-MM-DD，默认今天
    lookback_days: int = 500
    forward_days: int = 5
    label_threshold: float = 0.02  # 未来收益 > 2% 标为 1
    val_ratio: float = 0.2


@router.post("/train-model")
async def train_predict_model(req: StockPredictTrainRequest, user: dict = Depends(get_current_user)):
    """训练 3~5 日涨跌预测模型（LightGBM）。在后台线程执行，避免阻塞与 CancelledError。需登录。"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    # 空则交给 run_train_with_akshare 从选股同源池（_fetch_a_stock_list 主板抽样）取股
    codes = req.stock_codes if req.stock_codes else None
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: run_train_with_akshare(
            stock_codes=codes,
            end_date=req.end_date,
            lookback_days=min(1000, max(120, req.lookback_days)),
            forward_days=min(10, max(1, req.forward_days)),
            label_threshold=req.label_threshold,
            val_ratio=req.val_ratio,
        ),
    )
    return result


class DailyPredictRequest(BaseModel):
    top_n: int = 20
    use_cache: bool = True  # 当日已跑过则直接返回缓存
    force_refresh: bool = False  # True 时忽略缓存重新算
    stock_codes: Optional[List[str]] = None  # 指定股票池时，对该池做预测（与选股结果一致）；空则用全市场随机抽样


@router.post("/daily-predict")
def daily_predict(req: DailyPredictRequest, user: dict = Depends(get_current_user)):
    """每日预测：用已训练模型对股票池打分，返回「未来 3~5 日看涨」概率排序。可传 stock_codes 对选股结果预测。需登录。"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    # 指定了股票池（如选股结果）时，强制不用缓存、只对该池预测，且不写入默认缓存
    use_custom_pool = bool(req.stock_codes)
    result = run_daily_predict(
        stock_codes=req.stock_codes if use_custom_pool else None,
        model_path=None,
        top_n=min(50, max(5, req.top_n)),
        use_cache=False if use_custom_pool else not req.force_refresh,
        max_stocks=len(req.stock_codes) if use_custom_pool else 30,
        skip_cache_write=use_custom_pool,
    )
    return result

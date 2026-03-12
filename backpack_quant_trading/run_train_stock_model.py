#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
命令行训练 A 股 3~5 日涨跌预测模型（LightGBM）。
用法:
  cd backpack_quant_trading
  pip install lightgbm scikit-learn akshare
  python run_train_stock_model.py
  python run_train_stock_model.py --codes 000001 600000 000858 --days 5
"""
import argparse
import sys
from pathlib import Path

# 项目根 = 当前脚本所在目录的上一级（含 backpack_quant_trading 的目录）
_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root))

from backpack_quant_trading.core.stock_predict_model import run_train_with_akshare, DEFAULT_MODEL_PATH


def main():
    parser = argparse.ArgumentParser(description="训练 A 股涨跌预测模型")
    parser.add_argument("--codes", nargs="*", default=["000001", "000002", "600000", "600519", "000858"],
                        help="股票代码列表，如 000001 600000")
    parser.add_argument("--days", type=int, default=5, help="预测未来几日涨跌 (默认 5)")
    parser.add_argument("--lookback", type=int, default=500, help="历史日线回溯天数 (默认 500)")
    parser.add_argument("--threshold", type=float, default=0.02, help="涨跌阈值，超过视为涨 (默认 0.02 即 2%%)")
    parser.add_argument("--out", type=str, default=None, help="模型保存路径，默认项目 models/stock_predict_lgb.txt")
    args = parser.parse_args()

    result = run_train_with_akshare(
        stock_codes=args.codes,
        end_date=None,
        lookback_days=args.lookback,
        forward_days=args.days,
        label_threshold=args.threshold,
        val_ratio=0.2,
        save_path=args.out or DEFAULT_MODEL_PATH,
    )

    if result.get("ok"):
        print("训练完成.")
        print("  模型路径:", result.get("model_path"))
        print("  样本数:", result.get("n_samples"))
        print("  股票数:", result.get("n_stocks"))
        print("  预测周期: 未来 %s 日" % result.get("forward_days"))
    else:
        print("训练失败:", result.get("error", "未知错误"))
        sys.exit(1)


if __name__ == "__main__":
    main()

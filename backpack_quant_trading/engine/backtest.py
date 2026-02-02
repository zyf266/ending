import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from ..strategy.base import BaseStrategy
from ..core.data_manager import DataManager
from ..core.risk_manager import RiskManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


class BacktestResult:
    """回测结果"""

    def __init__(self):
        self.total_return = 0.0
        self.annualized_return = 0.0
        self.sharpe_ratio = 0.0
        self.max_drawdown = 0.0
        self.win_rate = 0.0
        self.profit_factor = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.trades = []


@dataclass
class Trade:
    """交易记录"""
    symbol: str
    action: str  # 'buy' or 'sell'
    quantity: float
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: datetime = None
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pnl_percent: float = 0.0
    commission: float = 0.0
    reason: str = ""


class BacktestEngine:
    """回测引擎"""

    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.positions: Dict[str, float] = {}
        self.trades: List[Trade] = []
        self.portfolio_values = []
        self.dates = []

        # 回测配置
        self.commission_rate = 0.001  # 0.1% 手续费
        self.slippage = 0.0005  # 0.05% 滑点

    def run(self, strategy: BaseStrategy, data: Dict[str, pd.DataFrame],
            start_date: datetime, end_date: datetime) -> BacktestResult:
        """运行回测"""
        logger.info(f"开始回测: {start_date} 到 {end_date}")

        result = BacktestResult()

        if not data:
            logger.warning("没有数据可用于回测")
            return result

        all_timestamps = set()
        for df in data.values():
            all_timestamps.update(df.index)

        all_dates = sorted(all_timestamps)

        for current_date in all_dates:
            current_data = {}
            for symbol, df in data.items():
                if current_date in df.index:
                    hist_data = df.loc[:current_date].copy()
                    if not isinstance(hist_data, pd.DataFrame):
                        hist_data = df[df.index <= current_date].copy()
                    current_data[symbol] = hist_data

            if not current_data:
                continue

            import asyncio
            signals = asyncio.run(strategy.calculate_signal(current_data))

            for signal in signals:
                self.execute_trade(signal, current_date)

            self.update_portfolio_value(current_data, current_date)

        result = self.calculate_metrics()

        return result

    def execute_trade(self, signal, current_date):
        """执行交易"""
        if signal.action == 'buy':
            self._execute_buy(signal, current_date)
        elif signal.action == 'sell':
            self._execute_sell(signal, current_date)

    def _execute_buy(self, signal, current_date):
        """执行买入"""
        # 计算实际成交价格（考虑滑点）
        actual_price = signal.price * (1 + self.slippage)

        # 计算手续费
        commission = actual_price * signal.quantity * self.commission_rate

        # 检查资金是否足够
        trade_value = actual_price * signal.quantity + commission
        if trade_value > self.capital:
            logger.warning(f"资金不足，无法执行买入: 需要 {trade_value}, 可用 {self.capital}")
            return

        # 记录交易
        trade = Trade(
            symbol=signal.symbol,
            action='buy',
            quantity=signal.quantity,
            entry_price=actual_price,
            entry_time=current_date,
            commission=commission,
            reason=signal.reason
        )

        # 更新仓位和资金
        self.positions[signal.symbol] = self.positions.get(signal.symbol, 0) + signal.quantity
        self.capital -= trade_value

        self.trades.append(trade)
        logger.info(f"买入 {signal.symbol}: {signal.quantity} @ {actual_price:.4f}")

    def _execute_sell(self, signal, current_date):
        """执行卖出"""
        if signal.symbol not in self.positions or self.positions[signal.symbol] <= 0:
            logger.warning(f"没有 {signal.symbol} 的仓位可以卖出")
            return

        # 计算实际成交价格（考虑滑点）
        actual_price = signal.price * (1 - self.slippage)

        # 计算手续费
        commission = actual_price * signal.quantity * self.commission_rate

        # 计算盈亏
        entry_price = self._get_average_entry_price(signal.symbol)
        pnl = (actual_price - entry_price) * signal.quantity - commission

        # 记录交易
        trade = Trade(
            symbol=signal.symbol,
            action='sell',
            quantity=signal.quantity,
            entry_price=entry_price,
            exit_price=actual_price,
            entry_time=current_date,
            exit_time=current_date,
            pnl=pnl,
            pnl_percent=(pnl / (entry_price * signal.quantity)) * 100,
            commission=commission,
            reason=signal.reason
        )

        # 更新仓位和资金
        self.positions[signal.symbol] -= signal.quantity
        if self.positions[signal.symbol] <= 0:
            del self.positions[signal.symbol]

        self.capital += actual_price * signal.quantity - commission

        self.trades.append(trade)
        logger.info(f"卖出 {signal.symbol}: {signal.quantity} @ {actual_price:.4f}, PnL: {pnl:.2f}")

    def _get_average_entry_price(self, symbol: str) -> float:
        """获取平均入场价格"""
        symbol_trades = [t for t in self.trades if t.symbol == symbol and t.action == 'buy']
        if not symbol_trades:
            return 0
        total_cost = sum(t.entry_price * t.quantity for t in symbol_trades)
        total_quantity = sum(t.quantity for t in symbol_trades)
        return total_cost / total_quantity if total_quantity > 0 else 0

    def update_portfolio_value(self, current_data, current_date):
        """更新组合价值"""
        portfolio_value = float(self.capital)

        for symbol, df in current_data.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                price = float(df.iloc[-1]['close'])
                if symbol in self.positions:
                    portfolio_value += price * self.positions[symbol]

        self.portfolio_values.append(portfolio_value)
        self.dates.append(current_date)

    def calculate_metrics(self):
        """计算回测指标"""
        result = BacktestResult()

        if not self.portfolio_values:
            return result

        # 计算收益率
        returns = pd.Series(self.portfolio_values).pct_change().dropna()
        total_return = (self.portfolio_values[-1] / self.initial_capital - 1) * 100

        days = (self.dates[-1] - self.dates[0]).days
        annualized_return = ((1 + total_return / 100) ** (365 / days) - 1) * 100

        returns_array = np.diff(self.portfolio_values).astype(float) / np.array(self.portfolio_values[:-1], dtype=float)
        if len(returns_array) > 1 and np.std(returns_array) > 0:
            sharpe_ratio = (np.mean(returns_array) * np.sqrt(252)) / np.std(returns_array)
        else:
            sharpe_ratio = 0

        # 计算最大回撤
        portfolio_series = pd.Series(self.portfolio_values, index=self.dates)
        rolling_max = portfolio_series.expanding().max()
        drawdowns = (portfolio_series - rolling_max) / rolling_max
        max_drawdown = abs(drawdowns.min()) * 100

        # 计算胜率
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]

        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0

        # 计算盈利因子
        total_profit = sum(t.pnl for t in winning_trades)
        total_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        # 填充结果
        result.total_return = total_return
        result.annualized_return = annualized_return
        result.sharpe_ratio = sharpe_ratio
        result.max_drawdown = max_drawdown
        result.win_rate = win_rate
        result.profit_factor = profit_factor
        result.total_trades = len(self.trades)
        result.winning_trades = len(winning_trades)
        result.losing_trades = len(losing_trades)
        result.trades = self.trades

        return result

    def generate_report(self, result: BacktestResult):
        """生成回测报告"""
        report = f"""
        ===================== 回测报告 =====================
        初始资金: ${self.initial_capital:,.2f}
        最终资金: ${self.portfolio_values[-1]:,.2f}
        总收益率: {result.total_return:.2f}%
        年化收益率: {result.annualized_return:.2f}%
        夏普比率: {result.sharpe_ratio:.2f}
        最大回撤: {result.max_drawdown:.2f}%
        胜率: {result.win_rate:.2f}%
        盈利因子: {result.profit_factor:.2f}
        总交易次数: {result.total_trades}
        盈利交易: {result.winning_trades}
        亏损交易: {result.losing_trades}
        =================================================
        """

        logger.info(report)
        return report
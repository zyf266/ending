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
        self.positions: Dict[str, Dict] = {}  # 双向持仓: {symbol: {long: {...}, short: {...}}}
        self.trades: List[Trade] = []
        self.portfolio_values = []
        self.dates = []

        # 回测配置
        self.commission_rate = 0.001  # 0.1% 手续费
        self.slippage = 0.0005  # 0.05% 滑点

    async def run(self, strategy: BaseStrategy, data: Dict[str, pd.DataFrame],
            start_date: datetime, end_date: datetime) -> BacktestResult:
        """运行回测（异步）"""
        logger.info(f"开始回测: {start_date} 到 {end_date}")

        result = BacktestResult()

        if not data:
            logger.warning("没有数据可用于回测")
            return result

        all_timestamps = set()
        for df in data.values():
            all_timestamps.update(df.index)

        all_dates = sorted(all_timestamps)
        
        # 【关键修复】预热期：跳过前100根K线，让指标计算充分
        warmup_bars = 100
        if len(all_dates) > warmup_bars:
            logger.info(f"🔥 预热期: 跳过前{warmup_bars}根K线")
            all_dates = all_dates[warmup_bars:]

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
            signals = await strategy.calculate_signal(current_data)

            for signal in signals:
                self.execute_trade(signal, current_date)
                            
            # 记录资金曲线
            self.portfolio_values.append(self.capital)
            self.dates.append(current_date)

        result = self.calculate_metrics()

        return result

    def execute_trade(self, signal, current_date):
        """执行交易（支持多空双向持仓）"""
        symbol = signal.symbol
        action = signal.action
        price = float(signal.price) if signal.price else 0
        quantity = float(signal.quantity) if signal.quantity else 0
        
        # 初始化持仓
        if symbol not in self.positions:
            self.positions[symbol] = {
                'long': {'qty': 0, 'entry_price': 0, 'margin': 0},
                'short': {'qty': 0, 'entry_price': 0, 'margin': 0}
            }
        
        pos = self.positions[symbol]
        
        # BUY: 有空仓则平空，否则开多
        if action == 'buy':
            if pos['short']['qty'] > 0:
                self._close_short(symbol, quantity, price, current_date, signal.reason)
            else:
                self._open_long(symbol, quantity, price, current_date, signal.reason)
        # SELL: 有多仓则平多，否则开空
        elif action == 'sell':
            if pos['long']['qty'] > 0:
                self._close_long(symbol, quantity, price, current_date, signal.reason)
            else:
                self._open_short(symbol, quantity, price, current_date, signal.reason)

    def _open_long(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """开多仓"""
        # 【关键修复】如果已有多仓，不允许重复开仓
        if self.positions[symbol]['long']['qty'] > 0:
            logger.warning(f"已有多仓，拒绝重复开多")
            return
        
        actual_price = price * (1 + self.slippage)
        leverage = 100
        margin = (actual_price * quantity) / leverage
        commission = margin * self.commission_rate
        trade_value = margin + commission
        
        if trade_value > self.capital:
            logger.warning(f"资金不足，无法开多")
            return
        
        self.positions[symbol]['long'] = {'qty': quantity, 'entry_price': actual_price, 'margin': margin}
        self.capital -= trade_value
        
        self.trades.append(Trade(
            symbol=symbol, action='buy', quantity=quantity, entry_price=actual_price,
            entry_time=current_date, commission=commission, reason=reason
        ))
        logger.info(f"开多 {symbol}: {quantity:.4f} @ {actual_price:.2f}")
        
        # 【关键】同步给策略（保持兼容）
        # 注意：这里需要访问策略对象，但回测引擎不应该依赖策略
        # 所以我们让策略自己管理持仓，但需要确保策略能找到持仓
    
    def _open_short(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """开空仓"""
        # 【关键修复】如果已有空仓，不允许重复开仓
        if self.positions[symbol]['short']['qty'] > 0:
            logger.warning(f"已有空仓，拒绝重复开空")
            return
        
        actual_price = price * (1 - self.slippage)
        leverage = 100
        margin = (actual_price * quantity) / leverage
        commission = margin * self.commission_rate
        trade_value = margin + commission
        
        if trade_value > self.capital:
            logger.warning(f"资金不足，无法开空")
            return
        
        self.positions[symbol]['short'] = {'qty': quantity, 'entry_price': actual_price, 'margin': margin}
        self.capital -= trade_value
        
        self.trades.append(Trade(
            symbol=symbol, action='sell', quantity=quantity, entry_price=actual_price,
            entry_time=current_date, commission=commission, reason=reason
        ))
        logger.info(f"开空 {symbol}: {quantity:.4f} @ {actual_price:.2f}")
    
    def _close_long(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """平多仓"""
        pos = self.positions[symbol]['long']
        if pos['qty'] <= 0:
            return
        
        actual_price = price * (1 - self.slippage)
        leverage = 100
        price_change = (actual_price - pos['entry_price']) / pos['entry_price']
        pnl = pos['margin'] * price_change * leverage
        commission = pos['margin'] * self.commission_rate
        final_pnl = pnl - commission
        
        self.capital += pos['margin'] + final_pnl
        self.positions[symbol]['long'] = {'qty': 0, 'entry_price': 0, 'margin': 0}
        
        self.trades.append(Trade(
            symbol=symbol, action='sell', quantity=pos['qty'],
            entry_price=pos['entry_price'], exit_price=actual_price,
            entry_time=current_date, exit_time=current_date,
            pnl=final_pnl, pnl_percent=(final_pnl/pos['margin'])*100,
            commission=commission, reason=reason
        ))
        logger.info(f"平多 {symbol}: PnL={final_pnl:.2f}")
    
    def _close_short(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """平空仓"""
        pos = self.positions[symbol]['short']
        if pos['qty'] <= 0:
            return
        
        actual_price = price * (1 + self.slippage)
        leverage = 100
        price_change = (pos['entry_price'] - actual_price) / pos['entry_price']
        pnl = pos['margin'] * price_change * leverage
        commission = pos['margin'] * self.commission_rate
        final_pnl = pnl - commission
        
        self.capital += pos['margin'] + final_pnl
        self.positions[symbol]['short'] = {'qty': 0, 'entry_price': 0, 'margin': 0}
        
        self.trades.append(Trade(
            symbol=symbol, action='buy', quantity=pos['qty'],
            entry_price=pos['entry_price'], exit_price=actual_price,
            entry_time=current_date, exit_time=current_date,
            pnl=final_pnl, pnl_percent=(final_pnl/pos['margin'])*100,
            commission=commission, reason=reason
        ))
        logger.info(f"平空 {symbol}: PnL={final_pnl:.2f}")


    def calculate_metrics(self):
        """计算回测指标"""
        result = BacktestResult()

        if not self.portfolio_values:
            return result

        # 计算收益率
        returns = pd.Series(self.portfolio_values).pct_change().dropna()
        total_return = (self.portfolio_values[-1] / self.initial_capital - 1) * 100

        days = (self.dates[-1] - self.dates[0]).days if len(self.dates) > 1 else 0
        annualized_return = ((1 + total_return / 100) ** (365 / days) - 1) * 100 if days > 0 else 0

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
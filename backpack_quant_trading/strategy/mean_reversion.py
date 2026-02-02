import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass

from .base import BaseStrategy, Signal, Position
from ..config.settings import config  # 导入配置实例

logger = logging.getLogger(__name__)  # 添加日志记录器


@dataclass
class MeanReversionParams:
    """均线回归策略参数"""
    lookback_period: int = 5  # 回看周期（为了快速测试减少到5个周期）
    zscore_threshold: float = 1.0  # Z分数阈值
    position_size: float = 0.03  # 仓位大小比例
    stop_loss_percent: float = 0.02  # 止损百分比
    take_profit_percent: float = 0.03  # 止盈百分比


class MeanReversionStrategy(BaseStrategy):
    """均值回归策略"""

    def __init__(self, symbols: List[str], api_client, risk_manager):
        super().__init__("MeanReversion", symbols, api_client, risk_manager)
        self.params = MeanReversionParams()
        self.price_history: Dict[str, pd.DataFrame] = {}

    async def calculate_signal(self, data: Dict[str, pd.DataFrame]) -> List[Signal]:
        """计算均值回归信号"""
        signals = []

        for symbol, df in data.items():
            logger.info(f"[{symbol}] 开始分析，数据量: {len(df)}, 需要: {self.params.lookback_period}")
            
            if len(df) < self.params.lookback_period:
                logger.warning(f"{symbol}数据不足，需要至少{self.params.lookback_period}个周期")
                continue

            # 计算移动平均和标准差
            df['MA'] = df['close'].rolling(window=self.params.lookback_period).mean()
            df['STD'] = df['close'].rolling(window=self.params.lookback_period).std()

            # 修正Z分数计算公式
            df['Zscore'] = (df['close'] - df['MA']) / df['STD'].replace(0, np.nan)
            # 避免除零错误，将标准差为0的替换为NaN

            current_price = df['close'].iloc[-1]
            current_zscore = df['Zscore'].iloc[-1]
            
            logger.info(f"[{symbol}] 当前价格: {current_price:.2f}, Z-Score: {current_zscore:.4f}, 阈值: ±{self.params.zscore_threshold}")

            # 检查是否为有效数值
            if pd.isna(current_zscore):
                logger.warning(f"[{symbol}] Z-Score为NaN，跳过")
                continue

            # 生成交易信号
            if symbol in self.positions:
                position = self.positions[symbol]
                logger.info(f"[{symbol}] 当前持仓: {position.side} {position.quantity}")
                # 检查是否应该平仓
                if self.should_exit_position(position, df.iloc[-1]):
                    exit_signal = self.generate_exit_signal(symbol, "mean_reversion_exit")
                    logger.info(f"[{symbol}] 生成平仓信号")
                    signals.append(exit_signal)

            else:
                logger.info(f"[{symbol}] 当前无持仓，检查开仓条件...")
                # 生成新的信号
                if current_zscore < -self.params.zscore_threshold:
                    # 价格过低，买入信号
                    quantity = await self._calculate_position_size(symbol, current_price)
                    # 【修复】只有计算出有效数量时才生成信号
                    if quantity > 0:
                        logger.info(f"[{symbol}] ✅ Z-Score过低 ({current_zscore:.4f} < -{self.params.zscore_threshold})，生成买入信号，数量: {quantity}")
                        
                        signal = Signal(
                            symbol=symbol,
                            action='buy',
                            quantity=quantity,
                            price=current_price,
                            stop_loss=current_price * (1 - self.params.stop_loss_percent),
                            take_profit=current_price * (1 + self.params.take_profit_percent),
                            confidence=min(abs(current_zscore) / self.params.zscore_threshold, 1.0),
                            reason=f"Z-Score oversold: {current_zscore:.2f}"
                        )
                        signals.append(signal)
                    else:
                        logger.warning(f"[{symbol}] 计算出的仓位数量为0（余额不足或风控拦截），跳过买入信号生成")

                elif current_zscore > self.params.zscore_threshold:
                    # 价格过高，卖出信号
                    quantity = await self._calculate_position_size(symbol, current_price)
                    # 【修复】只有计算出有效数量时才生成信号
                    if quantity > 0:
                        logger.info(f"[{symbol}] ✅ Z-Score过高 ({current_zscore:.4f} > {self.params.zscore_threshold})，生成卖出信号，数量: {quantity}")
                        
                        signal = Signal(
                            symbol=symbol,
                            action='sell',
                            quantity=quantity,
                            price=current_price,
                            stop_loss=current_price * (1 + self.params.stop_loss_percent),
                            take_profit=current_price * (1 - self.params.take_profit_percent),
                            confidence=min(abs(current_zscore) / self.params.zscore_threshold, 1.0),
                            reason=f"Z-Score overbought: {current_zscore:.2f}"
                        )
                        signals.append(signal)
                    else:
                        logger.warning(f"[{symbol}] 计算出的仓位数量为0（余额不足或风控拦截），跳过卖出信号生成")
                else:
                    logger.info(f"[{symbol}] Z-Score在正常范围内 ({current_zscore:.4f})，不生成信号")

        return signals

    def should_exit_position(self, position: Position, current_data: pd.Series) -> bool:
        """判断是否需要平仓 - 修正返回类型"""
        exit_needed, reason = self._should_exit_with_reason(position, current_data)
        if exit_needed:
            logger.info(f"平仓信号: {position.symbol}, 原因: {reason}")
        return exit_needed

    def _should_exit_with_reason(self, position: Position,
                                 current_data: pd.Series) -> Tuple[bool, str]:
        """内部方法：返回平仓判断和原因"""
        current_price = current_data['close']

        # 检查止损止盈
        if position.stop_loss and position.take_profit:
            if position.side == 'long':
                if current_price <= position.stop_loss:
                    return True, "stop_loss"
                if current_price >= position.take_profit:
                    return True, "take_profit"
            else:  # short position
                if current_price >= position.stop_loss:
                    return True, "stop_loss"
                if current_price <= position.take_profit:
                    return True, "take_profit"

        # 检查Z分数是否回归到均值
        zscore = current_data.get('Zscore', 0)
        if abs(zscore) < 0.5:  # 接近均值时平仓
            return True, "mean_reversion"

        return False, ""

    async def _calculate_position_size(self, symbol: str, price: float) -> float:
        """计算仓位大小"""
        try:
            # 获取可用余额（优先使用USDT）
            if self.api_client is not None:
                # 实盘模式：动态获取账户余额
                balances = await self.api_client.get_balances()
                logger.info(f"获取到API返回的余额原始数据: {balances}")
                
                # 优先查找USDT余额
                if 'USDT' in balances:
                    usdt_data = balances['USDT']
                    logger.info(f"USDT数据: {usdt_data}")
                    # 尝试不同的字段名
                    if 'available' in usdt_data:
                        balance = float(usdt_data['available'])
                        quote_currency = 'USDT'
                    elif 'availableBalance' in usdt_data:
                        balance = float(usdt_data['availableBalance'])
                        quote_currency = 'USDT'
                    elif 'free' in usdt_data:
                        balance = float(usdt_data['free'])
                        quote_currency = 'USDT'
                    else:
                        logger.error(f"USDT数据中找不到可用余额字段: {usdt_data.keys()}")
                        balance = 0.0
                        quote_currency = 'USDT'
                    logger.info(f"获取到账户{quote_currency}余额: {balance:.2f}")
                # 如果USDT不可用，尝试USDC
                elif 'USDC' in balances:
                    usdc_data = balances['USDC']
                    logger.info(f"USDC数据: {usdc_data}")
                    # 尝试不同的字段名
                    if 'available' in usdc_data:
                        balance = float(usdc_data['available'])
                        quote_currency = 'USDC'
                    elif 'availableBalance' in usdc_data:
                        balance = float(usdc_data['availableBalance'])
                        quote_currency = 'USDC'
                    elif 'free' in usdc_data:
                        balance = float(usdc_data['free'])
                        quote_currency = 'USDC'
                    else:
                        logger.error(f"USDC数据中找不到可用余额字段: {usdc_data.keys()}")
                        balance = 0.0
                        quote_currency = 'USDC'
                    logger.info(f"获取到账户{quote_currency}余额: {balance:.2f}")
                else:
                    logger.warning(f"未找到USDT或USDC余额，可用货币: {list(balances.keys())}")
                    balance = 0.0
                    quote_currency = '未知'
            else:
                # 回测模式
                balance = 10000.0
                quote_currency = 'USDT'

            if balance <= 0:
                logger.warning(f"{quote_currency}余额不足: {balance}")
                return 0

            # 【关键修复】Dashboard 传入的 position_size 是保证金的绝对数量，不是比例
            # 例如：输入 2.0 表示使用 2 USDT 作为保证金
            margin = float(self.params.position_size)  # 直接使用绝对数量
                        
            # 检查保证金是否超过账户余额
            if margin > balance:
                logger.warning(f"保证金{margin:.2f} {quote_currency}超过账户余额{balance:.2f}")
                return 0
            
            # 使用当前配置的杠杆值（已被 main.py 从 Dashboard 参数覆盖）
            leverage = config.trading.LEVERAGE
            position_value = margin * leverage  # 实际持仓价值
                        
            logger.info(f"计算仓位: 余额={balance:.2f} {quote_currency}, 保证金={margin:.2f} {quote_currency}, 杠杆={leverage}x, 持仓价值={position_value:.2f}")
            
            # 【修复】风险检查传入保证金，而不是持仓价值
            if hasattr(self.risk_manager, 'validate_position'):
                if not self.risk_manager.validate_position(symbol, margin, account_capital=balance):
                    logger.warning(f"风险检查未通过: {symbol}")
                    return 0
    
            # 计算数量
            quantity = position_value / price
    
            # 考虑最小交易单位
            min_qty = 0.0001  # Backpack最小交易数量为0.0001
            if quantity < min_qty:
                logger.warning(f"交易数量{quantity:.6f}小于最小要求{min_qty}")
                return 0
    
            logger.info(f"计算得到交易数量: {quantity:.6f} (持仓价值={position_value:.2f} / 价格={price:.2f})")
            return round(quantity, 6)  # 保留6位小数
    
        except Exception as e:
            logger.error(f"计算仓位大小失败: {e}", exc_info=True)
            return 0

    async def generate_signal(self, df: pd.DataFrame, symbol: str = None) -> Signal:
        """生成交易信号（与calculate_signal兼容）
        
        Args:
            df: 包含K线数据和技术指标的DataFrame
            symbol: 交易对名称
        
        Returns:
            Signal: 交易信号
        """
        if symbol:
            signals = await self.calculate_signal({symbol: df})
        else:
            signals = await self.calculate_signal({df.index.name: df}) if df.index.name else await self.calculate_signal({"": df})
        
        return signals[0] if signals else None
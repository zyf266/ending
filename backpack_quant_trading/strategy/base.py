from abc import ABC, abstractmethod   #ABC抽象基类，用于定义接口规范         abstractmethod：抽象方法装饰器，子类必须实现
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field    #dataclass:数据类装饰器，自动生成__init__,__repr__等方法
#field  数据类字典配置器，用于设置默认值，默认工厂函数
from datetime import datetime
import pandas as pd
import numpy as np

from ..core.api_client import BackpackAPIClient, ExchangeClient
from ..core.risk_manager import RiskManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Position:
    """仓位信息"""
    symbol:str  #交易对符号   如：BTC_USDC
    side:str  #'long' or 'short'  多头或空头
    quantity:float  #持仓数量
    entry_price:float #入场价格
    current_price:float #当前市场价格
    pnl:float=0.0 #盈亏金额
    pnl_percent:float=0.0  #盈亏百分比
    stop_loss:Optional[float]=None #止损价格
    take_profit:Optional[float]=None  #止盈价格
    timestamp:datetime=field(default_factory=datetime.now) #创建时间戳
#default_factory  工厂函数，每次创建新实例时调用datetime.now()  而不是固定时间
@dataclass
class Signal:
    """交易信息"""
    symbol:str
    action:str #'buy','sell','hold'
    quantity:float
    price:Optional[float]=None   #目标价格，如果为None则使用市价单
    stop_loss:Optional[float]=None  #止损价格
    take_profit:Optional[float]=None #止盈价格
    confidence:float=1.0  #信号置信度
    reason:str=""  #信号产生原因
class BaseStrategy(ABC):
    """策略基类
    抽象基类  所有具体交易策略都应继承此类并实现抽象方法
    采用模板方法设计模式
    """
    def __init__(self,name:str,symbols:List[str],api_client:BackpackAPIClient,risk_manager:RiskManager):
        """初始化策略
        args: name  策略名称  如RS_Strategy
        symbol：监控的交易对列表
        api_client:API客户端实例  用于执行操作
        risk_manager:风险管理器实例，用于风险控制


        """
        self.name=name
        self.symbols=symbols
        self.api_client: Optional[ExchangeClient] = api_client
        self.risk_manager=risk_manager
        #状态管理
        #当前持仓字典
        self.positions:Dict[str, Position]={}
        #生成的交易信号列表
        self.signals:List[Signal]=[]
        #性能指标字典，用于记录策略表现
        self.performance_metrics={}

        #策略参数
        #参数参数：用于存储策略参数如RIS周期，移动平均周期等
        self.params={}

    @abstractmethod
    async def calculate_signal(self,data:Dict[str,pd.DataFrame])->List[Signal]:
        """计算交易信号"""
        """
               抽象方法：计算交易信号

               Args:
                   data: 市场数据字典
                         key: symbol (交易对)
                         value: pd.DataFrame (包含OHLCV等数据)

               Returns:
                   List[Signal]: 交易信号列表

               子类必须实现此方法，定义具体的交易逻辑
               例如：
               - 基于技术指标（RSI、MACD、均线等）
               - 基于机器学习模型
               - 基于市场情绪分析
               """
    pass

    @abstractmethod
    def should_exit_position(self,position:Position,current_data:pd.Series)->bool:
        """判断是否需要平仓"""
        """
                抽象方法：判断是否需要平仓

                Args:
                    position: 当前持仓信息
                    current_data: 当前市场数据（价格、指标等）

                Returns:
                    bool: True表示需要平仓，False表示继续持有

                子类必须实现此方法，定义平仓逻辑
                例如：
                - 价格触及止损/止盈
                - 技术指标发出反转信号
                - 持有时间超过限制
                """
        pass

    def update_position(self,symbol:str,current_price:float):
        """更新仓位信息
         定期调用此方法更新持仓状态，计算实时盈亏

        Args:
            symbol: 交易对符号
            current_price: 当前市场价格
        """
        if symbol in self.positions:
            position=self.positions[symbol]
            position.current_price=current_price
            position.pnl=self._calculate_pnl(position)
            position.pnl_percent= self._calculate_pnl_percent(position)

            #检查止损止盈
            if self.should_exit_position(position,pd.Series({'price':current_price})):
                self.generate_exit_signal(symbol)

    def _calculate_pnl(self, position: Position) -> float:
        """计算持仓盈亏"""
        if position.side == 'long':
            return (position.current_price - position.entry_price) * position.quantity
        elif position.side == 'short':
            return (position.entry_price - position.current_price) * position.quantity
        else:
            logger.error(f"未知的持仓方向: {position.side}")
            return 0.0

    def _calculate_pnl_percent(self, position: Position) -> float:
        """计算持仓盈亏百分比"""
        entry_value = position.entry_price * position.quantity

        # 避免除零错误
        if entry_value == 0:
            logger.warning(f"入场价值为零: {position.symbol}")
            return 0.0

        pnl = self._calculate_pnl(position)
        return (pnl / entry_value) * 100
    def generate_exit_signal(self,symbol:str,reason:str="strategy_exit"):
        """生成平仓信息
          Args:
            symbol: 交易对符号
            reason: 平仓原因，默认为"strategy_exit"
        """
        if symbol in self.positions:
            position=self.positions[symbol]
            action='sell' if position.side=='long' else 'buy'
            signal=Signal(
                symbol=symbol,
                action=action,
                quantity=position.quantity,  #平掉全部持仓
                price=position.current_price, #使用当前价格
                reason=reason #记录平仓原因
            )
            self.signals.append(signal)
    def set_parameters(self,**kwargs):
        """设置策略参数"""
        self.params.update(kwargs)
        logger.info(f"策略{self.name}参数更新:{kwargs}")

    def get_performance_report(self)->Dict:
        """获取性能报告"""
        return {
            "strategy_name":self.name,
            "total_positions":len(self.positions), #总持仓数（含已平仓）
            "open_positions":sum(1 for p in self.positions.values() if p.quantity>0),  #当前开仓数
            "total_pnl":sum(p.pnl for p in self.positions.values()), #总盈亏
            "win_rate":self._calculate_win_rate(), #胜率
            "sharpe_ratio":self._calculate_sharpe_ratio(), #夏普比率
            "max_drawdown":self._calculate_max_drawdown(), #最大回撤
        }

    def _calculate_win_rate(self)->float:
        """计算胜率"""
        return 0.0

    def _calculate_sharpe_ratio(self)->float:
        """计算夏普比例
         夏普比率 = (策略收益率 - 无风险利率) / 策略收益率标准差
        衡量风险调整后的收益
        """
        return 0.0

    def _calculate_max_drawdown(self) -> float:  # 修正拼写
        """计算最大回撤"""
        # 这里需要实现具体逻辑
        # 通常需要维护一个净值曲线
        if hasattr(self, 'equity_curve') and len(self.equity_curve) > 0:
            # 计算峰值和谷值
            peak = np.maximum.accumulate(self.equity_curve)
            drawdown = (self.equity_curve - peak) / peak * 100
            return np.min(drawdown)  # 最大回撤是负数
        return 0.0





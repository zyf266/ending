from sqlalchemy import create_engine, Column, Integer, String, DateTime, Numeric, Boolean, Text, Enum, Float, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from datetime import datetime
from typing import Optional
import enum
from decimal import Decimal as PyDecimal

from backpack_quant_trading.config.settings import config

Base = declarative_base()


class OrderSide(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(enum.Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(enum.Enum):
    LONG = "long"
    SHORT = "short"


class RiskSeverity(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MarketData(Base):
    """市场数据表"""
    __tablename__ = 'market_data'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    source = Column(String(50), default='backpack', index=True)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Numeric(20, 8), nullable=False)
    high = Column(Numeric(20, 8), nullable=False)
    low = Column(Numeric(20, 8), nullable=False)
    close = Column(Numeric(20, 8), nullable=False)
    volume = Column(Numeric(20, 8), nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_symbol_timestamp_source', 'symbol', 'timestamp', 'source'),
    )


class Order(Base):
    """订单表"""
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, nullable=False)
    client_order_id = Column(String(100))
    source = Column(String(50), default='backpack', index=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    order_type = Column(String(10), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8))
    status = Column(String(20), nullable=False)
    filled_quantity = Column(Numeric(20, 8), default=PyDecimal('0'))
    filled_price = Column(Numeric(20, 8))
    commission = Column(Numeric(20, 8), default=PyDecimal('0'))
    commission_asset = Column(String(10))
    tx_hash = Column(String(100), nullable=True)  # 区块链交易哈希
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_symbol_status_source', 'symbol', 'status', 'source'),
        Index('idx_created_at_source', 'created_at', 'source'),
    )


class Position(Base):
    """仓位表"""
    __tablename__ = 'positions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), default='backpack', index=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    entry_price = Column(Numeric(20, 8), nullable=False)
    current_price = Column(Numeric(20, 8))
    unrealized_pnl = Column(Numeric(20, 8))
    unrealized_pnl_percent = Column(Numeric(10, 4))
    stop_loss = Column(Numeric(20, 8))
    take_profit = Column(Numeric(20, 8))
    
    # Ostium 扩展字段
    trade_index = Column(Integer, nullable=True)  # Ostium 仓位索引
    pair_id = Column(Integer, nullable=True)      # Ostium 交易对 ID
    collateral = Column(Numeric(20, 8), nullable=True) # 保证金

    opened_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime)

    __table_args__ = (
        Index('idx_symbol_status_source', 'symbol', 'closed_at', 'source'),
        Index('idx_opened_at_source', 'opened_at', 'source'),
    )


class Trade(Base):
    """成交记录表"""
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(100), unique=True, nullable=False)
    order_id = Column(String(100), nullable=False)
    source = Column(String(50), default='backpack', index=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    commission = Column(Numeric(20, 8), nullable=False)
    commission_asset = Column(String(10))
    is_maker = Column(Boolean, default=False)
    
    # Ostium / 回测 扩展字段
    close_price = Column(Numeric(20, 8), nullable=True)
    pnl_percent = Column(Numeric(20, 8), nullable=True)
    pnl_amount = Column(Numeric(20, 8), nullable=True)
    reason = Column(Text, nullable=True)
    
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_symbol_created_source', 'symbol', 'created_at', 'source'),
        Index('idx_order_id_source', 'order_id', 'source'),
    )


class AccountBalance(Base):
    """账户余额表"""
    __tablename__ = 'account_balance'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), default='backpack', index=True)
    asset = Column(String(10), nullable=False)
    total = Column(Numeric(20, 8), nullable=False)
    available = Column(Numeric(20, 8), nullable=False)
    locked = Column(Numeric(20, 8), nullable=False)
    timestamp = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_asset_timestamp_source', 'asset', 'timestamp', 'source'),
    )


class StrategyPerformance(Base):
    """策略性能表"""
    __tablename__ = 'strategy_performance'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), default='backpack', index=True)
    strategy_name = Column(String(50), nullable=False)
    total_return = Column(Numeric(10, 4), nullable=False)
    annualized_return = Column(Numeric(10, 4), nullable=False)
    sharpe_ratio = Column(Numeric(10, 4), nullable=False)
    max_drawdown = Column(Numeric(10, 4), nullable=False)
    win_rate = Column(Numeric(10, 4), nullable=False)
    profit_factor = Column(Numeric(10, 4), nullable=False)
    total_trades = Column(Integer, nullable=False)
    winning_trades = Column(Integer, nullable=False)
    losing_trades = Column(Integer, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class RiskEvent(Base):
    """风险事件表"""
    __tablename__ = 'risk_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), default='backpack', index=True)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(10), nullable=False)
    description = Column(Text, nullable=False)
    affected_symbols = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_event_type_source', 'event_type', 'source'),
        Index('idx_created_at_source', 'created_at', 'source'),
    )


class PortfolioHistory(Base):
    """组合历史净值表"""
    __tablename__ = 'portfolio_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), default='backpack', index=True)
    timestamp = Column(DateTime, nullable=False)
    portfolio_value = Column(Numeric(20, 8), nullable=False)
    cash_balance = Column(Numeric(20, 8), nullable=False)
    position_value = Column(Numeric(20, 8), nullable=False)
    daily_pnl = Column(Numeric(20, 8))
    daily_return = Column(Numeric(10, 4))

    __table_args__ = (
        Index('idx_portfolio_timestamp_source', 'timestamp', 'source'),
    )


class User(Base):
    """用户表：用于登录与权限控制"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default='user')  # 'user' 或 'superuser'
    created_at = Column(DateTime, default=datetime.now)


class UserInstance(Base):
    """用户实例归属表：实盘/网格/币种监视按用户隔离，刷新后恢复。
    注意：config_json 仅存 platform/strategy/symbol 等元数据，绝不存储 API Key、私钥等敏感信息。"""
    __tablename__ = 'user_instances'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    instance_type = Column(String(30), nullable=False)  # 'live' | 'grid' | 'currency_monitor'
    instance_id = Column(String(100), nullable=False, index=True)
    config_json = Column(Text, nullable=True)  # 仅存 platform/strategy/symbol 等，不含私钥
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (Index('idx_user_instance', 'user_id', 'instance_type', 'instance_id'),)


class StrategyConfig(Base):
    """策略元数据与默认配置"""
    __tablename__ = 'strategy_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    module = Column(String(255), nullable=False)
    class_name = Column(String(255), nullable=False)
    default_params = Column(Text, nullable=True)  # JSON 字符串保存默认参数
    enabled = Column(Boolean, default=True)



class DatabaseManager:
    """数据库管理器"""

    def __init__(self):
        self.engine = create_engine(
            config.database_url,
            pool_size=config.database.POOL_SIZE,
            max_overflow=config.database.MAX_OVERFLOW,
            pool_pre_ping=True,
            echo=False
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)

    def get_session(self):
        """获取数据库会话"""
        return self.Session()

    def create_tables(self):
        """创建所有表"""
        Base.metadata.create_all(self.engine)

    def drop_tables(self):
        """删除所有表"""
        Base.metadata.drop_all(self.engine)

    def save_market_data(self, symbol: str, data: list, source: str = 'backpack'):
        """保存市场数据"""
        session = self.get_session()
        try:
            for row in data:
                market_data = MarketData(
                    symbol=symbol,
                    source=source,
                    timestamp=datetime.fromtimestamp(row['timestamp']),
                    open=PyDecimal(str(row['open'])),
                    high=PyDecimal(str(row['high'])),
                    low=PyDecimal(str(row['low'])),
                    close=PyDecimal(str(row['close'])),
                    volume=PyDecimal(str(row['volume']))
                )
                session.merge(market_data)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_order(self, order_data: dict, source: str = 'backpack'):
        """保存订单"""
        session = self.get_session()
        try:
            # 【修复】截断过长的 order_id 和 tx_hash
            order_id = str(order_data['order_id'])[:250]
            tx_hash = str(order_data.get('tx_hash'))[:250] if order_data.get('tx_hash') else None
            
            order = Order(
                order_id=order_id,
                client_order_id=order_data.get('client_id'),
                source=source,
                symbol=order_data['symbol'],
                side=order_data['side'],
                order_type=order_data['type'],
                quantity=PyDecimal(str(order_data['quantity'])),
                price=PyDecimal(str(order_data.get('price'))) if order_data.get('price') is not None else None,
                status=order_data['status'],
                filled_quantity=PyDecimal(str(order_data.get('filledQuantity', 0))),
                filled_price=PyDecimal(str(order_data.get('avgPrice', 0))) if order_data.get('avgPrice') is not None else None,
                commission=PyDecimal(str(order_data.get('commission', 0))),
                commission_asset=order_data.get('commissionAsset'),
                tx_hash=tx_hash,
                created_at=datetime.fromtimestamp(order_data['createdTime'] / 1000) if isinstance(order_data.get('createdTime'), (int, float)) else order_data.get('createdTime', datetime.now()),
                updated_at=datetime.now()
            )
            session.merge(order)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_trade(self, trade_data: dict, source: str = 'backpack'):
        """保存成交"""
        session = self.get_session()
        try:
            # 【修复】截断过长的 trade_id 和 order_id，防止数据库错误
            trade_id = str(trade_data['tradeId'])[:250]
            order_id = str(trade_data['orderId'])[:250]
            
            # 【关键修复】检查是否已存在相同的 trade_id，避免重复插入
            existing_trade = session.query(Trade).filter_by(trade_id=trade_id).first()
            if existing_trade:
                # trade_id 已存在，静默跳过
                return
            
            trade = Trade(
                trade_id=trade_id,
                order_id=order_id,
                source=source,
                symbol=trade_data['symbol'],
                side=trade_data['side'],
                quantity=PyDecimal(str(trade_data['quantity'])),
                price=PyDecimal(str(trade_data['price'])),
                commission=PyDecimal(str(trade_data.get('commission', 0))),
                commission_asset=trade_data.get('commissionAsset'),
                is_maker=trade_data.get('isMaker', False),
                close_price=PyDecimal(str(trade_data.get('close_price'))) if trade_data.get('close_price') is not None else None,
                pnl_percent=PyDecimal(str(trade_data.get('pnl_percent'))) if trade_data.get('pnl_percent') is not None else None,
                pnl_amount=PyDecimal(str(trade_data.get('pnl_amount'))) if trade_data.get('pnl_amount') is not None else None,
                reason=trade_data.get('reason'),
                created_at=datetime.fromtimestamp(trade_data['timestamp'] / 1000) if isinstance(trade_data.get('timestamp'), (int, float)) else trade_data.get('timestamp', datetime.now())
            )
            session.add(trade)  # 【修复】使用 add 而不是 merge
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_position(self, position_data: dict, source: str = 'backpack'):
        """保存持仓"""
        session = self.get_session()
        try:
            # 查找是否已存在该持仓记录
            existing_position = session.query(Position).filter_by(
                symbol=position_data['symbol'],
                side=position_data['side'],
                source=source
            ).filter(Position.closed_at.is_(None)).first()
            
            if existing_position:
                # 更新已存在的持仓
                existing_position.quantity = PyDecimal(str(position_data['quantity']))
                existing_position.entry_price = PyDecimal(str(position_data['entry_price']))
                existing_position.current_price = PyDecimal(str(position_data['current_price'])) if position_data.get('current_price') is not None else None
                existing_position.unrealized_pnl = PyDecimal(str(position_data['unrealized_pnl'])) if position_data.get('unrealized_pnl') is not None else None
                existing_position.unrealized_pnl_percent = PyDecimal(str(position_data['unrealized_pnl_percent'])) if position_data.get('unrealized_pnl_percent') is not None else None
                existing_position.stop_loss = PyDecimal(str(position_data['stop_loss'])) if position_data.get('stop_loss') is not None else None
                existing_position.take_profit = PyDecimal(str(position_data['take_profit'])) if position_data.get('take_profit') is not None else None
                
                # Ostium 扩展
                existing_position.trade_index = position_data.get('index') or position_data.get('trade_index')
                existing_position.pair_id = position_data.get('pair_id')
                existing_position.collateral = PyDecimal(str(position_data.get('collateral'))) if position_data.get('collateral') else existing_position.collateral
                
                existing_position.updated_at = datetime.now()
                existing_position.closed_at = position_data.get('closed_at')
            else:
                # 创建新的持仓记录
                opened_at = position_data.get('opened_at')
                if isinstance(opened_at, (int, float)):
                    # 处理毫秒时间戳
                    if opened_at > 1e12:
                        opened_at /= 1000
                    opened_at = datetime.fromtimestamp(opened_at)
                elif opened_at is None:
                    opened_at = datetime.now()

                position = Position(
                    symbol=position_data['symbol'],
                    source=source,
                    side=position_data['side'],
                    quantity=PyDecimal(str(position_data['quantity'])),
                    entry_price=PyDecimal(str(position_data['entry_price'])),
                    current_price=PyDecimal(str(position_data['current_price'])) if position_data.get('current_price') is not None else None,
                    unrealized_pnl=PyDecimal(str(position_data['unrealized_pnl'])) if position_data.get('unrealized_pnl') is not None else None,
                    unrealized_pnl_percent=PyDecimal(str(position_data['unrealized_pnl_percent'])) if position_data.get('unrealized_pnl_percent') is not None else None,
                    stop_loss=PyDecimal(str(position_data['stop_loss'])) if position_data.get('stop_loss') is not None else None,
                    take_profit=PyDecimal(str(position_data['take_profit'])) if position_data.get('take_profit') is not None else None,
                    
                    # Ostium 扩展
                    trade_index=position_data.get('index') or position_data.get('trade_index'),
                    pair_id=position_data.get('pair_id'),
                    collateral=PyDecimal(str(position_data.get('collateral'))) if position_data.get('collateral') else None,
                    
                    opened_at=opened_at,
                    closed_at=position_data.get('closed_at')
                )
                session.add(position)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_risk_event(self, event_type: str, severity: str, description: str, affected_symbols: str = None, source: str = 'backpack'):
        """保存风险事件"""
        session = self.get_session()
        try:
            event = RiskEvent(
                event_type=event_type,
                severity=severity,
                description=description,
                affected_symbols=affected_symbols,
                source=source
            )
            session.add(event)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_portfolio_snapshot(self, portfolio_value: float, cash_balance: float,
                                 position_value: float, daily_pnl: float = None,
                                 daily_return: float = None, source: str = 'backpack'):
        """保存组合快照"""
        session = self.get_session()
        try:
            snapshot = PortfolioHistory(
                timestamp=datetime.now(),
                portfolio_value=PyDecimal(str(portfolio_value)),
                cash_balance=PyDecimal(str(cash_balance)),
                position_value=PyDecimal(str(position_value)),
                daily_pnl=PyDecimal(str(daily_pnl)) if daily_pnl else None,
                daily_return=PyDecimal(str(daily_return)) if daily_return else None,
                source=source
            )
            session.add(snapshot)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    # === 用户与策略配置相关方法 ===

    def get_user_by_username(self, username: str):
        """根据用户名获取用户"""
        session = self.get_session()
        try:
            user = session.query(User).filter_by(username=username).first()
            if user:
                session.refresh(user)
                session.expunge(user)
            return user
        finally:
            session.close()

    def get_user_by_id(self, user_id: int):
        """根据 ID 获取用户"""
        session = self.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user:
                session.refresh(user)
                session.expunge(user)
            return user
        finally:
            session.close()

    def create_user(self, username: str, password_hash: str, role: str = 'user'):
        """创建新用户"""
        session = self.get_session()
        try:
            user = User(username=username, password_hash=password_hash, role=role)
            session.add(user)
            session.commit()
            session.refresh(user)
            session.expunge(user)
            return user
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_user_instance(self, user_id: int, instance_type: str, instance_id: str, config_json: Optional[str] = None):
        """保存用户实例归属（实盘/网格/币种监视）"""
        session = self.get_session()
        try:
            existing = session.query(UserInstance).filter_by(
                user_id=user_id, instance_type=instance_type, instance_id=instance_id
            ).first()
            if not existing:
                ui = UserInstance(user_id=user_id, instance_type=instance_type, instance_id=instance_id, config_json=config_json)
                session.add(ui)
            else:
                existing.config_json = config_json
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_user_instance_ids(self, user_id: int, instance_type: str) -> list:
        """获取某用户某类型的所有 instance_id"""
        session = self.get_session()
        try:
            rows = session.query(UserInstance).filter_by(user_id=user_id, instance_type=instance_type).all()
            return [r.instance_id for r in rows]
        finally:
            session.close()

    def get_user_instance_configs(self, user_id: int, instance_type: str) -> list:
        """获取某用户某类型的所有实例配置 (instance_id, config_json)"""
        session = self.get_session()
        try:
            rows = session.query(UserInstance).filter_by(user_id=user_id, instance_type=instance_type).all()
            return [(r.instance_id, r.config_json) for r in rows]
        finally:
            session.close()

    def get_first_user_id(self) -> Optional[int]:
        """获取系统中第一个用户的 id，用于全局共享配置（如币种监视）"""
        session = self.get_session()
        try:
            user = session.query(User).order_by(User.id).first()
            return user.id if user else None
        finally:
            session.close()

    def get_currency_monitor_config(self) -> Optional[tuple]:
        """获取币种监视的全局配置（不按用户隔离，兼容旧逻辑）"""
        session = self.get_session()
        try:
            row = session.query(UserInstance).filter_by(
                instance_type='currency_monitor', instance_id='singleton'
            ).first()
            return (row.instance_id, row.config_json) if row and row.config_json else None
        finally:
            session.close()

    def get_currency_monitor_config_for_user(self, user_id: int) -> Optional[tuple]:
        """获取指定用户的币种监视配置"""
        session = self.get_session()
        try:
            row = session.query(UserInstance).filter_by(
                user_id=user_id, instance_type='currency_monitor', instance_id='singleton'
            ).first()
            return (row.instance_id, row.config_json) if row and row.config_json else None
        finally:
            session.close()

    def save_currency_monitor_config(self, config_json: str):
        """保存币种监视的全局配置（使用第一个用户 id 作为存储键）"""
        self.delete_currency_monitor_config()
        uid = self.get_first_user_id()
        if uid is not None:
            self.save_user_instance(uid, 'currency_monitor', 'singleton', config_json)

    def save_currency_monitor_config_for_user(self, user_id: int, config_json: str):
        """保存指定用户的币种监视配置"""
        self.delete_currency_monitor_config_for_user(user_id)
        self.save_user_instance(user_id, 'currency_monitor', 'singleton', config_json)

    def delete_currency_monitor_config(self):
        """删除币种监视的全局配置"""
        session = self.get_session()
        try:
            session.query(UserInstance).filter_by(
                instance_type='currency_monitor', instance_id='singleton'
            ).delete()
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def delete_currency_monitor_config_for_user(self, user_id: int):
        """删除指定用户的币种监视配置"""
        self.delete_user_instance(user_id, 'currency_monitor', 'singleton')

    def delete_user_instance(self, user_id: int, instance_type: str, instance_id: str):
        """删除用户实例归属（停止时调用）"""
        session = self.get_session()
        try:
            session.query(UserInstance).filter_by(
                user_id=user_id, instance_type=instance_type, instance_id=instance_id
            ).delete()
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def list_strategy_configs(self):
        """获取所有策略配置"""
        session = self.get_session()
        try:
            return session.query(StrategyConfig).all()
        finally:
            session.close()

    def save_strategy_config(self, name: str, module: str, class_name: str, default_params: Optional[str] = None):
        """保存或更新策略配置"""
        session = self.get_session()
        try:
            cfg = session.query(StrategyConfig).filter_by(name=name).first()
            if cfg is None:
                cfg = StrategyConfig(
                    name=name,
                    module=module,
                    class_name=class_name,
                    default_params=default_params,
                    enabled=True,
                )
                session.add(cfg)
            else:
                cfg.module = module
                cfg.class_name = class_name
                cfg.default_params = default_params
            session.commit()
            return cfg
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()


db_manager = DatabaseManager()

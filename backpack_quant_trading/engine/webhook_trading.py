import asyncio
import logging
import random
import pytz
import os
from datetime import datetime
from typing import Optional, Dict, List, Any
from pydantic import BaseModel
import hmac
import hashlib
import base64
import urllib.parse
import aiohttp
import time

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.ostium_client import OstiumAPIClient
from backpack_quant_trading.database.models import db_manager, Position, Trade

logger = logging.getLogger(__name__)

class TradingViewSignal(BaseModel):
    """信号模型"""
    signal: str  # 'buy' 或 'sell' 或 'close'
    symbol: str  # 交易对符号，如 'NDX'
    instance_id: Optional[str] = None  # 实例 ID，用于多实例路由
    strategy_name: Optional[str] = None  # 策略名，用于广播筛选
    price: Optional[float] = None
    timestamp: Optional[str] = None
    indicator: Optional[str] = None
    action: Optional[str] = None
    
    # TradingView 自定义字段
    exchange: Optional[str] = None
    ticker: Optional[str] = None
    先前仓位: Optional[str] = 'flat'
    先前仓位大小: Optional[str] = '0'


class WebhookTradingEngine:
    """Webhook 交易引擎：处理 TradingView 信号并在 Ostium 执行交易"""
    
    def __init__(self, stop_loss_ratio: Optional[float] = None, take_profit_ratio: Optional[float] = None):
        self.client = OstiumAPIClient()
        self.source = 'ostium'
        self.symbol = config.ostium.SYMBOL
        self.leverage = config.ostium.LEVERAGE
            
        # 风险控制参数（优先使用用户设置，否则使用全局配置）
        self.stop_loss_percent = stop_loss_ratio if stop_loss_ratio is not None else config.trading.STOP_LOSS_PERCENT
        self.take_profit_percent = take_profit_ratio if take_profit_ratio is not None else config.trading.TAKE_PROFIT_PERCENT
            
        # 仓位配置
        self.position_ratio = config.trading.MAX_POSITION_SIZE # 默认比例
        self.high_qty_min = config.webhook.HIGH_QTY_MIN
        self.high_qty_max = config.webhook.HIGH_QTY_MAX
            
        logger.info(f"Webhook 交易引擎初始化完成。止损: {self.stop_loss_percent*100}%, 止盈: {self.take_profit_percent*100}%")
            
        # 状态变量
        self.current_position = None  # 'LONG', 'SHORT', or None
        self.last_signal = None
        self.last_intent = None
        self.skip_next_opposite = False
        self.is_stopped = False
        self.last_reset_time = None
        # 注意：syncio.Lock 将在运行时创建，以确保在正确的 event loop 中
        self.lock = None
            
        # 时区与休市
        self.beijing_tz = pytz.timezone('Asia/Shanghai')
        
        # 从环境变量读取休市时间 (小时列表，如 "3,4,5,6,7,11,12,19,20")
        env_forbidden = os.getenv("OSTIUM_FORBIDDEN_HOURS")
        if env_forbidden:
            try:
                self.forbidden_hours = [int(h.strip()) for h in env_forbidden.split(',') if h.strip()]
                logger.info(f"使用自定义休市时间: {self.forbidden_hours}")
            except Exception as e:
                logger.error(f"解析 OSTIUM_FORBIDDEN_HOURS 失败: {e}")
                self.forbidden_hours = [3, 4, 5, 6, 7, 11, 12, 19, 20] # 默认
        else:
            self.forbidden_hours = [3, 4, 5, 6, 7, 11, 12, 19, 20] # 默认
    
    async def initialize(self):
        """异步初始化：同步持仓状态"""
        # 在运行时创建锁，确保在正确的 event loop 中
        if self.lock is None:
            self.lock = asyncio.Lock()
        await self.sync_position()
        logger.info("Webhook 交易引擎异步初始化完成")

    async def sync_position(self):
        """从 MySQL 数据库和 Ostium 同步持仓状态"""
        try:
            # 1. 先查本地数据库
            session = db_manager.get_session()
            pos = session.query(Position).filter_by(
                symbol=self.symbol,
                source=self.source,
                closed_at=None
            ).first()
            
            if pos:
                self.current_position = 'LONG' if pos.side == 'long' else 'SHORT'
                logger.info(f"从数据库恢复持仓: {self.current_position}, 数量: {pos.quantity}")
            else:
                # 2. 如果数据库没有，尝试从链上获取
                chain_positions = await self.client.get_positions(self.symbol)
                if chain_positions:
                    p = chain_positions[0]
                    self.current_position = 'LONG' if p['direction'] else 'SHORT'
                    # 保存到数据库
                    db_manager.save_position({
                        'symbol': self.symbol,
                        'side': 'long' if p['direction'] else 'short',
                        'quantity': p['collateral'],
                        'entry_price': await self.client.get_price(self.symbol), # 估计值
                        'collateral': p['collateral'],
                        'index': p['index'],
                        'pair_id': p['pair_id'],
                        'opened_at': p['opened_at']
                    }, source=self.source)
                    logger.info(f"从链上同步持仓: {self.current_position}")
                else:
                    self.current_position = None
            session.close()
        except Exception as e:
            logger.error(f"同步持仓失败: {e}")

    def is_trading_time(self) -> bool:
        """检查当前是否允许交易（北京时间）"""
        beijing_time = datetime.now(self.beijing_tz)
        current_hour = beijing_time.hour
        
        # 检查当前小时是否在休市列表中
        if current_hour in self.forbidden_hours:
            return False
            
        return True

    def get_beijing_time_str(self):
        return datetime.now(self.beijing_tz).strftime('%Y-%m-%d %H:%M:%S')

    async def _calculate_order_amount(self) -> float:
        """根据保证金数量(或范围)计算下单总金额 (USDC)"""
        try:
            # 1. 获取保证金设置 - 优先使用实例级别的环境变量
            instance_id = getattr(self, 'instance_id', None)
            if instance_id:
                env_margin = os.getenv(f"WEBHOOK_MARGIN_AMOUNT_{instance_id}")
            else:
                env_margin = os.getenv("WEBHOOK_MARGIN_AMOUNT")
            
            if not env_margin:
                # 优先使用设定的保证金范围 (您之前的逻辑)
                margin = random.uniform(self.high_qty_min, self.high_qty_max)
                logger.info(f"未设定保证金，使用配置默认范围: {self.high_qty_min}-{self.high_qty_max}")
            elif "-" in str(env_margin):
                # 处理范围格式 "5-6"
                try:
                    parts = str(env_margin).split("-")
                    m_min = float(parts[0])
                    m_max = float(parts[1])
                    margin = random.uniform(m_min, m_max)
                    logger.info(f"使用设定保证金范围: {m_min}-{m_max}")
                except Exception as e:
                    logger.error(f"解析保证金范围失败: {e}")
                    margin = self.high_qty_min
            else:
                # 单个数字
                margin = float(env_margin)
            
            # 2. 直接返回保证金金额（SDK 内部会根据杠杆计算总头寸）
            logger.info(f"📊 仓位计算: 保证金={margin:.2f} USDC, 杠杆={self.leverage}")
            
            return max(round(margin, 4), 0.1)
        except Exception as e:
            logger.error(f"计算下单金额异常: {e}")
            return 5.0  # 报错兜底：5u 保证金

    async def send_dingtalk_notification(self, message: str):
        """发送钉钉通知"""
        token = config.webhook.DINGTALK_TOKEN
        secret = config.webhook.DINGTALK_SECRET
        if not token:
            logger.warning("钉钉通知跳过：未配置 DINGTALK_TOKEN")
            return
        
        try:
            url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
            if secret:
                timestamp = str(round(datetime.now().timestamp() * 1000))
                string_to_sign = '{}\n{}'.format(timestamp, secret)
                hmac_code = hmac.new(secret.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                url += f"&timestamp={timestamp}&sign={sign}"
            
            data = {
                "msgtype": "text",
                "text": {"content": f"【Ostium Webhook】\n时间: {self.get_beijing_time_str()}\n{message}"}
            }
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=data, timeout=5)
        except Exception as e:
            logger.error(f"钉钉通知发送失败: {e}")

    async def execute_signal(self, signal: TradingViewSignal, raw_payload: Optional[Dict[str, Any]] = None):
        """处理信号入口。raw_payload 为 Webhook 原始 body，Ostium 已从 signal 解析意图，此参数仅保持与 Hyperliquid 引擎签名一致。"""
        # 确保锁已创建
        if self.lock is None:
            self.lock = asyncio.Lock()
        
        async with self.lock:
            if self.is_stopped:
                logger.warning("熔断中，忽略信号")
                return

            signal_type = signal.signal.lower()
            logger.info(f"收到信号: {signal_type} ({signal.symbol})")
            
            # 动态更新交易对
            if signal.symbol:
                self.symbol = signal.symbol
            
            # 【关键修复】每次执行信号前，强制重新同步持仓状态
            logger.info("🔄 执行信号前重新同步链上持仓...")
            await self.sync_position()
            logger.info(f"✅ 当前持仓状态: {self.current_position}")
            
            # 解析意图
            intent = "unknown"
            prev_pos = str(signal.先前仓位).strip().lower()
            prev_size = str(signal.先前仓位大小).strip()
            
            if prev_pos == 'flat' and (prev_size == '0' or prev_size == '0.0'):
                intent = "open"
            elif prev_pos in ['long', 'short'] and prev_size != '0' and prev_size != '0.0':
                intent = "close"
            
            logger.info(f"解析意图: {intent} (先前仓位: {prev_pos}, 先前仓位大小: {prev_size})")

            # === 信号丢失自愈逻辑 ===
            # 1. 检测信号丢失：确有持仓 + 连续相同开仓信号
            if self.current_position is not None and signal_type == self.last_signal and intent == "open" and self.last_intent == "open":
                logger.warning(f"检测到信号丢失(已有{self.current_position}且收到重复{signal_type})，尝试强平自愈")
                await self._close_position("信号丢失自愈强平")
                self.skip_next_opposite = True
                await self.send_dingtalk_notification("检测到信号丢失：已尝试强平并进入同步模式。")
                self.last_signal = signal_type
                self.last_intent = intent
                return

            # 2. 自愈模式：强平后跳过下一个信号
            if self.skip_next_opposite:
                logger.info(f"自愈中：跳过信号 {signal_type}，等待同步")
                self.skip_next_opposite = False
                self.last_signal = signal_type
                self.last_intent = intent
                return
            # ============================

            # 暂时不更新状态，等真正执行逻辑前再更新
            # self.last_signal = signal_type
            # self.last_intent = intent

            # 计算下单金额
            amount = await self._calculate_order_amount()
            
            if intent == "open":
                if signal_type in ['buy', 'long']:
                    # 执行前记录状态
                    self.last_signal = signal_type
                    self.last_intent = intent
                    await self._handle_open(amount, 'BUY')
                elif signal_type in ['sell', 'short']:
                    self.last_signal = signal_type
                    self.last_intent = intent
                    await self._handle_open(amount, 'SELL')
            elif intent == "close":
                self.last_signal = signal_type
                self.last_intent = intent
                await self._handle_close()
            else:
                # 兼容模式
                self.last_signal = signal_type
                self.last_intent = intent
                if signal_type in ['buy', 'long']:
                    await self._handle_open(amount, 'BUY')
                elif signal_type in ['sell', 'short']:
                    await self._handle_open(amount, 'SELL')
                elif signal_type == 'close':
                    await self._handle_close()

    async def _handle_open(self, amount: float, side: str):
        """处理开仓逻辑"""
        if not self.is_trading_time():
            logger.warning("休市时间，不予开仓")
            return

        target_side = 'LONG' if side == 'BUY' else 'SHORT'
        
        # 互平逻辑
        if self.current_position and self.current_position != target_side:
            logger.info(f"反向信号，先平仓 {self.current_position}")
            await self._close_position(f"反向信号 {side} 触发平仓")
            return

        if self.current_position == target_side:
            logger.info(f"已有 {target_side} 仓位，跳过")
            return

        # 执行下单
        logger.info(f"执行开仓: {target_side}, 交易对: {self.symbol}, 金额: {amount}")
        res = await self.client.place_order(
            symbol=self.symbol,
            side=side,
            quantity=amount,
            order_type='MARKET',
            leverage=self.leverage
        )
        
        if res.get('status') == 'FILLED':
            self.current_position = target_side
            
            # 【关键修复】开仓后从交易收据中直接解析 trade_index
            actual_trade_index = None
            actual_pair_id = None
                        
            try:
                logger.info("🔍 开仓成功，从交易收据事件日志中解析 trade_index...")
                            
                # 方法1：优先从 SDK 返回的 receipt 中解析 TradeOpened 事件
                if 'receipt' in res or 'tx_hash' in res:
                    # 尝试从 Ostium client 的方法获取
                    # 如果 place_order 返回了 trade_index，直接使用
                    if res.get('trade_index') is not None and res.get('trade_index') != res.get('orderId'):
                        # trade_index 不等于 order_id 说明是从事件日志解析的
                        actual_trade_index = res.get('trade_index')
                        actual_pair_id = res.get('pair_id')
                        logger.info(f"✅ 从 SDK 返回值获取 trade_index: {actual_trade_index}, pair_id: {actual_pair_id}")
                    else:
                        # 否则从 Subgraph 查询
                        logger.info("🔍 SDK 未返回 trade_index，尝试从 Subgraph 查询...")
                        positions = await self.client.get_positions(symbol=self.symbol)
                        if positions and len(positions) > 0:
                            # 获取最新的持仓（按 index 排序）
                            latest_position = max(positions, key=lambda p: p.get('index', 0))
                            actual_trade_index = latest_position.get('index')
                            actual_pair_id = latest_position.get('pair_id')
                            logger.info(f"✅ 从 Subgraph 获取 trade_index: {actual_trade_index}, pair_id: {actual_pair_id}")
                        else:
                            logger.warning("⚠️ Subgraph 查询返回空数组，可能是数据延迟")
                            # 使用 pair_id 作为备选
                            actual_pair_id = res.get('pair_id')
                            
                # 如果以上方法都失败，记录警告
                if actual_trade_index is None:
                    logger.warning(f"⚠️ 无法获取 trade_index，将在数据库中存储为 None")
                    logger.warning("⚠️ 请注意：这可能导致后续平仓失败！")
                                
            except Exception as query_error:
                logger.error(f"查询 trade_index 失败: {query_error}")
                actual_trade_index = res.get('trade_index') if res.get('trade_index') != res.get('orderId') else None
                actual_pair_id = res.get('pair_id')
            
            # 保存到 MySQL
            db_manager.save_order({
                'order_id': res['orderId'],
                'symbol': self.symbol,
                'side': side.lower(),
                'type': 'market',
                'quantity': amount,
                'price': res['price'],
                'status': 'filled',
                'createdTime': res['timestamp'],
                'tx_hash': res.get('tx_hash')
            }, source=self.source)
            
            db_manager.save_position({
                'symbol': self.symbol,
                'side': 'long' if side == 'BUY' else 'short',
                'quantity': amount,
                'entry_price': res['price'],
                'collateral': amount,
                'index': actual_trade_index,  # 使用从链上查询的值
                'pair_id': actual_pair_id,   # 使用从链上查询的值
                'opened_at': res['timestamp']
            }, source=self.source)

            db_manager.save_trade({
                'tradeId': res.get('tx_hash') or f"OPEN_{int(time.time())}",
                'orderId': res['orderId'],
                'symbol': self.symbol,
                'side': side.lower(),
                'quantity': amount,
                'price': res['price'],
                'timestamp': res['timestamp']
            }, source=self.source)
            
            logger.info("✅ 开仓成功且已存入数据库")
        else:
            logger.error(f"❌ 开仓失败: {res.get('error')}")

    async def _handle_close(self):
        """处理平仓信号"""
        # 【关键修复】优先查询数据库，而不是依赖内存状态
        session = db_manager.get_session()
        try:
            active_position = session.query(Position).filter_by(
                source=self.source,
                closed_at=None
            ).order_by(Position.id.desc()).first()
            
            if active_position or self.current_position:
                # 数据库有活跃仓位或内存中有仓位，执行平仓
                if active_position:
                    # 同步内存状态
                    self.current_position = 'LONG' if active_position.side == 'long' else 'SHORT'
                    logger.info(f"🔄 从数据库恢复仓位状态: {self.current_position}")
                await self._close_position("信号平仓")
            else:
                logger.info("当前无仓位可平")
        finally:
            session.close()

    async def _close_position(self, reason: str):
        """执行平仓并记录历史"""
        if not self.current_position:
            return

        session = db_manager.get_session()
        # 1. 查找活跃仓位（不限制 symbol，支持交易对切换）
        # 【关键】只查询 closed_at 为 None 的记录，这才是未平仓的持仓
        pos = session.query(Position).filter_by(
            source=self.source,
            closed_at=None
        ).order_by(Position.id.desc()).first()
        
        if pos:
            logger.info(f"🔍 找到未平仓持仓: id={pos.id}, symbol={pos.symbol}, pair_id={pos.pair_id}, trade_index={pos.trade_index}, opened_at={pos.opened_at}")
        
        # 彻底提取所有属性，完全解除与 Session 的绑定，防止 DetachedInstanceError
        if pos:
            entry_val = float(pos.entry_price)
            qty_val = float(pos.quantity)
            collateral_val = float(pos.collateral) if pos.collateral else (qty_val / self.leverage)
            side_val = pos.side
            symbol_val = pos.symbol
            opened_at_val = pos.opened_at
            # 先使用数据库中的值作为备选
            trade_index_val = int(pos.trade_index) if pos.trade_index is not None else 0
            pair_id_val = int(pos.pair_id) if pos.pair_id is not None else 12
        else:
            logger.warning(f"数据库中未找到活跃仓位，尝试根据 {self.symbol} 盲平")
            entry_val, qty_val, collateral_val = 0, 0, 0
            side_val = 'long'
            symbol_val = self.symbol
            opened_at_val = datetime.now()
            trade_index_val = 0
            asset, _ = self.client._parse_pair_info(self.symbol)
            pair_id_val = self.client._get_asset_type_id(asset) or 12

        # 【关键修复】使用数据库中保存的真实 trade_index
        # 不能硬编码为 0，否则会平错订单
        close_pair_id = pair_id_val  # 使用数据库中的值
        close_index = trade_index_val  # 使用数据库中的值
        
        # 【关键修复】2026-01-23 发现：由于 Ostium SDK closeTradeMarket 函数中 trade_index 为 uint8 类型
        # 但链上全局 trade_index 已超过 130 万，远超 uint8 最大值 255
        # 根据数据库历史记录，之前成功平仓的 trade_index 都是 None/0
        # SDK 对 None/0 有容错机制，会自动匹配账户最后一笔交易
        # 因此即使 trade_index=0 也允许平仓
        if close_index is None:
            close_index = 0  # 将 None 转为 0，利用 SDK 的容错机制
            logger.warning(f"⚠️ trade_index 为 None，转为 0 并利用 SDK 容错机制平仓")
        
        logger.info(f"🔥 平仓请求: pair_id={close_pair_id}, trade_index={close_index} (利用SDK容错机制)")
        
        current_price = await self.client.get_price(self.symbol)
        res = await self.client.close_position(close_pair_id, close_index, market_price=current_price)
        
        if res.get('status') == 'CLOSED':
            if pos:
                # 【关键修复】平仓时设置 closed_at 为当前时间，标记为已平仓
                close_time = datetime.now()
                logger.info(f"💾 更新持仓状态为已平仓: symbol={symbol_val}, closed_at={close_time}")
                db_manager.save_position({
                    'symbol': symbol_val,
                    'side': side_val,
                    'quantity': qty_val,
                    'entry_price': entry_val,
                    'current_price': current_price,
                    'collateral': collateral_val if collateral_val > 0 else None,
                    'trade_index': close_index,
                    'pair_id': close_pair_id,
                    'opened_at': opened_at_val,
                    'closed_at': close_time  # 设置平仓时间，用于区分已平仓和未平仓
                }, source=self.source)
            
            # 计算盈亏
            pnl_percent = 0
            pnl_amount = 0
            if entry_val > 0 and current_price and entry_val > 0:
                # 验证价格合理性（避免除零或异常值）
                if entry_val < 0.01 or current_price < 0.01:
                    logger.warning(f"⚠️ 价格异常: entry_price={entry_val}, current_price={current_price}，跳过 PnL 计算")
                else:
                    diff = (current_price - entry_val) / entry_val
                    if side_val == 'short':
                        diff = -diff
                    pnl_percent = diff * self.leverage
                    pnl_amount = pnl_percent * (collateral_val or (qty_val / self.leverage))
                    logger.info(f"📊 PnL 计算: entry={entry_val}, current={current_price}, diff={diff*100:.4f}%, leverage={self.leverage}x, PnL={pnl_percent*100:.2f}%")

            # 保存成交历史
            tx_hash = res.get('transactionHash') or res.get('tx_hash') or f"CLOSE_{int(time.time())}"
            db_manager.save_trade({
                'tradeId': tx_hash,
                'orderId': tx_hash,
                'symbol': self.symbol,
                'side': 'sell' if self.current_position == 'LONG' else 'buy',
                'quantity': qty_val,
                'price': current_price,
                'close_price': current_price,
                'pnl_percent': pnl_percent,
                'pnl_amount': pnl_amount,
                'reason': reason,
                'timestamp': res['timestamp']
            }, source=self.source)
            
            self.current_position = None
            logger.info(f"✅ 平仓成功: {reason}, PnL: {pnl_percent*100:.2f}%")
            
            # 风险检查 - 已禁用连续两笔亏损熔断
            # self._check_risk_circuit_breaker()
        else:
            logger.error(f"❌ 平仓失败: {res.get('error')}")
        session.close()

    def _check_risk_circuit_breaker(self):
        """风险统计熔断检查 - 已禁用
        - 单数 < 20: 连续两笔亏损超过 3% 触发熔断
        - 单数 >= 20: 连续两笔亏损超过平均亏损触发熔断
        
        此功能已按用户要求禁用
        """
        pass
        # try:
        #     session = db_manager.get_session()
        #     
        #     # 统计总单数
        #     total_trades = session.query(Trade).filter(
        #         Trade.source == self.source,
        #         Trade.pnl_percent.isnot(None)
        #     ).count()
        #     
        #     # 获取最近两笔交易
        #     trades = session.query(Trade).filter(
        #         Trade.symbol == self.symbol,
        #         Trade.source == self.source,
        #         Trade.pnl_percent.isnot(None)
        #     ).order_by(Trade.id.desc()).limit(2).all()
        #     
        #     if len(trades) < 2:
        #         session.close()
        #         return
        #     
        #     last_two = [float(t.pnl_percent) for t in trades]
        #     
        #     # 判断是否触发熔断
        #     should_stop = False
        #     trigger_reason = ""
        #     threshold_info = ""
        #     
        #     if total_trades < 20:
        #         # 单数少于20: 连续两笔亏损超过 3%
        #         threshold = -0.03
        #         if all(p < threshold for p in last_two):
        #             should_stop = True
        #             trigger_reason = "连续亏损超过3%"
        #             threshold_info = f"阈值: 3% (单数{total_trades}<20)"
        #     else:
        #         # 单数>=20: 按均值判断
        #         all_losses = session.query(Trade.pnl_percent).filter(
        #             Trade.source == self.source,
        #             Trade.pnl_percent.isnot(None),
        #             Trade.pnl_percent < 0
        #         ).all()
        #         
        #         if all_losses:
        #             avg_loss = sum(float(l[0]) for l in all_losses) / len(all_losses)
        #             if all(p < 0 and p < avg_loss for p in last_two):
        #                 should_stop = True
        #                 trigger_reason = "连续亏损超过均值"
        #                 threshold_info = f"平均亏损: {avg_loss*100:.2f}% (单数{total_trades}>=20)"
        #     
        #     if should_stop:
        #         logger.warning(f"🚨 触发熔断：{trigger_reason}")
        #         self.is_stopped = True
        #         
        #         # 记录风险事件到数据库
        #         try:
        #             db_manager.save_risk_event(
        #                 event_type='circuit_breaker',
        #                 severity='high',
        #                 description=f"系统熔断触发: {trigger_reason}. 最近PnL: {[f'{p*100:.2f}%' for p in last_two]}",
        #                 affected_symbols=self.symbol,
        #                 source=self.source
        #             )
        #         except Exception as e:
        #             logger.error(f"保存风险事件失败: {e}")
        # 
        #         # 发送熔断通知
        # 
        #         asyncio.create_task(self.send_dingtalk_notification(
        #             f"🚨 系统熔断通知\n"
        #             f"触发原因: {trigger_reason}\n"
        #             f"最近两笔: {last_two[0]*100:.2f}%, {last_two[1]*100:.2f}%\n"
        #             f"{threshold_info}\n"
        #             f"系统已暂停交易，请手动重置后恢复"
        #         ))
        #     session.close()
        # except Exception as e:
        #     logger.error(f"风险统计检查异常: {e}")

    async def run_risk_monitor(self):
        """实时止损监控"""
        logger.info("🛡️ 实时风险监控已启动")
        while not self.is_stopped:
            try:
                await asyncio.sleep(15)
                if self.current_position:
                    session = db_manager.get_session()
                    pos = session.query(Position).filter_by(symbol=self.symbol, source=self.source, closed_at=None).first()
                    if pos:
                        entry = float(pos.entry_price)
                        current = await self.client.get_price(self.symbol)
                        if current:
                            diff = (current - entry) / entry
                            if pos.side == 'short': diff = -diff
                            pnl = diff * self.leverage
                            if pnl <= -self.stop_loss_percent:
                                logger.warning(f"🚨 触发止损: {pnl*100:.2f}%")
                                
                                # 记录风险事件到数据库
                                try:
                                    db_manager.save_risk_event(
                                        event_type='stop_loss_triggered',
                                        severity='high',
                                        description=f"触发止损平仓: {pnl*100:.2f}%. 止损线: {self.stop_loss_percent*100:.2f}%",
                                        affected_symbols=self.symbol,
                                        source=self.source
                                    )
                                except:
                                    pass

                                await self._close_position(f"单笔强制止损")

                                self.is_stopped = True
                                # 发送熔断通知
                                await self.send_dingtalk_notification(
                                    f"🚨 系统熔断通知\n"
                                    f"触发原因: 单笔止损\n"
                                    f"亏损比例: {pnl*100:.2f}%\n"
                                    f"止损线: {self.stop_loss_percent*100:.2f}%\n"
                                    f"系统已暂停交易，请手动重置后恢复"
                                )
                    session.close()
            except Exception as e:
                logger.error(f"风险监控异常: {e}")

    async def run_market_monitor(self):
        """休市监控"""
        while True:
            try:
                await asyncio.sleep(60)
                if not self.is_trading_time():
                    if self.current_position:
                        logger.info(f"到达休市时间段，检测到 {self.current_position} 仓位，执行自动平仓")
                        await self._close_position("休市自动平仓")
            except Exception as e:
                logger.error(f"休市监控异常: {e}")

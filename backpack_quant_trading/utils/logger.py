import logging
import os
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import sys


# Windows下的安全文件处理器（每条写入后 flush，便于 tail/实时查看）
class SafeRotatingFileHandler(RotatingFileHandler):
    """Windows安全的文件轮转处理器"""
    def emit(self, record):
        super().emit(record)
        if self.stream:
            try:
                self.stream.flush()
            except Exception:
                pass

    def doRollover(self):
        """覆盖轮转逻辑，避免Windows权限问题"""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # 不进行重命名，直接使用新文件
        # 这样避免了Windows下的权限冲突
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        try:
                            os.remove(dfn)
                        except:
                            pass
                    try:
                        os.rename(sfn, dfn)
                    except:
                        pass
            
            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                try:
                    os.remove(dfn)
                except:
                    pass
            
            # 创建新文件，不重命名旧文件
            self.mode = 'w'
        
        if not self.delay:
            self.stream = self._open()


def setup_logger(name: str = None,
                 log_dir: Path = Path("./log"),
                 level: int = logging.INFO,
                 console: bool = True,
                 file: bool = True,
                 max_file_size: int = 10 * 1024 * 1024,  # 10MB
                 backup_count: int = 5) -> logging.Logger:
    """配置并返回logger实例。如果name为None，配置根logger"""
    # 确保日志目录存在
    log_dir.mkdir(parents=True, exist_ok=True)

    # 获取logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 如果是配置根logger且已经有处理器了，通常是因为basicConfig被调用过
    if name is None and logger.handlers:
        logger.handlers.clear()
    elif name is not None:
        logger.handlers.clear()

    # 格式化器
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器（使用行缓冲，便于实时看到输出）
    if console:
        try:
            import io
            stderr_line_buffered = io.TextIOWrapper(sys.stderr.buffer, encoding=sys.stderr.encoding, line_buffering=True)
            console_handler = logging.StreamHandler(stderr_line_buffered)
        except Exception:
            console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件处理器（按大小轮转）
    if file:
        # 交易日志 - 使用SafeRotatingFileHandler避免Windows权限问题
        trade_log = log_dir / "trades.log"
        trade_handler = SafeRotatingFileHandler(
            trade_log, maxBytes=max_file_size, backupCount=backup_count, encoding='utf-8'
        )
        trade_handler.setLevel(logging.DEBUG)
        trade_handler.setFormatter(formatter)
        logger.addHandler(trade_handler)

        # 错误日志
        error_log = log_dir / "errors.log"
        error_handler = SafeRotatingFileHandler(
            error_log, maxBytes=max_file_size, backupCount=backup_count, encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        logger.addHandler(error_handler)

        # 常规日志
        general_log = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"
        general_handler = SafeRotatingFileHandler(
            general_log, maxBytes=max_file_size, backupCount=backup_count, encoding='utf-8'
        )
        general_handler.setLevel(level)
        general_handler.setFormatter(formatter)
        logger.addHandler(general_handler)

    return logger


def get_logger(name: str = "backpack_quant") -> logging.Logger:
    """获取logger实例（简化版）"""
    return logging.getLogger(name)


# 获取默认logger
logger = get_logger("backpack_quant")


class TradeLogger:
    """交易专用日志记录器"""

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or get_logger("trades")
        self.trade_log_file = Path("./log/trades_detailed.log")

    def log_order(self, order_data: dict):
        """记录订单信息"""
        self.logger.info(f"ORDER: {order_data}")

    def log_trade(self, trade_data: dict):
        """记录成交信息"""
        msg = (
            f"TRADE | Symbol: {trade_data.get('symbol')} | "
            f"Side: {trade_data.get('side')} | "
            f"Qty: {trade_data.get('quantity')} | "
            f"Price: {trade_data.get('price')} | "
            f"PnL: {trade_data.get('pnl', 'N/A')}"
        )
        self.logger.info(msg)

    def log_signal(self, signal_data: dict):
        """记录交易信号"""
        msg = (
            f"SIGNAL | Symbol: {signal_data.get('symbol')} | "
            f"Action: {signal_data.get('action')} | "
            f"Confidence: {signal_data.get('confidence', 0):.2%} | "
            f"Reason: {signal_data.get('reason', 'N/A')}"
        )
        self.logger.info(msg)

    def log_error(self, error_type: str, error_msg: str, context: dict = None):
        """记录错误"""
        msg = f"ERROR | Type: {error_type} | Message: {error_msg}"
        if context:
            msg += f" | Context: {context}"
        self.logger.error(msg)

    def log_risk_event(self, event_type: str, details: dict):
        """记录风险事件"""
        msg = f"RISK | Type: {event_type} | Details: {details}"
        self.logger.warning(msg)

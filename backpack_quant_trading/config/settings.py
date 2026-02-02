import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# 只在环境变量未设置时加载密码，避免被空值覆盖
if not os.getenv("DB_PASSWORD"):
    os.environ["DB_PASSWORD"] = "zyf200018"
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

#dataclass 数据类标识
@dataclass
class BackpackConfig:
    """Backpack Exchange 配置"""
    #REST API请求地址(同步接口：用于查询行情，提交订单，查询资产)
    API_BASE_URL: str = "https://api.backpack.exchange"
    #WebSocket接口地址(异步接口：用于实时推送行情，订单成交数据)
    WS_BASE_URL: str = "wss://ws.backpack.exchange"
    #API密钥
    API_KEY: str = os.getenv("BACKPACK_API_KEY", "")
    #交易所私钥
    PRIVATE_KEY: str = os.getenv("BACKPACK_PRIVATE_KEY", "")
    #交易所公钥
    PUBLIC_KEY: str = os.getenv("BACKPACK_PUBLIC_KEY", "")
    #默认请求窗口时长
    DEFAULT_WINDOW: int = 5000
    #最大请求窗口时长
    MAX_WINDOW: int = 60000
    #Cookie认证（可选，用于Web API访问）
    ACCESS_KEY: str = os.getenv("BACKPACK_ACCESS_KEY", "")
    REFRESH_KEY: str = os.getenv("BACKPACK_REFRESH_KEY", "")

@dataclass
class HyperliquidConfig:
    """Hyperliquid 配置"""
    API_BASE_URL: str = "https://api.hyperliquid.xyz"
    WS_BASE_URL: str = "wss://api.hyperliquid.xyz/ws"
    # 账户私钥
    PRIVATE_KEY: str = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
    # 代理地址（如有）
    AGENT_ADDRESS: str = os.getenv("HYPERLIQUID_AGENT_ADDRESS", "")

@dataclass
class DatabaseConfig:
    """数据库配置"""
    HOST:str=os.getenv("DB_HOST", "localhost")
    PORT:int=int(os.getenv("DB_PORT",3306))
    USER:str=os.getenv("DB_USER", "root")
    PASSWORD:str=os.getenv("DB_PASSWORD", "zyf200018")
    NAME:str=os.getenv("DB_NAME", "backpack")
    POOL_SIZE: int = 20
    MAX_OVERFLOW:int=30

@dataclass
class TradingConfig:
    """交易配置"""
    MAX_POSITION_SIZE:float=0.1 #单笔最大仓位比例
    MAX_DAILY_LOSS:float=0.5 #单日最大亏损
    MAX_DRAWDOWN:float=0.15 #最大回撤
    ENABLE_STOP_LOSS:bool=True #是否启用止损
    STOP_LOSS_PERCENT:float=0.05 # 单个订单亏损达到 5% 时，自动卖出止损 (Ostium 默认)
    TAKE_PROFIT_PERCENT:float=0.20 # 单个订单盈利达到 20% 时，自动止盈卖出 (Ostium 默认)
    RISK_FREE_RATE:float=0.02  #无风险利率 -->年化2%
    LEVERAGE:int=5  #默认杠杆倍数


@dataclass
class OstiumConfig:
    """Ostium Exchange 配置"""
    RPC_URL: str = os.getenv("OSTIUM_RPC_URL", "https://arbitrum-mainnet.infura.io/v3/92165a5588524285865205014a04a79f")
    PRIVATE_KEY: str = os.getenv("OSTIUM_PRIVATE_KEY", "")
    NETWORK: str = os.getenv("OSTIUM_NETWORK", "mainnet")
    SYMBOL: str = os.getenv("OSTIUM_SYMBOL", "NDX-USD")
    LEVERAGE: int = int(os.getenv("OSTIUM_LEVERAGE", 5))


@dataclass
class WebhookConfig:
    """TradingView Webhook 配置"""
    SECRET: str = os.getenv("WEBHOOK_SECRET", "your-secret-key-here")
    HOST: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("WEBHOOK_PORT", 8005))
    DINGTALK_TOKEN: str = os.getenv("DINGTALK_TOKEN", "093b410911e49a071f0215528e9796c79a4fef81b02af280acddf2e08d92b6ee")
    DINGTALK_SECRET: str = os.getenv("DINGTALK_SECRET", "SEC40ec4439b5bee6976073e681e0c3ec035af44b33fbbc160640e66b5a483c3a2c")
    # 信号规则
    HIGH_QTY_MIN: float = float(os.getenv("WEBHOOK_HIGH_QTY_MIN", 10.0))
    HIGH_QTY_MAX: float = float(os.getenv("WEBHOOK_HIGH_QTY_MAX", 11.0))
    LOW_QTY_RATIO: float = float(os.getenv("WEBHOOK_LOW_QTY_RATIO", 1.0))


@dataclass
class DeepcoinConfig:
    """Deepcoin Exchange 配置"""
    API_BASE_URL: str = os.getenv("DEEPCOIN_API_BASE_URL", "https://api.deepcoin.com")
    API_KEY: str = os.getenv("DEEPCOIN_API_KEY", "")
    SECRET_KEY: str = os.getenv("DEEPCOIN_SECRET_KEY", "")
    PASSPHRASE: str = os.getenv("DEEPCOIN_PASSPHRASE", "")
    # 默认合约交易配置
    DEFAULT_MARGIN_MODE: str = os.getenv("DEEPCOIN_MARGIN_MODE", "isolated") # isolated 或 cross
    DEFAULT_MERGE_POSITION: str = os.getenv("DEEPCOIN_MERGE_POSITION", "split") # merge 或 split
    LEVERAGE: int = int(os.getenv("DEEPCOIN_LEVERAGE", 5))


class Config:
    """全局配置"""
    def __init__(self):
        self.backpack=BackpackConfig()
        self.hyperliquid=HyperliquidConfig()
        self.database=DatabaseConfig()
        self.trading=TradingConfig()
        self.ostium = OstiumConfig()
        self.deepcoin = DeepcoinConfig()
        self.webhook = WebhookConfig()
        
        # 统一项目根目录，确保日志和数据目录位置一致
        self.project_root = Path(__file__).parent.parent.absolute()
        self.data_dir = self.project_root / "data"
        self.log_dir = self.project_root / "log"

        #创建必要的目录
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def database_url(self)->str:
        """获取数据库连接URL"""
        return (
            f"mysql+pymysql://{self.database.USER}:{self.database.PASSWORD}" 
            f"@{self.database.HOST}:{self.database.PORT}/{self.database.NAME}"
        )
#模块级别实例化config类
config=Config()





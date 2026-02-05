import pandas as pd
import numpy as np
import json
import os
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .api_client import BackpackAPIClient
from ..config.settings import config
from ..utils.logger import get_logger
from ..database.models import db_manager

logger = get_logger(__name__)


class DataManager:
    """数据管理器
    负责市场数据的获取、处理、存储和缓存
    """

    # 类级别的缓存，所有实例共享
    market_data_cache: Dict[str, pd.DataFrame] = {}
    order_book_cache: Dict[str, Dict] = {}
    cache_config = {
        'max_cache_size': 1000,
        'cache_ttl': 3600,
        'last_update': {}
    }

    def __init__(self, api_client: BackpackAPIClient = None, mode: str = 'backtest'):
        self.api_client = api_client
        self.mode = mode

        # 数据存储路径
        self.data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        os.makedirs(self.data_dir, exist_ok=True)

        # 每个实例的配置（保持原有结构但引用类级别的缓存）
        self._init_mock_prices()

    def _init_mock_prices(self):
        """初始化模拟价格数据"""
        self.mock_prices = {
            'SOL_USDC': 100.0,
            'BTC_USDC': 65000.0,
            'ETH_USDC': 3500.0,
        }
        self.mock_volatility = {
            'SOL_USDC': 0.03,
            'BTC_USDC': 0.02,
            'ETH_USDC': 0.025,
        }

    def generate_mock_data(self, symbol: str, days: int = 30,
                           interval: str = '1h') -> pd.DataFrame:
        """生成模拟K线数据用于回测"""
        if symbol not in self.mock_prices:
            logger.error(f"Unknown symbol: {symbol}")
            return pd.DataFrame()

        base_price = self.mock_prices[symbol]
        volatility = self.mock_volatility[symbol]

        if interval == '1h':
            periods_per_day = 24
        elif interval == '4h':
            periods_per_day = 6
        elif interval == '1d':
            periods_per_day = 1
        else:
            periods_per_day = 24

        total_periods = days * periods_per_day

        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)

        if interval == '1h':
            timestamps = pd.date_range(start=start_time, periods=total_periods, freq='1h')
        elif interval == '4h':
            timestamps = pd.date_range(start=start_time, periods=total_periods, freq='4h')
        elif interval == '1d':
            timestamps = pd.date_range(start=start_time, periods=total_periods, freq='1D')
        else:
            timestamps = pd.date_range(start=start_time, periods=total_periods, freq='1h')

        returns = np.random.normal(0.0001, volatility, total_periods)
        price_changes = np.cumprod(1 + returns)
        close_prices = base_price * price_changes

        opens = close_prices * (1 + np.random.uniform(-0.002, 0.002, total_periods))
        highs = np.maximum(opens, close_prices) * (1 + np.random.uniform(0, 0.01, total_periods))
        lows = np.minimum(opens, close_prices) * (1 - np.random.uniform(0, 0.01, total_periods))
        volumes = np.random.uniform(1000, 10000, total_periods) * (1 + abs(returns) * 10)

        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': close_prices,
            'volume': volumes
        })

        df = self._clean_data(df)

        df.set_index('timestamp', inplace=True)

        logger.info(f"生成模拟数据 {symbol}: {len(df)} 条记录")
        return df

    def fetch_historical_data(self, symbol: str, interval: str,
                              start_time: datetime, end_time: datetime = None) -> pd.DataFrame:
        """获取历史K线数据"""
        if end_time is None:
            end_time = datetime.now()

        if start_time >= end_time:
            logger.error(f"开始时间 {start_time} 不能晚于结束时间 {end_time}")
            return pd.DataFrame()

        days = (end_time - start_time).days
        if days > 365:
            logger.warning("时间范围超过1年，可能获取数据量过大")

        if self.mode == 'backtest' or self.api_client is None:
            logger.info(f"回测模式: 生成 {symbol} 模拟数据")
            return self.generate_mock_data(symbol, days=min(days, 90), interval=interval)

        cache_key = f"{symbol}_{interval}_{start_time}_{end_time}"

        if cache_key in self.market_data_cache:
            last_update = self.cache_config['last_update'].get(cache_key)
            if last_update and (datetime.now() - last_update).seconds < self.cache_config['cache_ttl']:
                logger.debug(f"使用缓存数据: {cache_key}")
                return self.market_data_cache[cache_key].copy()

        try:
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())

            klines = self.api_client.get_klines(symbol, interval, start_ts, end_ts)

            if not klines:
                logger.warning(f"未获取到 {symbol} 的K线数据")
                return pd.DataFrame()

            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            if len(df) == 0:
                return pd.DataFrame()

            df = self._clean_data(df)

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('timestamp', inplace=True)

            if not df.empty:
                self.market_data_cache[cache_key] = df.copy()
            
            return df
            
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return pd.DataFrame()
    
    async def add_kline_data(self, symbol: str, data: dict, interval: str = '15m'):
        """添加实时K线数据（适配Backpack格式）
        
        Args:
            symbol: 交易对
            data: K线数据（Backpack格式）
            interval: 时间周期，默认为15m（AI策略使用15分钟K线）
        """
        try:
            # 提取K线数据
            timestamp_raw = data.get('t')
            if timestamp_raw is not None:
                try:
                    # 处理不同的时间戳格式
                    if isinstance(timestamp_raw, (int, float)):
                        # 时间戳（秒或毫秒）
                        ts_val = int(timestamp_raw)
                        # 【关键修复】转换为UTC时间，然后转为本地时区
                        timestamp = pd.to_datetime(ts_val, unit='ms' if len(str(ts_val)) > 10 else 's', utc=True)
                        timestamp = timestamp.tz_convert('Asia/Shanghai')  # 转为北京时间
                        timestamp = timestamp.tz_localize(None)  # 移除时区信息，保留本地时间
                    elif isinstance(timestamp_raw, str):
                        # 如果是纯数字字符串
                        if timestamp_raw.isdigit():
                            ts_val = int(timestamp_raw)
                            timestamp = pd.to_datetime(ts_val, unit='ms' if len(str(ts_val)) > 10 else 's', utc=True)
                            timestamp = timestamp.tz_convert('Asia/Shanghai')
                            timestamp = timestamp.tz_localize(None)
                        else:
                            # ISO格式字符串
                            timestamp = pd.to_datetime(timestamp_raw, utc=True)
                            timestamp = timestamp.tz_convert('Asia/Shanghai')
                            timestamp = timestamp.tz_localize(None)
                    else: 
                        timestamp = pd.to_datetime(timestamp_raw, utc=True)
                        timestamp = timestamp.tz_convert('Asia/Shanghai')
                        timestamp = timestamp.tz_localize(None)
                except Exception as e:
                    logger.error(f"解析时间戳失败: {timestamp_raw}, 错误: {e}")
                    # 使用当前时间作为后备
                    timestamp = pd.to_datetime(datetime.now())
            else:
                # 如果没有时间戳，使用当前时间
                timestamp = pd.to_datetime(datetime.now())
            
            # 更严格地获取并转换价格数据，确保值是有效的
            def safe_float_convert(value, default=0.0):
                """安全转换为float，处理各种异常情况"""
                if value is None:
                    return default
                try:
                    if isinstance(value, (int, float)):
                        return float(value)
                    elif isinstance(value, str):
                        # 清理字符串中的空格和异常字符
                        clean_value = value.strip()
                        if clean_value:
                            return float(clean_value)
                    return default
                except (ValueError, TypeError):
                    return default
            
            open_price = safe_float_convert(data.get('o'))
            high_price = safe_float_convert(data.get('h'))
            low_price = safe_float_convert(data.get('l'))
            close_price = safe_float_convert(data.get('c'))
            volume = safe_float_convert(data.get('v'))
            
            # 跳过无效的K线数据（价格为null或零）
            if close_price == 0 or open_price == 0:
                logger.debug(f"跳过无效K线数据: {symbol} - 时间: {timestamp}, 开盘价: {open_price}, 收盘价: {close_price}")
                return
            
            # 创建新的K线数据行
            new_kline = pd.DataFrame({
                'timestamp': [timestamp],
                'open': [open_price],
                'high': [high_price],
                'low': [low_price],
                'close': [close_price],
                'volume': [volume]
            })
            
            # 设置索引
            new_kline.set_index('timestamp', inplace=True)
            
            # 更新缓存
            cache_key = f"{symbol}_{interval}_live"
            
            if cache_key in self.market_data_cache:
                # 如果缓存存在，追加或更新数据
                existing_data = self.market_data_cache[cache_key]
                # 检查是否为重复的时间戳（更新同一K线）
                if timestamp in existing_data.index:
                    # 更新现有的K线数据
                    self.market_data_cache[cache_key].loc[timestamp] = new_kline.loc[timestamp]
                    logger.debug(f"更新 {symbol} K线数据: {timestamp}")
                else:
                    # 追加新的K线数据
                    self.market_data_cache[cache_key] = pd.concat([existing_data, new_kline])
                    logger.info(f"添加新 {symbol} K线数据: {timestamp}，总数：{len(self.market_data_cache[cache_key])}")
                    # 保持缓存大小限制
                    if len(self.market_data_cache[cache_key]) > self.cache_config['max_cache_size']:
                        self.market_data_cache[cache_key] = self.market_data_cache[cache_key].iloc[-self.cache_config['max_cache_size']:]
            else:
                # 如果缓存不存在，创建新缓存
                self.market_data_cache[cache_key] = new_kline
            
            # 更新缓存时间
            self.cache_config['last_update'][cache_key] = datetime.now()
            
            # 输出当前缓存数据量用于调试
            current_count = len(self.market_data_cache.get(cache_key, pd.DataFrame()))
            logger.info(f"当前 {symbol} K线缓存数量: {current_count}")
            
            # 保存数据到文件，确保不同进程可以共享
            if self.mode == 'live':
                self._save_data_to_file(cache_key, self.market_data_cache[cache_key])
                
        except Exception as e:
            logger.error(f"添加K线数据失败: {e}")
    
    def _save_data_to_file(self, cache_key: str, df: pd.DataFrame):
        """保存数据到文件"""
        try:
            if df.empty:
                return
            file_path = os.path.join(self.data_dir, f"{cache_key}.csv")
            df.to_csv(file_path)
            logger.debug(f"保存数据到文件: {file_path}")
        except Exception as e:
            logger.error(f"保存数据到文件失败: {e}")
    
    async def fetch_recent_data(self, symbol: str, interval: str = '1m', limit: int = 50) -> pd.DataFrame:
        """获取最近的K线数据
        
        Args:
            symbol: 交易对
            interval: 时间周期
            limit: 返回数据条数
        
        Returns:
            pd.DataFrame: K线数据
        """
        try:
            cache_key = f"{symbol}_{interval}_live"
            
            if cache_key in self.market_data_cache:
                df = self.market_data_cache[cache_key].copy()
                # 返回最近的limit条数据
                return df.iloc[-limit:]
            else:
                logger.warning(f"缓存中没有 {symbol} 的 {interval} K线数据")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取最近K线数据失败: {e}")
            return pd.DataFrame()

    def _clean_cache(self):
        """清理过期缓存"""
        current_time = datetime.now()
        keys_to_remove = []

        for key, last_update in self.cache_config['last_update'].items():
            if (current_time - last_update).seconds > self.cache_config['cache_ttl']:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            if key in self.market_data_cache:
                del self.market_data_cache[key]
            if key in self.cache_config['last_update']:
                del self.cache_config['last_update'][key]

        if len(self.market_data_cache) > self.cache_config['max_cache_size']:
            oldest_key = min(
                self.cache_config['last_update'].items(),
                key=lambda x: x[1]
            )[0]
            if oldest_key in self.market_data_cache:
                del self.market_data_cache[oldest_key]
            if oldest_key in self.cache_config['last_update']:
                del self.cache_config['last_update'][oldest_key]

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据清洗"""
        if df.empty:
            return df

        df = df.drop_duplicates(subset=['timestamp'])

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                df[col] = df[col].ffill()

        df = df[
            (df['high'] >= df['low']) &
            (df['high'] >= df['open']) &
            (df['high'] >= df['close']) &
            (df['low'] <= df['open']) &
            (df['low'] <= df['close']) &
            (df['volume'] >= 0)
        ]

        return df.dropna()

    # 注意：此方法未使用，已注释。如需使用，需要改为异步方法
    # async def get_realtime_data(self, symbol: str) -> pd.DataFrame:
    #     """获取实时行情（异步版本）"""
    #     try:
    #         ticker = await self.api_client.get_ticker(symbol)
    #         data = {
    #             'timestamp': datetime.now(),
    #             'symbol': symbol,
    #             'price': float(ticker.get('lastPrice', 0)),
    #             'volume': float(ticker.get('volume', 0)),
    #             'bid': float(ticker.get('bidPrice', 0)),
    #             'ask': float(ticker.get('askPrice', 0)),
    #             'bid_qty': float(ticker.get('bidQty', 0)),
    #             'ask_qty': float(ticker.get('askQty', 0))
    #         }
    #         return pd.DataFrame([data])
    #     except Exception as e:
    #         logger.error(f"获取实时数据失败: {e}")
    #         return pd.DataFrame()

    def fetch_order_book(self, symbol: str, limit: int = 100) -> Dict:
        """获取订单簿"""
        try:
            order_book = self.api_client.get_depth(symbol, limit)
            self.order_book_cache[symbol] = order_book
            return order_book
        except Exception as e:
            logger.error(f"获取订单簿失败: {e}")
            return {}

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        if df.empty:
            logger.warning("DataFrame为空，无法计算技术指标")
            return df

        close = df['close']

        df['MA5'] = close.rolling(window=5).mean()
        df['MA20'] = close.rolling(window=20).mean()
        df['MA50'] = close.rolling(window=50).mean()

        bb_middle = close.rolling(window=20).mean()
        bb_std = close.rolling(window=20).std()

        df['BB_Middle'] = bb_middle
        df['BB_Std'] = bb_std
        df['BB_Upper'] = bb_middle + 2 * bb_std
        df['BB_Lower'] = bb_middle - 2 * bb_std

        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()

        rs = gain / loss.replace(0, np.nan)
        df['RSI'] = 100 - (100 / (1 + rs))

        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()

        df['MACD'] = exp1 - exp2
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        df['Volume_MA'] = df['volume'].rolling(window=20).mean()

        df['ATR'] = self._calculate_atr(df)
        df['Volatility'] = close.pct_change().rolling(window=20).std()

        df['ZScore'] = (close - close.rolling(window=20).mean()) / close.rolling(window=20).std()

        return df

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR（平均真实波幅）"""
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return atr

    def get_multi_symbol_data(self, symbols: List[str], interval: str,
                              lookback_days: int = 30) -> Dict[str, pd.DataFrame]:
        """获取多个交易对的数据"""
        data = {}
        end_time = datetime.now()
        start_time = end_time - timedelta(days=lookback_days)

        for symbol in symbols:
            try:
                df = self.fetch_historical_data(symbol, interval, start_time, end_time)
                if not df.empty:
                    df = self.calculate_technical_indicators(df)
                    data[symbol] = df
            except Exception as e:
                logger.error(f"获取 {symbol} 数据失败: {e}")
                continue

        return data

    def calculate_correlation_matrix(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """计算资产相关性矩阵"""
        if not data:
            return pd.DataFrame()

        close_prices = pd.DataFrame({symbol: df['close'] for symbol, df in data.items()})
        returns = close_prices.pct_change().dropna()

        return returns.corr()

    # 注意：此方法未使用，已注释。如需使用，需要改为异步方法
    # async def get_market_summary(self) -> Dict:
    #     """获取市场概览（异步版本）"""
    #     try:
    #         markets = await self.api_client.get_markets()
    #         ticker_data = {}
    #
    #         for symbol in list(markets.keys())[:10]:
    #             ticker = await self.api_client.get_ticker(symbol)
    #             if ticker:
    #                 ticker_data[symbol] = {
    #                     'price': float(ticker.get('lastPrice', 0)),
    #                     'volume_24h': float(ticker.get('volume', 0)),
    #                     'price_change_24h': float(ticker.get('priceChange', 0)),
    #                     'high_24h': float(ticker.get('highPrice', 0)),
    #                     'low_24h': float(ticker.get('lowPrice', 0))
    #                 }
    #
    #         return {
    #             'markets': markets,
    #             'tickers': ticker_data,
    #             'timestamp': datetime.now()
    #         }
    #     except Exception as e:
    #         logger.error(f"获取市场概览失败: {e}")
    #         return {}

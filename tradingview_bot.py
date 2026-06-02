#!/usr/bin/env python3
"""
TradingView 信号 → 钉钉推送机器人（Flask，端口默认 5001）

在不改变你原有“信号预警推送”逻辑的前提下，新增旁路：
- 当信号的 ID/筛选ID = 实盘交易 时：
  - 调用本项目的 `backpack_quant_trading.core.crypto_signal_scorer.run_signal_score()` 做 AI 评分
  - 将评分卡片发送到指定钉钉群（CONFIG.live_trade_score_webhook）

同时修复常见问题：
- PowerShell / TradingView 文本消息中文乱码：对 raw bytes 做多编码尝试解码
- No module named 'backpack_quant_trading'：自动把项目根加入 sys.path（脚本放在项目根时可用）
"""

import os
import sys
import json
import re
import socket
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify
import requests


# --- 关键：确保能 import backpack_quant_trading（脚本放在项目根即可） ---
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- 关键：确保能读到 DEEPSEEK_API_KEY（与 run_api.py 同源 .env） ---
try:
    from dotenv import load_dotenv  # type: ignore

    # 优先加载 backpack_quant_trading/.env（项目内约定的位置）
    load_dotenv(PROJECT_ROOT / "backpack_quant_trading" / ".env", override=False)
    # 兼容：如果有人把 .env 放在项目根，也加载一下
    load_dotenv(PROJECT_ROOT / ".env", override=False)
except Exception:
    # dotenv 非必需；若没装可用环境变量方式提供 DEEPSEEK_API_KEY
    pass


# ============ 配置区域 ============
CONFIG = {
    # 默认钉钉群（除特殊策略外都发这里）
    "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=06a3b0f3dc20e4171267c912bd8e4892c0c0992df47349355657b4a4c146f1a2",
    # 按提醒ID路由到不同群（优先级最高）
    "id_webhook_map": {
        "趋势信号提醒": "https://oapi.dingtalk.com/robot/send?access_token=06a3b0f3dc20e4171267c912bd8e4892c0c0992df47349355657b4a4c146f1a2",
        "做空策略提醒": "https://oapi.dingtalk.com/robot/send?access_token=615446fec028e384703e8fb4b40cb19d92a5d8f330b7f3a411dc9e8e143d0a89",
        "山寨做多策略提醒": "https://oapi.dingtalk.com/robot/send?access_token=78f43fd7bf178e69b642b20be1b76addf64879db3427736f78643385645fef49",
        "实盘交易": "https://oapi.dingtalk.com/robot/send?access_token=5c0c5fc145b217a7a10ec0d6356ae24d9dd31b620ccb4be0251ff729e5cd0adb",
        "A股策略提醒": "https://oapi.dingtalk.com/robot/send?access_token=9507265055de756e8b38b2c9175a7f696cb899fd2532f440b01715d131cf6d03",
    },
    # 特定策略单独钉钉群：ETH做空策略
    "dingtalk_webhook_eth_short": "https://oapi.dingtalk.com/robot/send?access_token=615446fec028e384703e8fb4b40cb19d92a5d8f330b7f3a411dc9e8e143d0a89",
    # 特定策略单独钉钉群：BTC 2小时中性短线 系列策略
    "dingtalk_webhook_btc_2h": "https://oapi.dingtalk.com/robot/send?access_token=217932b58a8f99f498eb49b748f051608d7c27687e06ee48781f14924ce29440",
    # 特定策略单独钉钉群：山寨做空/做多策略
    "dingtalk_webhook_altcoin": "https://oapi.dingtalk.com/robot/send?access_token=78f43fd7bf178e69b642b20be1b76addf64879db3427736f78643385645fef49",
    "dingtalk_keyword": "交易信号",
    "preferred_port": 5001,  # 首选端口
    "alternative_ports": [5001, 5002, 5003, 5004, 5005],  # 备用端口
    "debug": True,
    "public_url": "https://47.110.57.118/service",

    # ===== 实盘交易评分推送群（你指定的微信群）=====
    "live_trade_score_webhook": "https://oapi.dingtalk.com/robot/send?access_token=5dea0e1540ba7759a8dc65304552cfea54b468bba572f8a655fb71ec062c2f03",
}


def check_port_available(port: int) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result != 0
    except Exception:
        return False


def get_available_port() -> int:
    if check_port_available(CONFIG["preferred_port"]):
        return CONFIG["preferred_port"]
    for port in CONFIG["alternative_ports"]:
        if check_port_available(port):
            print(f"⚠️  端口{CONFIG['preferred_port']}被占用，使用备用端口: {port}")
            return port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()
    print(f"⚠️  使用随机端口: {port}")
    return port


def kill_process_on_port(port: int) -> bool:
    if sys.platform in ["linux", "darwin"]:
        try:
            result = subprocess.run(
                f"lsof -ti:{port}",
                shell=True,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    if pid:
                        print(f"🛑 杀死进程 {pid} (占用端口 {port})")
                        subprocess.run(f"kill -9 {pid}", shell=True)
                return True
        except Exception:
            pass
    return False


def install_requirements() -> None:
    requirements = ["flask", "requests"]
    print("🔧 检查并安装依赖包...")
    for package in requirements:
        try:
            __import__(package.replace("-", "_"))
            print(f"✅ {package} 已安装")
        except ImportError:
            print(f"📦 正在安装 {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✅ {package} 安装完成")


def _decode_request_body(raw_bytes: bytes) -> str:
    """尽量避免中文变成 ???? 的乱码问题。"""
    if raw_bytes is None:
        return ""
    for enc in ("utf-8", "utf-16", "gbk", "cp936", "latin-1"):
        try:
            s = raw_bytes.decode(enc).strip()
            # 乱码特征：大量 ? 或 �，继续尝试其它编码
            if s.count("?") > 10 or "�" in s:
                continue
            return s
        except Exception:
            continue
    return raw_bytes.decode("utf-8", errors="ignore").strip()


def _normalize_tv_timeframe(value: str) -> str:
    """
    将 TradingView/文本里的周期字段规范化为评分模块可识别的格式。
    支持：
    - 2h/4h/8h/12h/1d/1w
    - 1H/2H/4H/8H/12H/1D/1W
    - 分钟数（如 60/120/240/480/720/1440；以及 640 这种非标准值会映射到最近支持值）
    """
    v = str(value or "").strip()
    if not v:
        return ""

    # 统一大小写与尾缀
    v_up = v.upper().replace(" ", "")
    v_low = v.lower().replace(" ", "")

    # 直接支持的字符串
    if v_low in ("1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w"):
        return v_low
    if v_up in ("1H", "2H", "4H", "6H", "8H", "12H", "1D", "1W", "D", "W"):
        if v_up == "D":
            return "1d"
        if v_up == "W":
            return "1w"
        return v_up.lower()

    # 纯数字：按分钟映射/就近映射
    if re.fullmatch(r"\d{1,5}", v_up):
        try:
            minutes = int(v_up)
        except ValueError:
            return ""
        supported = [60, 120, 240, 360, 480, 720, 1440]
        closest = min(supported, key=lambda x: abs(x - minutes))
        if closest == 1440:
            return "1d"
        if closest == 60:
            return "1h"
        if closest == 120:
            return "2h"
        if closest == 240:
            return "4h"
        if closest == 360:
            return "6h"
        if closest == 480:
            return "8h"
        if closest == 720:
            return "12h"
        return ""

    # 其它未知写法：不强行猜
    return ""


class TradingViewBot:
    def __init__(self, config: dict):
        self.config = config
        self.message_log = []
        self.buy_signal_counter = {}

    def normalize_message(self, message):
        if isinstance(message, dict):
            message = str(message)
        message = message.replace("\n", " ").replace("\r", " ").strip()
        message = re.sub(r"\s+", " ", message)
        return message

    def extract_symbol(self, message: str) -> str:
        new_pattern = r"交易品种[:：]\s*([A-Za-z0-9]+)"
        match = re.search(new_pattern, message, re.IGNORECASE)
        if match:
            return match.group(1).strip().upper()
        old_patterns = [
            r"成交币种[:：]\s*([A-Za-z]+USDT)",
            r"币种[:：]\s*([A-Za-z]+USDT)",
            r"品种[:：]\s*([A-Za-z]+USDT)",
            r"([A-Za-z]+USDT)",
        ]
        for pattern in old_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1).strip().upper()
        return "未知品种"

    def infer_action_from_text(self, message: str) -> str:
        msg = message or ""
        msg_lower = msg.lower()
        if re.search(r"(清空|平仓|全平|清仓|close\s*all|close|exit)", msg, re.IGNORECASE):
            return "清空"
        if ("sell" in msg_lower) or ("卖出" in msg) or ("看空" in msg) or ("short" in msg_lower) or ("做空" in msg):
            return "卖出"
        if ("buy" in msg_lower) or ("买入" in msg) or ("看多" in msg) or ("long" in msg_lower) or ("做多" in msg):
            return "买入"
        return ""

    def extract_symbol_from_strategy_prefix(self, message: str) -> str:
        if not message:
            return "未知品种"
        m = re.search(
            r"策略[:：]\s*([A-Za-z]{2,15})(?=(?:USDT)?(?:买入|卖出|清空|平仓|看多|看空|做多|做空|long|short))",
            message,
            re.IGNORECASE,
        )
        if not m:
            return "未知品种"
        return m.group(1).strip().upper()

    def parse_tradingview_message(self, raw_message):
        if isinstance(raw_message, dict):
            raw_msg = raw_message.get("raw_message", str(raw_message))
            return self.parse_tradingview_message(raw_msg)

        parsed_data = {
            "raw_message": raw_message,
            "alert_id": "",
            "symbol": "未知品种",
            "signal": "信号",
            "price": "N/A",
            "price_label": "",
            "current_price": "N/A",
            "stop_loss_price": "",
            "take_profit_price": "",
            "strategy": "未知策略",
            "action": "",
            "position_size": "",
            "signal_strength": "N/A",
            "timeframe": "",
            "id": "",
        }

        clean_message = self.normalize_message(raw_message)
        if CONFIG["debug"]:
            print(f"📝 标准化后消息: '{clean_message}'")

        # ID：xxx
        id_match = re.search(
            r"ID\s*[:：]\s*(.*?)(?:\s*策略[:：]|\s*交易品种[:：]|\s*方向[:：]|\s*成交价格[:：]|[，,]|$)",
            clean_message,
            re.IGNORECASE,
        )
        if id_match:
            alert_id = id_match.group(1).strip()
            parsed_data["alert_id"] = alert_id
            parsed_data["id"] = alert_id

        strategy_match = re.search(
            r"策略[:：]\s*(.*?)(?:\s*交易品种|\s*当前价格|\s*成交价格|\s*方向|\s*仓位|\s*信号强度|[，,]|$)",
            clean_message,
        )
        if strategy_match:
            strategy = strategy_match.group(1).strip()
            parsed_data["strategy"] = strategy
            timeframe_match = re.search(r"(\d+[hHdDmM])", strategy)
            if timeframe_match:
                parsed_data["timeframe"] = timeframe_match.group(1).strip()

        if not parsed_data["timeframe"]:
            # 只认「周期:」，不要把「离场周期/进场级别」当成 K线周期（那通常是策略参数如 640）
            explicit_tf_match = re.search(r"(?:周期)[:：]\s*([^\s,，]+)", clean_message)
            if explicit_tf_match:
                parsed_data["timeframe"] = explicit_tf_match.group(1).strip()

        direction_match = re.search(r"方向[:：]\s*(\w+)", clean_message)
        if direction_match:
            direction = direction_match.group(1).strip()
            parsed_data["action"] = direction
            if "buy" in direction.lower() or "买入" in direction:
                parsed_data["signal"] = "买入"
            elif "sell" in direction.lower() or "卖出" in direction:
                parsed_data["signal"] = "卖出"
            elif "close" in direction.lower() or "exit" in direction.lower() or "平仓" in direction or "清空" in direction:
                parsed_data["signal"] = "清空"
            else:
                parsed_data["signal"] = direction

        position_match = re.search(r"仓位[:：]\s*([\d.-]+|.+?)", clean_message)
        if not position_match:
            position_match = re.search(r"(?:新策略仓位|策略仓位)[:：]?\s*([^\s,，。]+)", clean_message)
        if position_match:
            parsed_data["position_size"] = position_match.group(1).strip()

        parsed_data["symbol"] = self.extract_symbol(clean_message)
        if parsed_data["symbol"] == "未知品种":
            strategy_symbol = self.extract_symbol_from_strategy_prefix(clean_message)
            if strategy_symbol != "未知品种":
                parsed_data["symbol"] = strategy_symbol

        price_patterns = [
            r"成交价格[:：]\s*([^\s,，]+)",
            r"买入价格[:：]\s*([^\s,，]+)",
            r"卖出价格[:：]\s*([^\s,，]+)",
            r"价格[:：]\s*([^\s,，]+)",
        ]
        for pattern in price_patterns:
            match = re.search(pattern, clean_message, re.IGNORECASE)
            if match:
                parsed_data["price"] = match.group(1).strip()
                parsed_data["price_label"] = "成交价格"
                break

        current_price_match = re.search(r"(当前价格|现价|最新价)[:：]\s*([^\s,，]+)", clean_message, re.IGNORECASE)
        if current_price_match:
            parsed_data["current_price"] = current_price_match.group(2).strip()
            if not parsed_data["price"] or parsed_data["price"] == "N/A":
                parsed_data["price"] = parsed_data["current_price"]
                parsed_data["price_label"] = "当前价格"

        stop_loss_match = re.search(r"(止损价格|止损|stop\s*loss)[:：]\s*([^\s,，]+)", clean_message, re.IGNORECASE)
        if stop_loss_match:
            parsed_data["stop_loss_price"] = stop_loss_match.group(2).strip()

        take_profit_match = re.search(r"(止盈价格|止盈|take\s*profit)[:：]\s*([^\s,，]+)", clean_message, re.IGNORECASE)
        if take_profit_match:
            parsed_data["take_profit_price"] = take_profit_match.group(2).strip()

        strength_patterns = [
            r"信号强度[:：]\s*([^\s，,。]+)",
            r"强度[:：]\s*([^\s，,。]+)",
            r"强度\s*([^\s，,。]+)",
        ]
        for pattern in strength_patterns:
            match = re.search(pattern, clean_message, re.IGNORECASE)
            if match:
                parsed_data["signal_strength"] = f"{match.group(1)}"
                break

        if parsed_data["action"] == "" or parsed_data["signal"] in ("", "信号"):
            inferred = self.infer_action_from_text(clean_message)
            if inferred:
                parsed_data["signal"] = inferred
                parsed_data["action"] = inferred

        return parsed_data

    def update_buy_signal_counter(self, strategy: str, signal_type: str) -> str:
        is_buy = "buy" in (signal_type or "").lower() or ("买入" in (signal_type or ""))
        is_sell = (
            ("sell" in (signal_type or "").lower())
            or ("卖出" in (signal_type or ""))
            or ("清空" in (signal_type or ""))
            or ("平仓" in (signal_type or ""))
            or ("close" in (signal_type or "").lower())
            or ("exit" in (signal_type or "").lower())
        )
        target_strategy = "eth 双买点趋势"
        if strategy == target_strategy:
            if is_buy:
                current_count = self.buy_signal_counter.get(strategy, 0)
                if current_count < 2:
                    current_count += 1
                    self.buy_signal_counter[strategy] = current_count
                return "第一次买入" if current_count == 1 else "第二次买入"
            if is_sell:
                self.buy_signal_counter[strategy] = 0
                if ("清空" in signal_type) or ("平仓" in signal_type) or ("close" in (signal_type or "").lower()) or ("exit" in (signal_type or "").lower()):
                    return "清空"
                return "卖出"
        return signal_type

    def format_signal_message(self, signal_data):
        if isinstance(signal_data, str):
            signal_data = self.parse_tradingview_message(signal_data)
        symbol = signal_data.get("symbol", "未知品种")
        signal_type = signal_data.get("signal", "")
        strategy = signal_data.get("strategy", "未知策略")
        timeframe = signal_data.get("timeframe", "")
        price = signal_data.get("price", "N/A")
        current_price = signal_data.get("current_price", "N/A")
        stop_loss_price = signal_data.get("stop_loss_price", "")
        take_profit_price = signal_data.get("take_profit_price", "")
        position_size = signal_data.get("position_size", "")
        signal_strength = signal_data.get("signal_strength", "N/A")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        action_display = self.update_buy_signal_counter(strategy, signal_type)
        if ("清空" in signal_type) or ("平仓" in signal_type) or ("清空" in action_display) or ("平仓" in action_display):
            emoji = "⚪"
        elif ("buy" in (signal_type or "").lower()) or ("买入" in signal_type) or ("买入" in action_display):
            emoji = "🟢"
        elif ("sell" in (signal_type or "").lower()) or ("卖出" in signal_type) or ("卖出" in action_display):
            emoji = "🔴"
        else:
            emoji = "🔔"

        message_lines = [
            "",
            f"**交易品种**: {symbol}",
            f"**信号类型**: {action_display} {emoji}",
        ]
        if price and price != "N/A":
            price_label = signal_data.get("price_label") or "成交价格"
            message_lines.append(f"**{price_label}**: {price}")
        if current_price and current_price != "N/A" and (signal_data.get("price_label") != "当前价格"):
            message_lines.append(f"**当前价格**: {current_price}")
        if stop_loss_price:
            message_lines.append(f"**止损价格**: {stop_loss_price}")
        if take_profit_price:
            message_lines.append(f"**止盈价格**: {take_profit_price}")
        if position_size:
            message_lines.append(f"**仓位**: {position_size}")
        message_lines.append(f"**策略名称**: {strategy}")
        if timeframe:
            message_lines.append(f"**周期**: {timeframe}")
        if signal_strength != "N/A":
            message_lines.append(f"**信号强度**: {signal_strength}")
        message_lines.append(f"**触发时间**: {current_time}")
        return "\n\n".join(message_lines)

    def send_to_dingtalk(self, signal_data) -> bool:
        try:
            message = self.format_signal_message(signal_data)
            msg_id = signal_data.get("id")
            webhook_url = self.config["id_webhook_map"].get(msg_id)
            if not webhook_url:
                print(f"⚠️  未找到ID '{msg_id}' 对应的webhook，使用策略名匹配")
                strategy_str = str(signal_data.get("strategy") or "")
                webhook_url = self.config.get("dingtalk_webhook") or next(iter(self.config["id_webhook_map"].values()), None)
                if "ETH做空策略" in strategy_str:
                    webhook_url = self.config.get("dingtalk_webhook_eth_short", webhook_url)
                elif "山寨做空策略" in strategy_str:
                    webhook_url = self.config.get("dingtalk_webhook_eth_short", webhook_url)
                elif "山寨做多策略" in strategy_str:
                    webhook_url = self.config.get("dingtalk_webhook_altcoin", webhook_url)
                else:
                    btc_prefix_1 = "BTC 2小时中性短线 - 强度90开仓版 (优化)"
                    btc_prefix_2 = "BTC 2小时中性短线"
                    if strategy_str.startswith(btc_prefix_1) or strategy_str.startswith(btc_prefix_2):
                        webhook_url = self.config.get("dingtalk_webhook_btc_2h", webhook_url)
            if not webhook_url:
                print("❌ 没有配置任何webhook")
                return False

            dingtalk_msg = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"{signal_data.get('strategy', signal_data.get('symbol', '交易'))}信号",
                    "text": message,
                },
                "at": {"atMobiles": [], "isAtAll": False},
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(webhook_url, headers=headers, data=json.dumps(dingtalk_msg), timeout=10)
            result = response.json()
            if result.get("errcode") == 0:
                print(f"✅ 信号发送成功: {signal_data.get('symbol', '未知')}")
                return True
            print(f"❌ 钉钉发送失败: {result.get('errmsg')}")
            return False
        except Exception as e:
            print(f"❌ 发送失败: {str(e)}")
            return False


def main() -> None:
    print("=" * 60)
    print("🚀 TradingView钉钉推送机器人（含实盘交易评分旁路）")
    print("=" * 60)

    install_requirements()
    print("\n🔍 检查端口可用性...")
    if not check_port_available(CONFIG["preferred_port"]):
        kill_process_on_port(CONFIG["preferred_port"])
    port = get_available_port()
    CONFIG["port"] = port
    print(f"✅ 使用端口: {port}")

    app = Flask(__name__)
    bot = TradingViewBot(CONFIG)

    def _get_filter_id(raw: dict, parsed: dict) -> str:
        return str(
            raw.get("筛选ID")
            or raw.get("ID")
            or raw.get("id")
            or parsed.get("id")
            or parsed.get("alert_id")
            or ""
        ).strip()

    def _should_score_live_trade(raw: dict, parsed: dict) -> bool:
        fid = _get_filter_id(raw, parsed)
        return fid == "实盘交易" or fid.lower() == "live_trade"

    def _action_to_buy_sell(sig: str) -> str:
        s = (sig or "").strip().lower()
        if (s in ("buy", "long")) or ("买" in (sig or "")) or ("buy" in s):
            return "buy"
        if (s in ("sell", "short")) or ("卖" in (sig or "")) or ("sell" in s):
            return "sell"
        return ""

    def _score_and_push_live_trade(raw: dict, parsed: dict) -> None:
        try:
            from backpack_quant_trading.core.crypto_signal_scorer import run_signal_score, format_dingtalk_message
            from backpack_quant_trading.core.stock_news_alert import send_dingtalk_text

            symbol = (parsed.get("symbol") or raw.get("交易品种") or raw.get("symbol") or raw.get("coin") or "").strip()
            # 周期优先级：信号字段 > K线级别字段 > 文本解析出的周期
            tf_raw = (raw.get("周期") or raw.get("K线级别") or raw.get("timeframe") or parsed.get("timeframe") or "").strip()
            timeframe = _normalize_tv_timeframe(tf_raw) or ""
            action = _action_to_buy_sell(parsed.get("signal") or parsed.get("action") or raw.get("方向") or raw.get("action") or "")
            if not symbol or not action:
                print(f"⚠️ 实盘交易评分跳过：symbol/action 缺失 symbol={symbol} action={action}")
                return

            strategy_label = str(parsed.get("strategy") or raw.get("策略名称") or raw.get("strategy_name") or "live_trade")
            res = run_signal_score(
                symbol,
                action,
                timeframe=timeframe,
                webhook_raw=raw,
                strategy_label=strategy_label,
            )
            if not res.get("ok"):
                print(f"❌ 实盘交易评分失败: {res.get('error')}")
                return

            webhook_url = CONFIG["live_trade_score_webhook"]
            body = format_dingtalk_message(
                res.get("symbol") or symbol,
                res.get("action") or action,
                res.get("snapshot") or {},
                res.get("deepseek") or {},
                timeframe=res.get("timeframe") or timeframe,
            )
            ok, msg = send_dingtalk_text(webhook_url, body)
            if ok:
                print("✅ 实盘交易评分已推送钉钉")
            else:
                print(f"❌ 实盘交易评分钉钉发送失败: {msg}")
        except Exception as e:
            print(f"❌ 实盘交易评分线程异常: {e}")

    @app.route("/webhook", methods=["POST"])
    def webhook_handler():
        try:
            raw_bytes = request.get_data()
            raw_data = _decode_request_body(raw_bytes)

            try:
                data = json.loads(raw_data)
                if isinstance(data, dict):
                    signal_data = data
                else:
                    signal_data = {"raw_message": str(data)}
            except json.JSONDecodeError:
                signal_data = {"raw_message": raw_data}

            parsed_data = bot.parse_tradingview_message(signal_data)

            # 新增旁路：仅实盘交易触发评分推送（后台线程，不阻塞）
            if isinstance(signal_data, dict) and _should_score_live_trade(signal_data, parsed_data):
                threading.Thread(
                    target=_score_and_push_live_trade,
                    args=(signal_data, parsed_data),
                    daemon=True,
                ).start()

            # 原有逻辑：照常推送信号卡片
            success = bot.send_to_dingtalk(parsed_data)
            if success:
                return jsonify({"status": "success", "message": "信号已发送", "data": parsed_data}), 200
            return jsonify({"status": "error", "message": "发送失败", "data": parsed_data}), 500
        except Exception as e:
            error_msg = f"处理Webhook时出错: {str(e)}"
            print(f"❌ {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 500

    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify(
            {
                "status": "running",
                "service": "TradingView钉钉推送机器人（含实盘交易评分旁路）",
                "port": port,
                "timestamp": datetime.now().isoformat(),
            }
        )

    @app.route("/")
    def index():
        return f"""
        <html>
        <head><title>TradingView钉钉推送机器人</title></head>
        <body>
            <h1>✅ 机器人运行正常</h1>
            <p>服务状态: 运行中</p>
            <p>端口: {port}</p>
            <p>Webhook地址: /webhook</p>
            <p>健康检查: /health</p>
            <p><a href="/health">点击查看服务状态</a></p>
        </body>
        </html>
        """

    print("\n" + "=" * 60)
    print("📡 服务地址:")
    print(f"   本地地址: http://localhost:{port}")
    print(f"   Webhook: POST http://localhost:{port}/webhook")
    print(f"   健康检查: GET http://localhost:{port}/health")
    print("=" * 60)
    print("\n🎉 启动服务器... (按 Ctrl+C 停止)")

    app.run(host="0.0.0.0", port=port, debug=CONFIG["debug"], use_reloader=False)


if __name__ == "__main__":
    main()


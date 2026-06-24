#!/usr/bin/env python3
"""
钉钉 Stream 机器人：群内「回复信号 + @机器人 + 评分」→ 拉 K 线 → DeepSeek 评分 → 群内回复。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from backpack_quant_trading.core.env_loader import load_project_env

    load_project_env()
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dingtalk_score_bot")


def _allowed_sender(sender_staff_id: str, sender_id: str) -> bool:
    raw = os.getenv("DINGTALK_MANUAL_SCORE_ALLOWED_STAFF_IDS", "").strip()
    if not raw:
        return True
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return (sender_staff_id or "") in allowed or (sender_id or "") in allowed


def _user_text(incoming, raw: dict) -> str:
    from backpack_quant_trading.core.dingtalk_manual_score import extract_user_text_from_raw

    text = extract_user_text_from_raw(raw)
    if text:
        return text
    try:
        parts = incoming.get_text_list()
        if parts:
            return " ".join(str(p) for p in parts if p).strip()
    except Exception:
        pass
    if getattr(incoming, "text", None) and getattr(incoming.text, "content", None):
        return str(incoming.text.content).strip()
    return ""


class ManualScoreBotHandler:
    def __init__(self, handler: "dingtalk_stream.ChatbotHandler"):
        self._handler = handler

    def _work(self, incoming, raw: dict, parsed: dict, user_text: str) -> None:
        from backpack_quant_trading.core.dingtalk_manual_score import score_manual_parsed

        sender_staff = str(raw.get("senderStaffId") or getattr(incoming, "sender_staff_id", "") or "")
        sender_id = str(raw.get("senderId") or getattr(incoming, "sender_id", "") or "")

        logger.info(
            "[钉钉手动评分] 执行 source=%s symbol=%s action=%s tf=%s user_text=%s",
            parsed.get("resolve_source"),
            parsed.get("symbol"),
            parsed.get("action"),
            parsed.get("timeframe"),
            user_text[:120],
        )

        if not _allowed_sender(sender_staff, sender_id):
            self._handler.reply_text("无手动评分权限，请联系管理员配置白名单。", incoming)
            return

        try:
            reply_body, result = score_manual_parsed(parsed, sender_id=sender_staff or sender_id)
        except Exception as exc:
            logger.exception("[钉钉手动评分] 评分线程异常: %s", exc)
            try:
                self._handler.reply_text(f"评分异常：{exc}", incoming)
            except Exception:
                pass
            return

        try:
            if result and result.get("reply_markdown"):
                title = str(result.get("reply_title") or "AI 信号评分")
                self._handler.reply_markdown(title, reply_body, incoming)
            else:
                self._handler.reply_text(reply_body, incoming)
        except Exception as exc:
            logger.exception("钉钉回复失败: %s", exc)
            try:
                self._handler.reply_text(f"评分结果发送失败：{exc}", incoming)
            except Exception:
                pass

    def handle(self, incoming, raw: dict) -> None:
        from backpack_quant_trading.core.dingtalk_manual_score import (
            is_manual_score_command,
            resolve_signal_for_scoring,
            _summarize_replied_msg,
        )

        user_text = _user_text(incoming, raw)
        logger.info("[钉钉手动评分] 入站 text=%s isReply=%s", user_text[:160], raw.get("text"))

        if not is_manual_score_command(user_text):
            try:
                self._handler.reply_text(
                    "可以说：@我 评一下分 / 对 ETH 2h 买入 评分",
                    incoming,
                )
            except Exception:
                pass
            return

        parsed, hint = resolve_signal_for_scoring(user_text, raw)
        if not parsed or not parsed.get("symbol"):
            from backpack_quant_trading.core.dingtalk_signal_cache import (
                cache_signal_count,
                get_latest_cached_signal,
            )

            latest = get_latest_cached_signal(max_age_sec=7200)
            cache_n = cache_signal_count(max_age_sec=7200)
            quoted_body = ""
            text_block = raw.get("text")
            if isinstance(text_block, dict) and text_block.get("repliedMsg"):
                quoted_body = (_summarize_replied_msg(text_block["repliedMsg"]) or "")[:200]
            logger.warning(
                "[钉钉手动评分] 解析失败 text=%s hint=%s cache_n=%s latest=%s quoted=%s raw=%s",
                user_text,
                hint,
                cache_n,
                (latest or {}).get("symbol"),
                quoted_body,
                json.dumps(raw.get("text"), ensure_ascii=False)[:800],
            )
            try:
                if hint.startswith("ambiguous:"):
                    syms = hint.split(":", 1)[1].replace(",", "、")
                    tip = (
                        f"最近有多条相同策略的信号（{syms}），无法确定评哪条。\n"
                        f"请写明品种，例如：@我 对 BTC 8h 卖出 评分"
                    )
                elif cache_n > 1:
                    tip = (
                        "最近有多条信号缓存，不能自动用「最新一条」。\n"
                        "请回复要评的那条信号，或写：@我 对 BTC 8h 卖出 评分"
                    )
                elif latest and latest.get("symbol"):
                    tip = (
                        "钉钉未传回信号正文（界面上能看到，API 里往往只有标题）。\n"
                        "请直接写：@我 对 BTC 8h 卖出 评分"
                    )
                else:
                    tip = (
                        "钉钉未传回信号正文，且服务器缓存里没有最近推送（需 tradingview_bot 推成功）。\n"
                        "请直接写：@我 对 BTC 8h 卖出 评分"
                    )
                self._handler.reply_text(tip, incoming)
            except Exception:
                pass
            return

        threading.Thread(
            target=self._work,
            args=(incoming, raw, parsed, user_text),
            daemon=True,
            name="dingtalk-manual-score",
        ).start()

        sym = parsed.get("symbol") or "?"
        tf = parsed.get("timeframe") or "默认周期"
        role = parsed.get("signal_role") or (
            "做多开仓" if (parsed.get("action") or "buy") == "buy" else "做空开仓"
        )
        try:
            self._handler.reply_text(
                f"好的，正在评 {sym} {tf} {role}，请稍候…",
                incoming,
            )
        except Exception as exc:
            logger.warning("即时确认回复失败: %s", exc)


def _build_handler(logger_obj: logging.Logger):
    import dingtalk_stream
    from dingtalk_stream import AckMessage

    class _Handler(dingtalk_stream.ChatbotHandler):
        def __init__(self):
            super().__init__()
            self.logger = logger_obj
            self._manual = ManualScoreBotHandler(self)

        def _dispatch(self, callback: dingtalk_stream.CallbackMessage):
            raw = callback.data
            if isinstance(raw, str):
                raw = json.loads(raw)
            incoming = dingtalk_stream.ChatbotMessage.from_dict(raw)
            if not incoming.is_in_at_list:
                return AckMessage.STATUS_OK, "not_at"
            self._manual.handle(incoming, raw)
            return AckMessage.STATUS_OK, "OK"

        async def process(self, callback: dingtalk_stream.CallbackMessage):
            return self._dispatch(callback)

    return _Handler()


def main() -> None:
    from backpack_quant_trading.core.dingtalk_manual_score import manual_dingtalk_score_enabled

    if not manual_dingtalk_score_enabled():
        logger.error("DINGTALK_MANUAL_SCORE_ENABLED=0，已退出")
        sys.exit(1)

    client_id = os.getenv("DINGTALK_SCORE_BOT_CLIENT_ID", "").strip()
    client_secret = os.getenv("DINGTALK_SCORE_BOT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.error("缺少 DINGTALK_SCORE_BOT_CLIENT_ID / DINGTALK_SCORE_BOT_CLIENT_SECRET")
        sys.exit(1)

    try:
        import dingtalk_stream
    except ImportError:
        logger.error("请安装 dingtalk-stream: pip install dingtalk-stream")
        sys.exit(1)

    try:
        import logging as _log
        from backpack_quant_trading.config.settings import config
        from backpack_quant_trading.utils.logger import setup_logger
        from backpack_quant_trading.core.crypto_signal_scorer import log_score_runtime_config

        setup_logger(log_dir=config.log_dir, level=_log.INFO)
        log_score_runtime_config()
    except Exception as exc:
        logger.warning("评分日志初始化失败(继续): %s", exc)

    credential = dingtalk_stream.Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        _build_handler(logger),
    )
    logger.info("钉钉手动评分 Stream 机器人启动 client_id=%s…", client_id[:8])
    client.start_forever()


if __name__ == "__main__":
    main()

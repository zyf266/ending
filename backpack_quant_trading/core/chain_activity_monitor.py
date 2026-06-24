"""链上活跃度监控：ETH / Arbitrum / BSC，每 15 分钟对比前后窗口交易活跃度，超阈值钉钉推送。"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SEC = 15 * 60
DEFAULT_ACTIVITY_MULT = 10.0
MIN_BASELINE_TX = 50

CHAIN_ACTIVITY_WEBHOOK = os.getenv(
    "CHAIN_ACTIVITY_WEBHOOK",
    "https://oapi.dingtalk.com/robot/send?access_token=3bedccd203d2ed11882431c3250ed31af4090591fdb6a87aaf04f8953fdbc1dc",
)

_CHAIN_ENV_KEYS = {"eth": "ETH_RPC_URL", "arb": "ARB_RPC_URL", "bsc": "BSC_RPC_URL"}

_CHAIN_RPC_DEFAULTS: Dict[str, List[str]] = {
    "eth": [
        "https://rpc.ankr.com/eth",
        "https://ethereum.publicnode.com",
        "https://eth.llamarpc.com",
        "https://1rpc.io/eth",
    ],
    "arb": [
        "https://rpc.ankr.com/arbitrum",
        "https://arbitrum-one.publicnode.com",
        "https://arb1.arbitrum.io/rpc",
    ],
    "bsc": [
        "https://bsc-dataseed1.binance.org",
        "https://bsc-dataseed2.binance.org",
        "https://rpc.ankr.com/bsc",
    ],
}

CHAIN_DEFS: Dict[str, Dict[str, Any]] = {
    "eth": {"name": "Ethereum", "avg_block_sec": 12.0},
    "arb": {"name": "Arbitrum", "avg_block_sec": 0.25},
    "bsc": {"name": "BSC", "avg_block_sec": 3.0},
}


def rpc_urls_for_chain(chain_id: str) -> List[str]:
    cid = str(chain_id or "").lower().strip()
    urls: List[str] = []
    env_key = _CHAIN_ENV_KEYS.get(cid)
    if env_key:
        custom = os.getenv(env_key, "").strip()
        if custom:
            urls.append(custom)
    for u in _CHAIN_RPC_DEFAULTS.get(cid, []):
        if u not in urls:
            urls.append(u)
    return urls


def get_chain_rpc_info() -> Dict[str, Any]:
    """返回各链 RPC 配置说明（供前端/用户排查）。"""
    out: Dict[str, Any] = {}
    for cid, meta in CHAIN_DEFS.items():
        env_key = _CHAIN_ENV_KEYS.get(cid, "")
        custom = os.getenv(env_key, "").strip() if env_key else ""
        out[cid] = {
            "name": meta["name"],
            "env_var": env_key,
            "custom_rpc": custom or None,
            "default_rpcs": _CHAIN_RPC_DEFAULTS.get(cid, []),
            "active_order": rpc_urls_for_chain(cid),
        }
    return out


def _requests_proxies() -> Optional[Dict[str, str]]:
    https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or https
    if not (http or https):
        return None
    p: Dict[str, str] = {}
    if http:
        p["http"] = http
    if https:
        p["https"] = https
    return p or None


def _rpc_call_url(rpc_url: str, method: str, params: list, *, timeout: int = 20) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(
        rpc_url,
        json=payload,
        timeout=timeout,
        proxies=_requests_proxies(),
        headers={"Content-Type": "application/json"},
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        err = data["error"]
        if isinstance(err, dict):
            raise RuntimeError(err.get("message") or str(err))
        raise RuntimeError(str(err))
    return data.get("result")


def _rpc_call_chain(chain_id: str, method: str, params: list, *, timeout: int = 20) -> Tuple[Any, str]:
    last_err: Optional[Exception] = None
    for url in rpc_urls_for_chain(chain_id):
        try:
            return _rpc_call_url(url, method, params, timeout=timeout), url
        except Exception as exc:
            last_err = exc
            logger.debug("RPC 失败 %s %s: %s", chain_id, url, exc)
    raise RuntimeError(f"{CHAIN_DEFS[chain_id]['name']} 所有 RPC 节点均不可用: {last_err}")


def _rpc_call(rpc_url: str, method: str, params: list) -> Any:
    """兼容旧调用：按 URL 直连（无 fallback）。"""
    return _rpc_call_url(rpc_url, method, params)


def _hex_to_int(val: Any) -> int:
    if isinstance(val, int):
        return val
    s = str(val or "0")
    return int(s, 16) if s.startswith("0x") else int(s)


def _get_latest_block(chain_id: str) -> Tuple[int, int, int, str]:
    num_hex, rpc = _rpc_call_chain(chain_id, "eth_blockNumber", [])
    block_num = _hex_to_int(num_hex)
    block, rpc2 = _rpc_call_chain(chain_id, "eth_getBlockByNumber", [hex(block_num), False])
    if not block:
        raise RuntimeError("无法获取最新区块")
    ts = _hex_to_int(block.get("timestamp"))
    tx_count = len(block.get("transactions") or [])
    return block_num, ts, tx_count, rpc2 or rpc


def _get_block_meta(chain_id: str, block_num: int) -> Tuple[int, int]:
    block, _ = _rpc_call_chain(chain_id, "eth_getBlockByNumber", [hex(block_num), False])
    if not block:
        raise RuntimeError(f"区块 {block_num} 不存在")
    ts = _hex_to_int(block.get("timestamp"))
    tx_count = len(block.get("transactions") or [])
    return ts, tx_count


def _find_block_at_or_before(chain_id: str, target_ts: int, hi: int) -> int:
    lo = max(0, hi - 500_000)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        ts, _ = _get_block_meta(chain_id, mid)
        if ts <= target_ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


@dataclass
class ChainActivitySnapshot:
    chain_id: str
    chain_name: str
    tx_count: int
    native_transfers: int
    contract_calls: int
    block_from: int
    block_to: int
    window_start_ts: int
    window_end_ts: int
    sampled: bool = False


def _sample_block_detail(chain_id: str, block_num: int) -> Tuple[int, int, int]:
    block, _ = _rpc_call_chain(chain_id, "eth_getBlockByNumber", [hex(block_num), True], timeout=25)
    if not block:
        return 0, 0, 0
    txs = block.get("transactions") or []
    native = 0
    calls = 0
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        val = _hex_to_int(tx.get("value"))
        inp = str(tx.get("input") or "0x")
        if val > 0:
            native += 1
        if inp not in ("0x", "0X", ""):
            calls += 1
    return len(txs), native, calls


def measure_chain_activity(
    chain_id: str,
    window_sec: int = CHECK_INTERVAL_SEC,
) -> ChainActivitySnapshot:
    cfg = CHAIN_DEFS[chain_id]
    latest_num, latest_ts, _, _ = _get_latest_block(chain_id)
    end_ts = latest_ts
    start_ts = end_ts - window_sec
    end_block = latest_num
    start_block = _find_block_at_or_before(chain_id, start_ts, end_block)
    block_span = max(0, end_block - start_block + 1)

    total_tx = 0
    total_native = 0
    total_calls = 0
    sampled = False

    if block_span <= 0:
        return ChainActivitySnapshot(
            chain_id=chain_id,
            chain_name=cfg["name"],
            tx_count=0,
            native_transfers=0,
            contract_calls=0,
            block_from=start_block,
            block_to=end_block,
            window_start_ts=start_ts,
            window_end_ts=end_ts,
        )

    if block_span <= 60:
        for b in range(start_block, end_block + 1):
            _, tx = _get_block_meta(chain_id, b)
            total_tx += tx
        detail_blocks = list(range(start_block, end_block + 1, max(1, block_span // 5 or 1)))[:5]
        for b in detail_blocks:
            _, nat, call = _sample_block_detail(chain_id, b)
            total_native += nat
            total_calls += call
        if detail_blocks:
            scale = block_span / len(detail_blocks)
            total_native = int(total_native * scale)
            total_calls = int(total_calls * scale)
    else:
        sampled = True
        step = max(1, block_span // 40)
        samples_tx: List[int] = []
        detail_blocks: List[int] = []
        for b in range(start_block, end_block + 1, step):
            _, tx = _get_block_meta(chain_id, b)
            samples_tx.append(tx)
            if len(detail_blocks) < 8:
                detail_blocks.append(b)
        avg_tx = sum(samples_tx) / len(samples_tx) if samples_tx else 0
        total_tx = int(avg_tx * block_span)
        for b in detail_blocks:
            _, nat, call = _sample_block_detail(chain_id, b)
            total_native += nat
            total_calls += call
        if detail_blocks:
            scale = block_span / len(detail_blocks)
            total_native = int(total_native * scale)
            total_calls = int(total_calls * scale)

    return ChainActivitySnapshot(
        chain_id=chain_id,
        chain_name=cfg["name"],
        tx_count=total_tx,
        native_transfers=total_native,
        contract_calls=total_calls,
        block_from=start_block,
        block_to=end_block,
        window_start_ts=start_ts,
        window_end_ts=end_ts,
        sampled=sampled,
    )


def send_chain_activity_dingtalk(chain_id: str, title: str, body: str) -> bool:
    webhook = (CHAIN_ACTIVITY_WEBHOOK or "").strip()
    if not webhook:
        logger.warning("链上活跃度钉钉跳过：未配置 CHAIN_ACTIVITY_WEBHOOK")
        return False
    try:
        content = (
            f"\n【链上活跃度】{title}\n"
            f"链: {CHAIN_DEFS.get(chain_id, {}).get('name', chain_id)}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{body}"
        )
        data = {"msgtype": "text", "text": {"content": content}}
        resp = requests.post(webhook, json=data, timeout=8)
        if resp.status_code == 200:
            logger.info("链上活跃度钉钉已发送: %s", chain_id)
            return True
        logger.error("链上活跃度钉钉失败: %s", resp.text)
        return False
    except Exception as exc:
        logger.error("链上活跃度钉钉异常: %s", exc)
        return False


class ChainActivityMonitorService:
    """每 15 分钟检测各链交易活跃度，当前窗口 ≥ 上一窗口 × 倍数时推送。"""

    def __init__(
        self,
        chains: List[str],
        *,
        activity_mult_threshold: float = DEFAULT_ACTIVITY_MULT,
        check_interval_sec: int = CHECK_INTERVAL_SEC,
        cooldown_sec: int = CHECK_INTERVAL_SEC,
    ):
        self.chains = [c.lower() for c in chains if c.lower() in CHAIN_DEFS]
        self.activity_mult_threshold = float(activity_mult_threshold)
        self.check_interval_sec = int(check_interval_sec)
        self.cooldown_sec = int(cooldown_sec)
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._prev_snapshots: Dict[str, ChainActivitySnapshot] = {}
        self._last_alert_ts: Dict[str, float] = {}
        self._last_check_summary: Dict[str, Any] = {}

    def get_status_summary(self) -> Dict[str, Any]:
        return {
            "chains": self.chains,
            "activity_mult_threshold": self.activity_mult_threshold,
            "check_interval_sec": self.check_interval_sec,
            "last_check": self._last_check_summary,
        }

    def _cooldown_ok(self, chain_id: str) -> bool:
        now = time.time()
        last = self._last_alert_ts.get(chain_id, 0)
        if now - last >= self.cooldown_sec:
            self._last_alert_ts[chain_id] = now
            return True
        return False

    def _check_chain(self, chain_id: str) -> None:
        cur = measure_chain_activity(chain_id, window_sec=self.check_interval_sec)
        prev = self._prev_snapshots.get(chain_id)
        self._prev_snapshots[chain_id] = cur

        ratio = None
        triggered = False
        if prev and prev.tx_count >= MIN_BASELINE_TX:
            ratio = cur.tx_count / prev.tx_count if prev.tx_count > 0 else 0
            if ratio >= self.activity_mult_threshold and self._cooldown_ok(chain_id):
                triggered = True
                body = (
                    f"当前15分钟活跃度: {cur.tx_count:,} 笔交易\n"
                    f"上一15分钟: {prev.tx_count:,} 笔\n"
                    f"倍数: {ratio:.1f}x ≥ {self.activity_mult_threshold:.0f}x\n"
                    f"原生转账(估): {cur.native_transfers:,} | 合约调用(估): {cur.contract_calls:,}\n"
                    f"区块范围: {cur.block_from} → {cur.block_to}"
                    + (" (采样估算)" if cur.sampled else "")
                )
                send_chain_activity_dingtalk(
                    chain_id,
                    f"{cur.chain_name} 链上活跃度暴增",
                    body,
                )

        self._last_check_summary[chain_id] = {
            "tx_count": cur.tx_count,
            "prev_tx_count": prev.tx_count if prev else None,
            "ratio": round(ratio, 2) if ratio is not None else None,
            "native_transfers": cur.native_transfers,
            "contract_calls": cur.contract_calls,
            "triggered": triggered,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        logger.info(
            "[链上活跃度] %s tx=%s prev=%s ratio=%s triggered=%s",
            chain_id,
            cur.tx_count,
            prev.tx_count if prev else "—",
            f"{ratio:.1f}x" if ratio is not None else "—",
            triggered,
        )

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                for chain_id in self.chains:
                    if self._stop_event.is_set():
                        break
                    try:
                        self._check_chain(chain_id)
                    except Exception as exc:
                        logger.error("链上活跃度检测失败 %s: %s", chain_id, exc)
                        self._last_check_summary[chain_id] = {
                            "error": str(exc),
                            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
            except Exception as exc:
                logger.error("链上活跃度循环异常: %s", exc)

            now = time.time()
            sleep_s = self.check_interval_sec - (now % self.check_interval_sec)
            if sleep_s < 5:
                sleep_s += self.check_interval_sec
            self._stop_event.wait(sleep_s)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="chain-activity")
        self._thread.start()
        logger.info("✅ 链上活跃度监控已启动: %s", self.chains)

    def check_now(self) -> Dict[str, Any]:
        """立即执行一轮检测（不等待定时），返回各链结果。"""
        out: Dict[str, Any] = {}
        for chain_id in self.chains:
            try:
                self._check_chain(chain_id)
                out[chain_id] = dict(self._last_check_summary.get(chain_id) or {})
            except Exception as exc:
                out[chain_id] = {"error": str(exc)}
        return out

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        logger.info("🛑 链上活跃度监控已停止")


_chain_activity_instance: Optional[ChainActivityMonitorService] = None


def get_chain_activity_instance() -> Optional[ChainActivityMonitorService]:
    return _chain_activity_instance


def set_chain_activity_instance(instance: Optional[ChainActivityMonitorService]) -> None:
    global _chain_activity_instance
    _chain_activity_instance = instance


def list_supported_chains() -> List[Dict[str, str]]:
    return [{"id": k, "name": v["name"]} for k, v in CHAIN_DEFS.items()]


def quick_probe_chain(chain_id: str) -> Dict[str, Any]:
    """轻量 RPC 探测：仅 2 次请求，几秒内完成。"""
    cid = str(chain_id or "").lower().strip()
    if cid not in CHAIN_DEFS:
        return {"ok": False, "chain_id": cid, "error": f"不支持的链: {cid}"}
    cfg = CHAIN_DEFS[cid]
    try:
        block_num, ts, tx_count, rpc = _get_latest_block(cid)
        return {
            "ok": True,
            "chain_id": cid,
            "chain_name": cfg["name"],
            "rpc": rpc,
            "block_number": block_num,
            "block_time_utc": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "tx_in_latest_block": tx_count,
            "mode": "quick",
            "message": "RPC 连通正常（快速探测）",
            "rpc_candidates": rpc_urls_for_chain(cid),
        }
    except Exception as exc:
        return {
            "ok": False,
            "chain_id": cid,
            "chain_name": cfg["name"],
            "error": str(exc),
            "rpc_candidates": rpc_urls_for_chain(cid),
            "env_var": _CHAIN_ENV_KEYS.get(cid),
            "hint": (
                "内置了多个免费公共 RPC，会自动依次尝试。"
                f"若均失败，请注册 Alchemy/Infura 免费节点，设置环境变量 {_CHAIN_ENV_KEYS.get(cid)} 后重启 API。"
                "国内可先开 HTTP_PROXY，或换云服务器部署。"
            ),
        }


def probe_chain_activity(chain_id: str, *, window_sec: int = CHECK_INTERVAL_SEC, deep: bool = False) -> Dict[str, Any]:
    """单次探测：默认快速；deep=True 时做完整 15 分钟窗口统计（较慢）。"""
    cid = str(chain_id or "").lower().strip()
    if not deep:
        return quick_probe_chain(cid)
    if cid not in CHAIN_DEFS:
        return {"ok": False, "chain_id": cid, "error": f"不支持的链: {cid}"}
    cfg = CHAIN_DEFS[cid]
    try:
        snap = measure_chain_activity(cid, window_sec=window_sec)
        return {
            "ok": True,
            "chain_id": cid,
            "chain_name": cfg["name"],
            "rpc_candidates": rpc_urls_for_chain(cid),
            "tx_count": snap.tx_count,
            "native_transfers": snap.native_transfers,
            "contract_calls": snap.contract_calls,
            "block_from": snap.block_from,
            "block_to": snap.block_to,
            "sampled": snap.sampled,
            "window_sec": window_sec,
            "mode": "deep",
            "message": "完整窗口统计完成",
        }
    except Exception as exc:
        logger.warning("链上深度探测失败 %s: %s", cid, exc)
        return {
            "ok": False,
            "chain_id": cid,
            "chain_name": cfg["name"],
            "error": str(exc),
            "rpc_candidates": rpc_urls_for_chain(cid),
            "env_var": _CHAIN_ENV_KEYS.get(cid),
            "hint": f"可设置 {_CHAIN_ENV_KEYS.get(cid)} 为自有 RPC 后重启 API",
        }


def probe_chain_activity_batch(chains: Optional[List[str]] = None, *, deep: bool = False) -> Dict[str, Any]:
    ids = [str(c).lower() for c in (chains or list(CHAIN_DEFS.keys())) if str(c).lower() in CHAIN_DEFS]
    results = {cid: probe_chain_activity(cid, deep=deep) for cid in ids}
    ok_count = sum(1 for r in results.values() if r.get("ok"))
    return {
        "ok": ok_count == len(ids) and len(ids) > 0,
        "total": len(ids),
        "ok_count": ok_count,
        "mode": "deep" if deep else "quick",
        "rpc_info": get_chain_rpc_info(),
        "results": results,
    }


def send_chain_activity_test_dingtalk() -> Tuple[bool, str]:
    ok = send_chain_activity_dingtalk(
        "eth",
        "连通性测试",
        "这是一条链上活跃度监控的测试消息。若收到说明钉钉 Webhook 配置正常。",
    )
    return ok, "已发送测试消息" if ok else "发送失败，请检查 CHAIN_ACTIVITY_WEBHOOK"

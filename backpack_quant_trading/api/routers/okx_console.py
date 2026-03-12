"""
OKX CLI 控制台（供前端页面调用）
 - 后端在本机执行 okx-trade-cli（okx 命令），读取 ~/.okx/config.toml
 - 默认仅开放行情/账户只读能力（market/account 的查询）
 - 交易类命令（spot/swap/option/futures/bot/account transfer 等）默认禁用，需显式开启环境变量
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backpack_quant_trading.api.deps import require_user

router = APIRouter()


def _build_subprocess_env() -> dict:
    """
    让后端在 Windows 下也能找到 npm 全局安装的 okx 命令。
    常见位置：
    - %APPDATA%\\npm（Windows npm -g 默认）
    - npm config get prefix 的返回目录（有时是 Node 安装目录）
    """
    env = dict(os.environ)
    path = env.get("PATH", "")

    def _add(p: str) -> None:
        nonlocal path
        p = (p or "").strip().strip('"')
        if not p:
            return
        parts = [x for x in path.split(os.pathsep) if x]
        if any(x.lower() == p.lower() for x in parts):
            return
        path = f"{p}{os.pathsep}{path}" if path else p

    appdata = env.get("APPDATA") or ""
    if appdata:
        _add(os.path.join(appdata, "npm"))

    npm = shutil.which("npm")
    if npm:
        try:
            cp = subprocess.run([npm, "config", "get", "prefix"], capture_output=True, text=True, timeout=5, shell=False)
            prefix = (cp.stdout or "").strip()
            if prefix:
                _add(prefix)
                _add(os.path.join(prefix, "bin"))
        except Exception:
            pass

    env["PATH"] = path
    return env


def _okx_exists(env: Optional[dict] = None) -> bool:
    return bool(shutil.which("okx", path=(env or os.environ).get("PATH")))


def _resolve_okx_executable(env: Optional[dict] = None) -> Optional[str]:
    """在 Windows 下优先解析到 okx.CMD 的绝对路径，避免 subprocess 对 PATHEXT 的差异。"""
    return shutil.which("okx", path=(env or os.environ).get("PATH"))


class OkxRunRequest(BaseModel):
    command: str = Field(..., description="okx CLI 命令，不含前缀空格，例如: okx market ticker BTC-USDT")
    profile: Optional[str] = Field(None, description="可选：--profile <name>")
    demo: bool = Field(False, description="可选：--demo")
    json: bool = Field(False, description="可选：--json（输出原始 JSON）")


def _tokenize(cmd: str) -> List[str]:
    try:
        return shlex.split(cmd, posix=False)
    except Exception:
        # 兜底：简单按空格切
        return [c for c in (cmd or "").strip().split(" ") if c]


# 允许的模块与动作（尽量只读）
_ALLOW_MODULE_ACTIONS: Dict[str, Optional[set[str]]] = {
    "market": None,  # 允许所有 market 子命令（均为查询）
    "account": {"balance", "asset-balance", "positions", "positions-history", "bills", "fees", "config", "max-size", "max-avail-size", "max-withdrawal", "audit"},
    "config": {"show", "list", "profiles"},  # 若 CLI 不支持这些 action，会在执行时报错；这里仅做限制
    # 交易类模块：默认由 ENABLE_OKX_TRADE 开关控制（见 _validate）
    "swap": {"positions", "orders", "get", "fills", "place", "cancel", "amend", "close", "leverage", "get-leverage", "batch"},
    "spot": {"orders", "get", "fills", "place", "cancel", "amend", "batch"},
    "futures": {"positions", "orders", "get", "fills", "place", "cancel", "amend"},
    "option": {"positions", "orders", "get", "fills", "place", "cancel", "amend", "instruments", "greeks"},
    "bot": None,  # bot 子模块较多，仍需 ENABLE_OKX_TRADE 开启
    "trade": None,  # okx trade order/close 等（CLI 统一交易入口），需 ENABLE_OKX_TRADE
}


def _is_trade_action(tokens: List[str]) -> bool:
    # okx spot/swap/futures/option/bot/trade 都属于交易/资金操作类
    for t in tokens:
        if t in {"spot", "swap", "futures", "option", "bot", "trade"}:
            return True
    # account transfer 属于资金划转
    if len(tokens) >= 3 and tokens[0] == "okx" and tokens[1] == "account" and tokens[2] == "transfer":
        return True
    return False


def _validate(tokens: List[str]) -> None:
    if not tokens or tokens[0].lower() != "okx":
        raise HTTPException(status_code=400, detail="仅支持 okx CLI 命令，例如：okx market ticker BTC-USDT")
    # 允许全局参数出现在 module 之前，例如：
    # okx --demo market ticker BTC-USDT
    # okx --profile live --json market ticker BTC-USDT
    if len(tokens) < 3:
        raise HTTPException(status_code=400, detail="命令不完整：至少需要 okx <module> <action>")

    idx = 1
    while idx < len(tokens) and tokens[idx].startswith("--"):
        idx += 1
    if idx + 1 >= len(tokens):
        raise HTTPException(status_code=400, detail="命令不完整：缺少 <module> <action>")

    module = tokens[idx]
    action = tokens[idx + 1]
    # 是否带 --demo（模拟盘）
    has_demo_flag = any(t == "--demo" for t in tokens[1:idx])
    if module not in _ALLOW_MODULE_ACTIONS:
        raise HTTPException(status_code=403, detail=f"模块未开放：{module}（当前仅开放 market/account）")

    # 交易模块：需要显式开启（但模拟盘 --demo 放行）
    if module in {"spot", "swap", "futures", "option", "bot", "trade"}:
        if (not has_demo_flag) and os.getenv("ENABLE_OKX_TRADE", "").lower() not in {"1", "true", "yes"}:
            raise HTTPException(
                status_code=403,
                detail="交易类命令默认禁用。若确认要在实盘/非模拟盘开启，请在后端环境变量设置 ENABLE_OKX_TRADE=true",
            )

    allow_actions = _ALLOW_MODULE_ACTIONS[module]
    if allow_actions is not None and action not in allow_actions:
        raise HTTPException(status_code=403, detail=f"该操作未开放：{module} {action}")

    # 禁止明显危险参数（避免注入/任意文件访问等）
    blocked = {"&", "|", ";", ">", "<", "&&", "||"}
    if any(tok in blocked for tok in tokens):
        raise HTTPException(status_code=400, detail="命令包含不允许的分隔符")


@router.get("/presets", summary="OKX 控制台快捷命令")
def presets(_: dict = Depends(require_user)):
    return {
        "presets": [
            {"label": "BTC 最新价", "command": "okx market ticker BTC-USDT"},
            {"label": "ETH 最新价", "command": "okx market ticker ETH-USDT"},
            {"label": "BTC 1H K线(200)", "command": "okx market candles BTC-USDT --bar 1H --limit 200"},
            {"label": "资金费率(BTC-SWAP)", "command": "okx market funding-rate BTC-USDT-SWAP"},
            {"label": "账户余额(需Key)", "command": "okx account balance"},
            {"label": "当前持仓(需Key)", "command": "okx account positions"},
        ]
    }


@router.post("/run", summary="执行 OKX CLI（受限白名单）")
def run_okx(req: OkxRunRequest, _: dict = Depends(require_user)) -> Dict[str, Any]:
    tokens = _tokenize(req.command)
    _validate(tokens)

    # 交易能力默认关闭（即使白名单也会被拦截）
    if _is_trade_action(tokens):
        # 带 --demo 视为模拟盘，默认放行
        has_demo_flag = any(t == "--demo" for t in tokens)
        if (not has_demo_flag) and os.getenv("ENABLE_OKX_TRADE", "").lower() not in {"1", "true", "yes"}:
            raise HTTPException(
                status_code=403,
                detail="交易类命令默认禁用。若确认要在实盘/非模拟盘开启，请在后端环境变量设置 ENABLE_OKX_TRADE=true",
            )

    env = _build_subprocess_env()
    okx_bin = _resolve_okx_executable(env) or "okx"
    args = [okx_bin]
    # 模拟盘且未指定 profile 时，使用本机配置的 demo 账户（~/.okx/config.toml [profiles.demo]）
    profile = req.profile if req.profile else ("demo" if req.demo else None)
    if profile:
        args += ["--profile", profile]
    if req.demo:
        args += ["--demo"]
    if req.json:
        args += ["--json"]
    args += tokens[1:]  # 去掉首个 okx

    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="OKX 命令执行超时")
    except FileNotFoundError:
        if not _okx_exists(env):
            raise HTTPException(
                status_code=500,
                detail=(
                    "未找到 okx CLI（后端进程 PATH 中没有 okx）。"
                    "请先执行：npm install -g okx-trade-cli，"
                    "并确保系统 PATH 包含 %APPDATA%\\npm；然后重启后端生效。"
                ),
            )
        raise HTTPException(status_code=500, detail="OKX CLI 启动失败（FileNotFoundError）")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败：{e}")

    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    return {
        "ok": cp.returncode == 0,
        "code": cp.returncode,
        "stdout": out,
        "stderr": err,
        "args": args,
    }


# ---------- 自然语言解析（开多/开空/查行情等） ----------
import re

_SYMBOL_MAP = {"eth": "ETH-USDT-SWAP", "以太": "ETH-USDT-SWAP", "btc": "BTC-USDT-SWAP", "比特": "BTC-USDT-SWAP"}
_DEFAULT_LEVERAGE = 10


class NaturalRequest(BaseModel):
    text: str = Field(..., description="自然语言，例如：帮我在模拟盘以当前价格开空eth，仓位10u")


def _parse_natural(text: str) -> dict:
    """解析自然语言为意图。返回 { type, inst_id?, side?, margin_u?, demo?, query? }"""
    t = (text or "").strip().lower()
    # 交易意图：开空/做空/开多/做多 + 币种 + 仓位?u + 模拟盘?
    m_trade = re.search(
        r"(开空|做空|开多|做多)\s*(?:[\w\s]*?)(eth|以太|btc|比特)?\s*(?:.*?)(?:仓位|保证金)?\s*(\d+)\s*u",
        t,
        re.I,
    )
    if m_trade:
        action, sym, margin = m_trade.group(1), (m_trade.group(2) or "eth").strip(), int(m_trade.group(3) or 10)
        inst = _SYMBOL_MAP.get(sym.lower(), "ETH-USDT-SWAP")
        demo = "模拟盘" in t or "demo" in t
        return {
            "type": "swap_open",
            "inst_id": inst,
            "side": "sell" if action in ("开空", "做空") else "buy",
            "pos_side": "short" if action in ("开空", "做空") else "long",
            "margin_u": min(margin, 10000),
            "demo": demo,
        }

    # 查行情：价格/行情/多少 + 币种
    m_price = re.search(r"(?:查|看|当前|最新)?\s*(?:价格|行情|多少钱)?\s*(eth|以太|btc|比特)", t)
    if m_price or "价格" in t or "行情" in t:
        sym = "eth"
        for k in ("btc", "比特", "eth", "以太"):
            if k in t:
                sym = "btc" if k in ("btc", "比特") else "eth"
                break
        inst_spot = "BTC-USDT" if sym == "btc" else "ETH-USDT"
        return {"type": "market_ticker", "inst_id": inst_spot}

    # 账户余额/持仓
    if "余额" in t or "账户" in t:
        return {"type": "account_balance"}
    if "持仓" in t or "仓位" in t:
        return {"type": "account_positions"}

    return {"type": "unknown", "raw": text}


def _run_okx_raw(args: list, timeout: int = 25) -> dict:
    try:
        env = _build_subprocess_env()
        if args and str(args[0]).lower() == "okx":
            args = [_resolve_okx_executable(env) or "okx", *args[1:]]
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            env=env,
        )
        return {"ok": cp.returncode == 0, "stdout": (cp.stdout or "").strip(), "stderr": (cp.stderr or "").strip()}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}


@router.post("/natural", summary="自然语言执行（开多/开空/查行情等）")
def run_natural(req: NaturalRequest, _: dict = Depends(require_user)) -> Dict[str, Any]:
    intent = _parse_natural(req.text)
    if intent.get("type") == "unknown":
        return {
            "ok": False,
            "intent": intent,
            "command": None,
            "result": None,
            "message": "未识别到操作意图。可尝试：查一下 ETH 价格 / 模拟盘开空 ETH 仓位 10U / 账户余额",
        }

    # 只读类：直接执行
    if intent["type"] == "market_ticker":
        cmd = ["okx", "market", "ticker", intent["inst_id"]]
        r = _run_okx_raw(cmd)
        return {"ok": r["ok"], "intent": intent, "command": " ".join(cmd), "result": r, "message": None}
    if intent["type"] == "account_balance":
        cmd = ["okx", "account", "balance"]
        r = _run_okx_raw(cmd)
        return {"ok": r["ok"], "intent": intent, "command": " ".join(cmd), "result": r, "message": None}
    if intent["type"] == "account_positions":
        cmd = ["okx", "account", "positions"]
        r = _run_okx_raw(cmd)
        return {"ok": r["ok"], "intent": intent, "command": " ".join(cmd), "result": r, "message": None}

    # 交易类：开仓
    if intent["type"] == "swap_open":
        if os.getenv("ENABLE_OKX_TRADE", "").lower() not in {"1", "true", "yes"}:
            return {
                "ok": False,
                "intent": intent,
                "command": None,
                "result": None,
                "message": "交易已禁用。请在后端设置环境变量 ENABLE_OKX_TRADE=true 后重试（并确保已配置 ~/.okx/config.toml）",
            }
        inst = intent["inst_id"]
        # 先取最新价（--json 便于解析）
        spot_inst = inst.replace("-SWAP", "")
        ticker = _run_okx_raw(["okx", "--json", "market", "ticker", spot_inst], timeout=10)
        price_s = None
        if ticker["ok"] and ticker["stdout"]:
            try:
                import json
                data = json.loads(ticker["stdout"])
                if isinstance(data, list) and len(data) > 0:
                    price_s = str(data[0].get("last") or "")
                elif isinstance(data, dict):
                    price_s = str(data.get("last") or data.get("lastPx") or "")
            except Exception:
                pass
        if not price_s or not price_s.replace(".", "").replace("-", "").isdigit():
            return {
                "ok": False,
                "intent": intent,
                "command": None,
                "result": ticker,
                "message": "无法获取当前价格，请稍后重试或使用命令：okx market ticker ETH-USDT",
            }
        price = float(price_s)
        margin_u = intent.get("margin_u") or 10
        lev = _DEFAULT_LEVERAGE
        notional = margin_u * lev
        sz = round(notional / price, 4)
        if sz <= 0:
            sz = 0.0001
        cmd = [
            "okx", "swap", "place",
            "--instId", inst,
            "--side", intent["side"],
            "--ordType", "market",
            "--sz", str(sz),
            "--posSide", intent["pos_side"],
            "--tdMode", "cross",
        ]
        if intent.get("demo"):
            cmd.insert(1, "--demo")
        r = _run_okx_raw(cmd, timeout=20)
        return {
            "ok": r["ok"],
            "intent": intent,
            "command": " ".join(cmd),
            "result": r,
            "message": f"已解析：{intent['pos_side']} {inst} 约{margin_u}U保证金(杠杆{lev}x)，数量{sz}" if r["ok"] else (r["stderr"] or "下单失败"),
        }

    return {"ok": False, "intent": intent, "command": None, "result": None, "message": "暂不支持该意图"}


# ---------- LLM Agent（任意意图 → 自动解析 → 工具调用） ----------
import json
import requests


class AgentRequest(BaseModel):
    text: str = Field(..., description="任意自然语言，例如：帮我在模拟盘以当前价格开空eth，仓位10u")
    auto_execute: bool = Field(True, description="是否自动执行（交易类会强制要求二次确认）")
    confirm: bool = Field(False, description="二次确认开关（交易类需要 confirm=true 才执行）")
    profile: Optional[str] = Field(None, description="可选：--profile <name>")
    demo: Optional[bool] = Field(None, description="可选：--demo")
    json_out: Optional[bool] = Field(None, description="可选：--json")


def _llm_to_plan(text: str) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "未配置 DEEPSEEK_API_KEY，无法启用 AI 自解析。",
        }

    system = (
        "你是 OKX 交易助手。你的任务：把用户的中文意图转换为可执行的 okx-trade-cli 命令。\n"
        "只输出严格 JSON，禁止多余文字。JSON schema：\n"
        "{\n"
        "  \"intent\": \"...简短描述...\",\n"
        "  \"risk\": \"read\"|\"trade\",\n"
        "  \"command\": \"okx ...\",\n"
        "  \"explain\": \"一句话解释你要做什么\",\n"
        "  \"need_confirm\": true|false\n"
        "}\n"
        "规则：\n"
        "- 查询类：用 okx market / okx account 查询命令，risk=read，need_confirm=false。\n"
        "- 下单/撤单/改仓/转账/机器人：risk=trade，need_confirm=true。\n"
        "- 如果用户说“模拟盘/demo”，命令要加 --demo（例如 okx --demo swap place ...）。\n"
        "- 币种：ETH → ETH-USDT-SWAP（永续）或 ETH-USDT（现货/行情）。BTC 同理。\n"
        "- 永续/合约下单必须用 okx swap place，禁止使用 trade order（CLI 不支持）。格式：okx [--demo] swap place --instId ETH-USDT-SWAP --side buy|sell --posSide long|short --ordType market --sz <数量> --tdMode isolated --lever 10。sz 为合约张数或币数量，可按“保证金*杠杆/当前价”估算并保留4位小数。\n"
        "- 重要：command 必须是“纯 okx 命令”。禁止出现任何 shell 语法/管道/变量/重定向，例如：|、;、>、<、&&、read、jq、$()。\n"
        "- 如果需要当前价/计算数量：不要在命令里做计算。先输出查询命令：okx --json market ticker <instId>（risk=read）。\n"
        "- 如果用户明确给了数量（sz）则可直接下单；如果只给了保证金/仓位U而没给数量，先让用户补充或先查价。\n"
        "- 如果无法确定，优先输出查询命令（risk=read）来获取必要信息。\n"
        "- 如果用户只是在闲聊、追问、打招呼（例如「好的」「谢谢」「你啥时候更新好」「啥时候能好」），不要编造命令，command 设为空字符串 \"\"，intent 写「用户闲聊/追问」，explain 写一句说明即可。\n"
    )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
    }
    try:
        resp = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=45)
        data = resp.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        content = content.strip()
        # 允许模型偶发包裹 ```json
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*", "", content).strip()
            content = content[:-3].strip() if content.endswith("```") else content
        plan = json.loads(content)
        return {"ok": True, "plan": plan}
    except Exception as e:
        return {"ok": False, "error": f"DeepSeek 调用/解析失败：{e}"}


def _llm_chat_reply(
    user_text: str,
    plan: Dict[str, Any],
    results: Optional[List[Dict[str, Any]]] = None,
    need_confirm: bool = False,
    executed: bool = False,
    ok: bool = True,
) -> str:
    """让 DeepSeek 生成一句有人情味的对话回复，不要冷冰冰的「意图/命令」式输出。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        if need_confirm:
            return "已经按你的要求准备好了，点一下「确认执行」我就帮你下单～"
        if executed and ok:
            return "搞定了，已经帮你执行完成。"
        if executed and not ok:
            return "执行时出了点问题，你可以看看上面的报错，需要的话再跟我说。"
        return "好的，收到。"

    summary = ""
    if plan:
        summary += f"意图：{plan.get('intent', '')}；"
        if plan.get("command"):
            summary += f"将执行命令：{plan.get('command', '')[:120]}…；"
        summary += f"说明：{plan.get('explain', '')}。"
    if results:
        for i, r in enumerate(results):
            if r.get("ok"):
                summary += f" 第{i+1}步成功。"
            else:
                summary += f" 第{i+1}步失败：{str(r.get('stderr') or r.get('stdout') or '')[:80]}。"
    if need_confirm:
        summary += " 当前等待用户确认执行。"
    if executed and ok:
        summary += " 已执行完成。"
    if executed and not ok:
        summary += " 执行未完全成功。"

    system = (
        "你是 OKX 交易助手，用朋友聊天的口吻回复用户，简短自然、有人情味。"
        "不要列点、不要写「意图」「命令」「说明」这类冷冰冰的标签，不要贴整段命令。"
        "一两句话说完：要么确认已准备好并提醒点确认，要么说执行结果如何、有没有报错。"
        "可以适当用「好啦」「搞定」「哦」等语气词。只输出这一段回复，不要其他内容。"
    )
    user_msg = f"用户说：{user_text}\n\n我们这边：{summary}\n\n请用一段话回复用户（直接说人话，不要 JSON 不要标签）。"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.5,
        "max_tokens": 300,
    }
    try:
        resp = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=15)
        data = resp.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        reply = content.strip()
        return reply if reply else "好的，收到。"
    except Exception:
        if need_confirm:
            return "已经按你的要求准备好了，点一下「确认执行」我就帮你下单～"
        if executed and ok:
            return "搞定了，已经帮你执行完成。"
        if executed and not ok:
            return "执行时出了点问题，你可以看看报错信息，需要再跟我说。"
        return "好的，收到。"


def _llm_chat_only(user_text: str, hint: str = "") -> str:
    """用户只是在闲聊/追问、或命令无效时，生成一句有人情味的回复，不执行任何命令。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "哈哈我刚才没理解清楚～你是想问啥呀？要下单、查行情还是查余额，直接跟我说就行～"

    system = (
        "你是 OKX 交易助手，用朋友聊天的口吻回复用户，一两句话、有人情味。"
        "不要列点、不要写「命令」「错误」等冷冰冰的词。"
        "若用户只是在闲聊/追问（例如问「你啥时候好」「谢谢」「好的」），就轻松回应并引导：可以说「好哒」「没问题」再问一句要不要查行情或下单。"
        "若对方遇到报错或没搞成，就安慰一下并说「再试一次」或「直接跟我说要干啥我帮你」。只输出这一段回复，不要其他内容。"
    )
    user_msg = f"用户说：{user_text}\n\n{hint}\n\n请用一段话回复用户（直接说人话）。"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        "temperature": 0.5,
        "max_tokens": 200,
    }
    try:
        resp = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=12)
        data = resp.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        reply = content.strip()
        return reply if reply else "好哒，有啥要帮忙的随时说～要下单、查行情、查余额都行。"
    except Exception:
        return "哈哈刚才没理解到～你要查行情、下单还是查余额？直接跟我说就行～"


def _run_single_okx_command(command: str, *, profile: Optional[str], demo: Optional[bool], json_out: Optional[bool]) -> Dict[str, Any]:
    # 复用 run_okx 的白名单校验
    req = OkxRunRequest(command=command, profile=profile, demo=bool(demo), json=bool(json_out))
    return run_okx(req, _={})  # type: ignore[arg-type]


@router.post("/agent", summary="AI 自解析任意意图（DeepSeek）")
def okx_agent(req: AgentRequest, user: dict = Depends(require_user)) -> Dict[str, Any]:
    llm = _llm_to_plan(req.text)
    if not llm.get("ok"):
        reply = _llm_chat_only(req.text, "解析时出了点问题：" + (llm.get("error") or "AI 解析失败"))
        return {"ok": False, "message": llm.get("error") or "AI 解析失败", "reply": reply, "plan": None}

    plan = llm["plan"] or {}
    command = str(plan.get("command") or "").strip()
    risk = str(plan.get("risk") or "read").strip().lower()
    need_confirm = bool(plan.get("need_confirm") or False) or (risk == "trade")

    # 用户只是在闲聊/追问时 AI 会返回空 command，不报错，用人话回复
    if not command or not command.strip():
        reply = _llm_chat_only(req.text, "用户可能只是在闲聊或追问，没有给出具体操作。")
        return {"ok": True, "executed": False, "need_confirm": False, "reply": reply, "plan": plan}
    if not command.startswith("okx "):
        reply = _llm_chat_only(req.text, "当前没解析出可执行的命令。")
        return {"ok": True, "executed": False, "reply": reply, "plan": plan}

    # 不允许危险分隔符
    if any(x in command for x in ["|", ";", ">", "<"]):
        return {"ok": False, "message": "AI 输出命令包含不允许的分隔符", "plan": plan}

    # 禁止把 shell 脚本片段混进来
    lowered = command.lower()
    if any(x in lowered for x in [" jq", "read ", "$(", "`", "export ", "set ", "powershell", "cmd.exe"]):
        return {"ok": False, "message": "AI 输出包含不允许的 shell 脚本片段（请只输出 okx 命令）", "plan": plan}

    # 先做兜底修正（保证金/杠杆/posSide/sz），再决定是否返回“需确认”，这样首次展示的 plan 已是用户说的 3555U、3x
    try:
        cmd_tokens = _tokenize(command)
        lowered_tokens = [t.lower() for t in cmd_tokens]
        is_swap_place = len(lowered_tokens) >= 3 and lowered_tokens[0] == "okx" and "swap" in lowered_tokens and "place" in lowered_tokens
        if is_swap_place:
            # 找 instId / lever / sz
            def _get_flag_value(flag: str) -> Optional[str]:
                if flag in lowered_tokens:
                    i = lowered_tokens.index(flag)
                    if i + 1 < len(cmd_tokens):
                        return cmd_tokens[i + 1]
                return None

            inst_id = _get_flag_value("--instid")
            lever_s = _get_flag_value("--lever")
            sz_s = _get_flag_value("--sz")

            # OKX 默认多为「净仓」模式，posSide 需为 net；long/short 会报 Parameter posSide error
            if "--posside" in lowered_tokens:
                pi = lowered_tokens.index("--posside")
                if pi + 1 < len(cmd_tokens) and cmd_tokens[pi + 1].lower() in ("long", "short"):
                    cmd_tokens[pi + 1] = "net"
                    command = " ".join(cmd_tokens)
                    plan["command"] = command
                    plan["explain"] = (plan.get("explain") or "") + "（净仓模式已改为 posSide=net）"

            lever = 10
            if lever_s:
                try:
                    lever = int(float(lever_s))
                except Exception:
                    lever = 10

            sz_val = None
            if sz_s:
                try:
                    sz_val = float(sz_s)
                except Exception:
                    sz_val = None

            # 从用户文本提取保证金 U（支持 3555u / 3555usdt，默认 10U）
            margin_u = 10
            m = re.search(r"(\d+)\s*u(?:sdt)?", (req.text or "").lower())
            if m:
                try:
                    margin_u = int(m.group(1))
                except Exception:
                    margin_u = 10

            # 从用户文本提取杠杆（支持 3x / 3倍），优先于命令里的 --lever
            lever_from_text = None
            m_lev = re.search(r"(\d+)\s*(?:x|倍)", (req.text or "").lower())
            if m_lev:
                try:
                    lever_from_text = int(m_lev.group(1))
                except Exception:
                    pass
            if lever_from_text is not None:
                lever = lever_from_text
                if "--lever" in lowered_tokens:
                    j = lowered_tokens.index("--lever")
                    if j + 1 < len(cmd_tokens):
                        cmd_tokens[j + 1] = str(lever)
                else:
                    cmd_tokens += ["--lever", str(lever)]
                command = " ".join(cmd_tokens)
                plan["command"] = command
                plan["explain"] = (plan.get("explain") or "") + f"（已按你说的 {margin_u}U、{lever}x 算好了）"

            # OKX 永续 sz=合约张数；ETH-USDT-SWAP 1张=0.1 ETH，步长 0.01 张（见 OKX 合约规格）
            def _swap_spec(inst: str):
                if not inst:
                    return None, None
                u = (inst or "").upper()
                if "ETH" in u and "-USDT-SWAP" in u:
                    return 0.1, 0.01   # ctVal=0.1 ETH/张, lotSz=0.01 张
                if "BTC" in u and "-USDT-SWAP" in u:
                    return 0.01, 0.01  # 1张=0.01 BTC, 步长 0.01
                return None, None

            ct_val, lot_sz = _swap_spec(inst_id or "")
            if inst_id and sz_val is not None and sz_val > 0 and lot_sz is not None and ct_val is not None:
                # AI 常按「币数量」输出（如 4.927 ETH），OKX 要求「张数」：张数 = 币数 / ctVal
                if sz_val < 100:
                    contracts = sz_val / ct_val
                else:
                    contracts = sz_val
                sz_rounded = round(contracts / lot_sz) * lot_sz
                sz_rounded = round(sz_rounded, 2)
                if sz_rounded <= 0:
                    sz_rounded = lot_sz
                if abs(sz_rounded - sz_val) > 1e-6 and "--sz" in lowered_tokens:
                    j = lowered_tokens.index("--sz")
                    cmd_tokens[j + 1] = f"{sz_rounded:.2f}"
                    command = " ".join(cmd_tokens)
                    plan["command"] = command
                    plan["explain"] = (plan.get("explain") or "") + f"（已按合约张数步长 {lot_sz} 取整为 {sz_rounded:.2f} 张）"

            if (sz_val is None or sz_val <= 0) and inst_id:
                spot_inst = inst_id.replace("-SWAP", "")
                ticker = _run_okx_raw(["okx", "--json", "market", "ticker", spot_inst], timeout=10)
                price_s = None
                if ticker.get("ok") and ticker.get("stdout"):
                    try:
                        data = json.loads(ticker["stdout"])
                        if isinstance(data, list) and len(data) > 0:
                            price_s = str(data[0].get("last") or "")
                        elif isinstance(data, dict):
                            price_s = str(data.get("last") or data.get("lastPx") or "")
                    except Exception:
                        price_s = None
                if price_s and ct_val and lot_sz:
                    try:
                        price = float(price_s)
                        notional = float(margin_u) * float(lever)
                        eth_equiv = notional / price
                        contracts = eth_equiv / ct_val
                        sz_new = round(contracts / lot_sz) * lot_sz
                        sz_new = round(sz_new, 2)
                        if sz_new <= 0:
                            sz_new = lot_sz
                        if "--sz" in lowered_tokens:
                            j = lowered_tokens.index("--sz")
                            cmd_tokens[j + 1] = f"{sz_new:.2f}"
                        else:
                            cmd_tokens += ["--sz", f"{sz_new:.2f}"]
                        command = " ".join(cmd_tokens)
                        plan["command"] = command
                        plan["explain"] = (plan.get("explain") or "") + f"（{notional:.0f}U/{price:.2f}≈{eth_equiv:.4f} ETH→{sz_new:.2f} 张，步长 {lot_sz}）"
                    except Exception:
                        pass
                elif price_s:
                    # 未知合约规格，按 0.1 张步长保守取整（避免再次报错）
                    try:
                        price = float(price_s)
                        notional = float(margin_u) * float(lever)
                        eth_equiv = notional / price
                        contracts = eth_equiv / 0.1
                        sz_new = round(contracts / 0.01) * 0.01
                        sz_new = round(sz_new, 2)
                        if sz_new <= 0:
                            sz_new = 0.01
                        if "--sz" in lowered_tokens:
                            j = lowered_tokens.index("--sz")
                            cmd_tokens[j + 1] = f"{sz_new:.2f}"
                        else:
                            cmd_tokens += ["--sz", f"{sz_new:.2f}"]
                        command = " ".join(cmd_tokens)
                        plan["command"] = command
                        plan["explain"] = (plan.get("explain") or "") + f"（已按 0.01 张取整为 {sz_new:.2f}）"
                    except Exception:
                        pass
    except Exception:
        pass

    command = str(plan.get("command") or command).strip()

    # 交易类：强制二次确认（在兜底修正之后返回，这样 plan 里已是正确的保证金/杠杆）
    if need_confirm and not req.confirm:
        reply = _llm_chat_reply(req.text, plan, need_confirm=True, executed=False, ok=True)
        return {
            "ok": True,
            "executed": False,
            "need_confirm": True,
            "message": "检测到交易/资金操作，已生成计划。请点击“确认执行”后再下单。",
            "reply": reply,
            "plan": plan,
        }

    parts = [command]
    results: List[Dict[str, Any]] = []
    try:
        for p in parts:
            if not p.startswith("okx "):
                reply = _llm_chat_only(req.text, "命令不合法，无法执行。")
                return {"ok": False, "message": "命令不合法", "reply": reply, "plan": plan}
            results.append(_run_single_okx_command(p, profile=req.profile, demo=req.demo, json_out=req.json_out))
            if results[-1].get("ok") is False:
                break
    except HTTPException as e:
        detail = e.detail if isinstance(getattr(e, "detail", None), str) else str(getattr(e, "detail", str(e)))
        reply = _llm_chat_only(req.text, f"执行时遇到：{detail}，请换个说法或稍后再试。")
        return {"ok": False, "executed": False, "reply": reply, "plan": plan, "results": results}

    ok_result = all(r.get("ok") for r in results) if results else False
    reply = _llm_chat_reply(req.text, plan, results=results, need_confirm=False, executed=True, ok=ok_result)
    return {
        "ok": ok_result,
        "executed": True,
        "need_confirm": False,
        "reply": reply,
        "plan": plan,
        "results": results,
    }


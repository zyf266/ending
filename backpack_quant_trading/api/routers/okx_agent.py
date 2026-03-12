"""
OKX Agent Trade Kit 集成 API（欧意版 OpenClaw / MCP）
- 能力说明、模块与工具列表、快速开始、安全与 FAQ
- 不存储也不接触用户 API Key，仅提供文档与接入指引
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()


class ToolGroup(BaseModel):
    name: str
    description: str
    auth: str  # "公开" | "需 API Key"
    tools: List[dict]


class ModuleInfo(BaseModel):
    id: str
    name: str
    description: str
    auth: str
    tool_count: int
    tools: List[dict]


@router.get("/capabilities", summary="OKX Agent 能力概览")
def get_capabilities():
    """返回 OKX Agent Trade Kit 模块与能力说明，供前端展示。"""
    return {
        "title": "OKX Agent Trade Kit",
        "subtitle": "欧易官方 AI 智能交易工具包 · 自然语言驱动",
        "description": "将 AI 助手与您的 OKX 账户直接连接。无需在 AI 和交易所之间来回切换，用自然语言即可执行行情查询、现货/合约/期权交易、账户管理与网格策略。",
        "features": [
            "行情数据 — 价格、订单簿、K 线、资金费率、持仓量",
            "现货交易 — 下单、撤单、改单、批量操作、策略委托",
            "合约与永续 — 永续/交割、杠杆、持仓管理",
            "期权 — 下单、期权链、希腊字母（IV、Delta、Gamma、Theta、Vega）",
            "策略委托 — 条件单、OCO 止盈止损、追踪止损",
            "账户 — 余额、账单、手续费率、仓位管理",
            "机器人 — 网格、DCA 定投策略的创建与监控",
        ],
        "usage_modes": [
            {"id": "mcp", "name": "MCP 服务器", "pkg": "okx-trade-mcp", "desc": "接入 Claude、Cursor、VS Code、Windsurf 等，自然语言调用 OKX 工具"},
            {"id": "cli", "name": "命令行", "pkg": "okx-trade-cli", "desc": "终端直接交易，支持管道、定时任务与脚本，无需 AI 客户端"},
            {"id": "skills", "name": "Skills (OpenClaw)", "pkg": "okx/agent-skills", "desc": "即插即用模块，适用于支持 Skills 的 AI 客户端（如 OpenClaw）"},
        ],
        "modules": [
            {
                "id": "market",
                "name": "行情数据",
                "description": "最新价、盘口、K 线、资金费率、持仓量、指数",
                "auth": "公开 · 无需 API Key",
                "tool_count": 12,
                "tools": [
                    {"name": "market_get_ticker", "desc": "单币对行情"},
                    {"name": "market_get_orderbook", "desc": "盘口深度"},
                    {"name": "market_get_candles", "desc": "K 线（最近 300 根）"},
                    {"name": "market_get_funding_rate", "desc": "永续资金费率"},
                    {"name": "market_get_open_interest", "desc": "持仓量"},
                ],
            },
            {
                "id": "spot",
                "name": "现货交易",
                "description": "市价/限价、Post-only、FOK/IOC、批量下单与撤单",
                "auth": "需 API Key（交易权限）",
                "tool_count": 10,
                "tools": [
                    {"name": "spot_place_order", "desc": "下现货单"},
                    {"name": "spot_cancel_order", "desc": "撤销挂单"},
                    {"name": "spot_batch_place_orders", "desc": "批量下单（最多 20 笔）"},
                    {"name": "spot_get_open_orders", "desc": "当前挂单"},
                ],
            },
            {
                "id": "swap",
                "name": "永续合约",
                "description": "永续合约下单、改单、一键平仓、杠杆设置",
                "auth": "需 API Key（交易权限）",
                "tool_count": 12,
                "tools": [
                    {"name": "swap_place_order", "desc": "下永续单"},
                    {"name": "swap_close_position", "desc": "一键平仓"},
                    {"name": "swap_get_positions", "desc": "当前持仓"},
                    {"name": "swap_set_leverage", "desc": "设置杠杆"},
                ],
            },
            {
                "id": "option",
                "name": "期权",
                "description": "期权下单、期权链、Greeks（IV、Delta、Gamma、Theta、Vega）",
                "auth": "需 API Key（交易权限）",
                "tool_count": 8,
                "tools": [
                    {"name": "option_place_order", "desc": "期权下单"},
                    {"name": "option_get_instruments", "desc": "期权链"},
                    {"name": "option_get_greeks", "desc": "IV + Greeks"},
                ],
            },
            {
                "id": "account",
                "name": "账户管理",
                "description": "余额、持仓、账单、费率、仓位模式、审计日志",
                "auth": "需 API Key（读取权限）",
                "tool_count": 12,
                "tools": [
                    {"name": "account_get_balance", "desc": "交易账户余额"},
                    {"name": "account_get_positions", "desc": "当前所有持仓"},
                    {"name": "account_get_bills", "desc": "账单流水"},
                    {"name": "account_get_fee_rates", "desc": "手续费率"},
                ],
            },
            {
                "id": "bot",
                "name": "策略机器人",
                "description": "网格（现货/合约/Moon Grid）、DCA 定投",
                "auth": "需 API Key（交易权限）",
                "tool_count": 8,
                "tools": [
                    {"name": "grid_create_order", "desc": "创建网格机器人"},
                    {"name": "grid_stop_order", "desc": "停止网格"},
                    {"name": "dca_create_order", "desc": "创建 DCA 策略"},
                    {"name": "dca_get_orders", "desc": "DCA 策略列表"},
                ],
            },
        ],
        "security": [
            "模拟盘模式（--demo）— 模拟账户交易，实盘资金不受影响",
            "只读模式（--read-only）— 仅允许数据查询，禁止交易",
            "智能注册 — 根据 API Key 权限自动暴露/隐藏下单类工具",
            "风险标签 — 资金操作工具均标记 [CAUTION]，提示 AI 确认",
        ],
        "links": {
            "github_mcp": "https://github.com/okx/agent-trade-kit",
            "github_skills": "https://github.com/okx/agent-skills",
            "npm_mcp": "https://www.npmjs.com/package/@okx_ai/okx-trade-mcp",
            "npm_cli": "https://www.npmjs.com/package/@okx_ai/okx-trade-cli",
            "okx_api_docs": "https://www.okx.com/docs-v5",
            "telegram": "https://t.me/OKX_AgentKit",
        },
    }


@router.get("/quickstart", summary="快速开始步骤")
def get_quickstart():
    """返回 OpenClaw / MCP 快速开始步骤。"""
    return {
        "openclaw": [
            {"step": 1, "title": "安装 Skills", "content": "在 OpenClaw 对话框中发送：运行 npx skills add okx/agent-skills，自主解决所有碰到的问题，查询 BTC 价格。"},
            {"step": 2, "title": "配置 API 凭证", "content": "在终端创建 ~/.okx/config.toml，填入 api_key、secret_key、passphrase。建议先用模拟盘（demo = true）。"},
            {"step": 3, "title": "试用", "content": "在 AI 中输入：OKX 上 BTC 现在的价格是多少？ / 查看我的账户余额 / 在模拟盘用市价单买入 100 USDT 的 BTC"},
        ],
        "mcp": [
            {"step": 1, "title": "安装", "content": "npm install -g @okx_ai/okx-trade-mcp @okx_ai/okx-trade-cli"},
            {"step": 2, "title": "配置凭证", "content": "运行 okx config init 或手动创建 ~/.okx/config.toml"},
            {"step": 3, "title": "连接 AI 客户端", "content": "okx-trade-mcp setup --client cursor（或 claude-desktop / vscode / windsurf）"},
            {"step": 4, "title": "试用", "content": "在 AI 中输入：OKX 上 BTC 现在的价格是多少？ 或 查看我的账户余额"},
        ],
        "config_example": """
default_profile = "demo"

[profiles.demo]
api_key    = "your-demo-api-key"
secret_key = "your-demo-secret-key"
passphrase = "your-demo-passphrase"
demo       = true

[profiles.live]
api_key    = "your-live-api-key"
secret_key = "your-live-secret-key"
passphrase = "your-live-passphrase"
""".strip(),
    }


@router.get("/faq", summary="常见问题摘要")
def get_faq():
    """常见问题精简版。"""
    return {
        "items": [
            {"q": "Agent Trade Kit 能做什么？", "a": "涵盖欧易核心功能：查询价格、现货/合约/期权交易、高级订单（止盈止损、追踪止损）、账户管理、网格与 DCA 机器人。均可通过自然语言或命令行完成。"},
            {"q": "支持哪些 AI 客户端？", "a": "支持兼容 MCP 的客户端（Claude Desktop、Claude Code、Cursor、VS Code、Windsurf 等）。Skills 方式适用于 OpenClaw 等支持 Skills 的客户端。"},
            {"q": "API Key 安全吗？", "a": "程序在本地运行，密钥仅保存在本地 ~/.okx/config.toml，签名在本地完成，AI 无法获取凭证。建议使用子账户 API Key 并仅开启最小权限。"},
            {"q": "是否收费？", "a": "基于 MIT 协议完全开源免费。仅需欧易账户与 API Key（仅查行情则不需要 Key）。"},
        ],
    }

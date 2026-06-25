#!/usr/bin/env bash
# 服务器上一键重启全部交易相关进程（须在上传最新代码后执行）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

MIXED_PORT="${MIXED_PORT:-7891}"
PROXY_URL="${PROXY_URL:-http://127.0.0.1:${MIXED_PORT}}"

export TRADING_SERVER=1
export STOCK_NEWS_FORCE_SYSTEM_PROXY=1
export CRYPTO_SCORE_ENABLED=0
export US_STOCK_SCORE_ENABLED=1
export DEEPSEEK_SCORE_MODEL=deepseek-v4-flash
export DEEPSEEK_SCORE_THINKING=0
export HTTP_PROXY="${PROXY_URL}"
export HTTPS_PROXY="${PROXY_URL}"
export ALL_PROXY="${PROXY_URL}"
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"

LOG_DIR="$ROOT/backpack_quant_trading/log"
mkdir -p "$LOG_DIR"

_is_port_listening() {
  local p="$1"
  ss -tlnp 2>/dev/null | grep -qE ":[[:space:]]*${p}[[:space:]]"
}

_ensure_mihomo_running() {
  local config_dir="${HOME}/.config/mihomo"
  local mihomo_bin="${HOME}/.local/bin/mihomo"
  local cfg="${config_dir}/config.yaml"

  if _is_port_listening "${MIXED_PORT}"; then
    return 0
  fi

  if [[ ! -x "${mihomo_bin}" ]] || [[ ! -f "${cfg}" ]]; then
    return 1
  fi

  echo "mihomo 未在 ${MIXED_PORT} 监听，尝试后台启动..."
  nohup "${mihomo_bin}" -d "${config_dir}" -f "${cfg}" >>"${LOG_DIR}/mihomo.out" 2>&1 &
  local i
  for i in $(seq 1 12); do
    sleep 1
    if _is_port_listening "${MIXED_PORT}"; then
      echo "mihomo 已启动 (pid $(pgrep -f "${mihomo_bin}" | head -1 || echo '?'))"
      return 0
    fi
  done
  echo "mihomo 启动超时，最近日志:"
  tail -5 "${LOG_DIR}/mihomo.out" 2>/dev/null || true
  return 1
}

_proxy_self_check() {
  local err_file
  err_file="$(mktemp)"
  if curl -fsSL --max-time 12 -x "${PROXY_URL}" -o /dev/null \
    "https://fapi.binance.com/fapi/v1/ping" 2>"${err_file}"; then
    rm -f "${err_file}"
    return 0
  fi
  # 币安偶发超时，再试一个轻量探测
  if curl -fsSL --max-time 12 -x "${PROXY_URL}" -o /dev/null \
    "http://www.gstatic.com/generate_204" 2>"${err_file}"; then
    rm -f "${err_file}"
    return 0
  fi
  echo "curl 错误: $(tr '\n' ' ' <"${err_file}" | head -c 200)"
  rm -f "${err_file}"
  return 1
}

_sync_proxy_from_port() {
  PROXY_URL="${PROXY_URL:-http://127.0.0.1:${MIXED_PORT}}"
  export HTTP_PROXY="${PROXY_URL}" HTTPS_PROXY="${PROXY_URL}" ALL_PROXY="${PROXY_URL}"
}

ENV_DIR="$ROOT/backpack_quant_trading"
if [[ -f "$ENV_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_DIR/.env"
  set +a
fi
if [[ -f "$ENV_DIR/.env.secrets" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_DIR/.env.secrets"
  set +a
fi

MIXED_PORT="${MIXED_PORT:-7891}"
_sync_proxy_from_port

if [[ ! -f "$ENV_DIR/.env.secrets" ]]; then
  echo "错误: 缺少 $ENV_DIR/.env.secrets（ENV_SECRETS_PASSPHRASE，用于解密 DEEPSEEK_API_KEY_ENC）"
  exit 1
fi
chmod 600 "$ENV_DIR/.env" "$ENV_DIR/.env.secrets" 2>/dev/null || true

echo "代理: HTTP_PROXY=${HTTP_PROXY} ALL_PROXY=${ALL_PROXY}"

if ! _is_port_listening "${MIXED_PORT}"; then
  echo "端口 ${MIXED_PORT} 未监听"
  if ! _ensure_mihomo_running; then
    echo "警告: 无法启动 mihomo。请先执行:"
    echo "  export CLASH_SUB_URL='<<你的订阅链接>>'"
    echo "  bash backpack_quant_trading/tools/proxy/start_clash.sh   # 或 tmux/nohup 后台常驻"
    echo "  确认 mixed-port 与 MIXED_PORT=${MIXED_PORT} 一致"
  fi
elif pgrep -f "mihomo" >/dev/null 2>&1; then
  echo "mihomo 进程: $(pgrep -af mihomo | head -1)"
fi

if _proxy_self_check; then
  echo "代理自检: OK (${PROXY_URL})"
else
  echo "警告: 代理自检失败（端口 ${MIXED_PORT}）"
  if _is_port_listening "${MIXED_PORT}"; then
    echo "  端口在监听但外网不通，常见原因:"
    echo "  1) 订阅节点失效 — 重启 start_clash.sh 或换节点"
    echo "  2) Country.mmdb 缺失 — 见 tools/proxy/start_clash.sh 的 MMDB 说明"
    echo "  3) 手动验证: curl -v -x ${PROXY_URL} https://fapi.binance.com/fapi/v1/ping"
  else
    echo "  请先启动 mihomo/clash 并确认 mixed-port=${MIXED_PORT}"
  fi
fi

_launch() {
  local name="$1"
  shift
  nohup bash -lc "
    cd '${ROOT}'
    if [[ -f '${ENV_DIR}/.env' ]]; then set -a; source '${ENV_DIR}/.env'; set +a; fi
    if [[ -f '${ENV_DIR}/.env.secrets' ]]; then set -a; source '${ENV_DIR}/.env.secrets'; set +a; fi
    export TRADING_SERVER=1
    export STOCK_NEWS_FORCE_SYSTEM_PROXY=1
    export CRYPTO_SCORE_ENABLED=0
    export US_STOCK_SCORE_ENABLED=1
    export DEEPSEEK_SCORE_MODEL=deepseek-v4-flash
    export DEEPSEEK_SCORE_THINKING=0
    export HTTP_PROXY='${PROXY_URL}'
    export HTTPS_PROXY='${PROXY_URL}'
    export ALL_PROXY='${PROXY_URL}'
    export NO_PROXY='${NO_PROXY:-127.0.0.1,localhost}'
    exec $*
  " >>"$LOG_DIR/${name}.out" 2>&1 &
}

echo "停止旧进程..."
pkill -f "backpack_quant_trading/webhook_service.py" 2>/dev/null || true
pkill -f "tradingview_bot.py" 2>/dev/null || true
pkill -f "backpack_quant_trading/run_api.py" 2>/dev/null || true
pkill -f "backpack_quant_trading/dingtalk_score_bot.py" 2>/dev/null || true
sleep 2

echo "启动 webhook_service (8005)..."
_launch webhook_service python backpack_quant_trading/webhook_service.py

echo "启动 tradingview_bot (5001)..."
_launch tradingview_bot python tradingview_bot.py

echo "启动 run_api (8100)..."
_launch run_api python backpack_quant_trading/run_api.py

if [[ -n "${DINGTALK_SCORE_BOT_CLIENT_ID:-}" ]] && [[ -n "${DINGTALK_SCORE_BOT_CLIENT_SECRET:-}" ]]; then
  echo "启动 dingtalk_score_bot (Stream 手动评分)..."
  _launch dingtalk_score_bot python backpack_quant_trading/dingtalk_score_bot.py
else
  echo "跳过 dingtalk_score_bot（未配置 DINGTALK_SCORE_BOT_CLIENT_ID/SECRET）"
fi

sleep 3
echo "--- 当前进程 ---"
pgrep -af "webhook_service|tradingview_bot|run_api|dingtalk_score_bot" || true
echo "--- 进程内代理环境变量（抽样第一个 run_api）---"
pid="$(pgrep -f 'backpack_quant_trading/run_api.py' | head -1 || true)"
if [[ -n "${pid}" ]]; then
  tr '\0' '\n' <"/proc/${pid}/environ" 2>/dev/null | grep -E '^(HTTP|HTTPS|ALL)_PROXY=' || true
fi
echo "--- 启动日志(DeepSeek配置) ---"
grep -h "DeepSeek评分.*启动配置" "$LOG_DIR"/app_*.log 2>/dev/null | tail -3 || true

#!/usr/bin/env bash
set -euo pipefail

PROXY_HTTP="${PROXY_HTTP:-http://127.0.0.1:7890}"
PROXY_SOCKS="${PROXY_SOCKS:-socks5://127.0.0.1:7890}"

export HTTP_PROXY="${PROXY_HTTP}"
export HTTPS_PROXY="${PROXY_HTTP}"
export ALL_PROXY="${PROXY_SOCKS}"

echo "HTTP_PROXY=${HTTP_PROXY}"
echo "HTTPS_PROXY=${HTTPS_PROXY}"
echo "ALL_PROXY=${ALL_PROXY}"
echo "启动 API..."

exec python -m backpack_quant_trading.run_api


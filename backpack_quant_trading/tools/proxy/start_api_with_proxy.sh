#!/usr/bin/env bash
set -euo pipefail

MIXED_PORT="${MIXED_PORT:-7891}"
PROXY_HTTP="${PROXY_HTTP:-http://127.0.0.1:${MIXED_PORT}}"
PROXY_SOCKS="${PROXY_SOCKS:-socks5://127.0.0.1:${MIXED_PORT}}"

export HTTP_PROXY="${PROXY_HTTP}"
export HTTPS_PROXY="${PROXY_HTTP}"
export ALL_PROXY="${PROXY_SOCKS}"
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"

echo "HTTP_PROXY=${HTTP_PROXY}"
echo "HTTPS_PROXY=${HTTPS_PROXY}"
echo "ALL_PROXY=${ALL_PROXY}"
echo "NO_PROXY=${NO_PROXY}"
echo "启动 API..."

exec python -m backpack_quant_trading.run_api


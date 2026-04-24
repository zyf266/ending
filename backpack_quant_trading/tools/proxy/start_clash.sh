#!/usr/bin/env bash
set -euo pipefail

# 兼容两种用法：
# 1) 推荐：运行时 export CLASH_SUB_URL=...
# 2) 你明确希望“写死在脚本里”：把 DEFAULT_CLASH_SUB_URL 改成你的订阅链接
DEFAULT_CLASH_SUB_URL="https://bsub.douyincdns.com/2cad2128/5d113b9c-7861-4be7-a0ea-a5b24a515f77/x28ffHmCJ9xJMtSr?x=48fd675a68e4&sub=clash&clash=1"
CLASH_SUB_URL="${CLASH_SUB_URL:-${DEFAULT_CLASH_SUB_URL}}"
if [[ -z "${CLASH_SUB_URL}" ]]; then
  echo "ERROR: 未设置 CLASH_SUB_URL，且 DEFAULT_CLASH_SUB_URL 为空"
  echo "示例: export CLASH_SUB_URL=\"你的订阅链接\""
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${HOME}/.config/mihomo"
BIN_DIR="${HOME}/.local/bin"
MIHOMO_BIN="${BIN_DIR}/mihomo"

mkdir -p "${CONFIG_DIR}" "${BIN_DIR}"

SUB_FILE="${CONFIG_DIR}/subscription.yaml"
CFG_FILE="${CONFIG_DIR}/config.yaml"

echo "[1/4] 下载订阅到 ${SUB_FILE}"
curl -fsSL "${CLASH_SUB_URL}" -o "${SUB_FILE}"

# 生成一个最小可用的 config.yaml：把订阅作为外部 provider 引入
# 说明：
# - 大多数订阅本身就是完整 clash 配置；但各家端口/tun 可能不一致。
# - 这里统一使用 mixed-port=7890，便于服务端程序设置 HTTP(S)_PROXY。
echo "[2/4] 生成 ${CFG_FILE}"
cat > "${CFG_FILE}" <<'YAML'
mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
external-controller: 127.0.0.1:9090

# DNS 可按需调整；云服务器一般用系统 DNS 即可
dns:
  enable: true
  listen: 127.0.0.1:1053
  ipv6: false
  enhanced-mode: fake-ip
  nameserver:
    - 223.5.5.5
    - 1.1.1.1

proxy-providers:
  sub:
    type: http
    path: ./subscription.yaml
    url: http://127.0.0.1/placeholder
    interval: 3600
    health-check:
      enable: true
      url: http://www.gstatic.com/generate_204
      interval: 300

proxies: []
proxy-groups:
  - name: PROXY
    type: select
    use:
      - sub
    url: http://www.gstatic.com/generate_204
    interval: 300

rules:
  - MATCH,PROXY
YAML

# 把 provider 的 url 指向真实订阅；避免在 here-doc 中展开变量导致 YAML 转义问题
python3 - <<PY
import pathlib
p = pathlib.Path("${CFG_FILE}")
s = p.read_text(encoding="utf-8")
s = s.replace("url: http://127.0.0.1/placeholder", "url: " + "${CLASH_SUB_URL}".replace("\\n",""))
p.write_text(s, encoding="utf-8")
PY

echo "[3/4] 准备 mihomo 二进制"
if [[ ! -x "${MIHOMO_BIN}" ]]; then
  # 说明：mihomo 发布物 URL 可能随时间变动；若下载失败，请自行安装 mihomo 并放到 ~/.local/bin/mihomo
  MIHOMO_URL_DEFAULT="https://github.com/MetaCubeX/mihomo/releases/latest/download/mihomo-linux-amd64-compatible.gz"
  MIHOMO_URL="${MIHOMO_URL:-${MIHOMO_URL_DEFAULT}}"
  echo "下载: ${MIHOMO_URL}"
  tmp_gz="$(mktemp)"
  if ! curl -fsSL "${MIHOMO_URL}" -o "${tmp_gz}"; then
    echo "ERROR: 下载 mihomo 失败。你可以手动安装后放到 ${MIHOMO_BIN}"
    exit 1
  fi
  gzip -dc "${tmp_gz}" > "${MIHOMO_BIN}"
  chmod +x "${MIHOMO_BIN}"
  rm -f "${tmp_gz}"
else
  echo "已存在: ${MIHOMO_BIN}"
fi

echo "[4/4] 启动 mihomo（前台）"
echo "提示：可用 tmux/nohup 让其后台常驻"
echo "配置目录: ${CONFIG_DIR}"
exec "${MIHOMO_BIN}" -d "${CONFIG_DIR}" -f "${CFG_FILE}"


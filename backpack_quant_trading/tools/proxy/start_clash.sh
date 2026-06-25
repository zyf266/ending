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
MIXED_PORT="${MIXED_PORT:-7891}"
CTRL_ADDR="${CTRL_ADDR:-127.0.0.1:9090}"

mkdir -p "${CONFIG_DIR}" "${BIN_DIR}"

SUB_FILE="${CONFIG_DIR}/subscription.yaml"
CFG_FILE="${CONFIG_DIR}/config.yaml"
SUB_LOG="${CONFIG_DIR}/download_last.err"

_sub_looks_valid() {
  local f="$1"
  [[ -s "${f}" ]] || return 1
  if head -n 5 "${f}" | tr -d '\r' | grep -qiE '<!doctype html|<html|access denied|forbidden|unauthorized|登录|subscribe|token|expired'; then
    return 1
  fi
  grep -qE '^(proxies:|proxy-groups:|proxy-providers:|rules:|rule-providers:)' "${f}"
}

_sub_has_proxy_nodes() {
  local f="$1"
  python3 - "${f}" <<'PY'
import re, sys
from pathlib import Path

def has_nodes(t: str) -> bool:
    if re.search(r"^proxy-providers:\s*$", t, re.M):
        return True
    if re.search(r"^proxies:\s*\[\s*\]", t, re.M):
        return False
    in_proxies = False
    for line in t.splitlines():
        if re.match(r"^proxies:\s*$", line):
            in_proxies = True
            continue
        if not in_proxies:
            continue
        if line and line[0] not in " \t" and re.match(r"^[A-Za-z0-9_-]+:", line):
            break
        if re.match(r"^\s+-\s+", line) and "name" in line:
            return True
    return False

p = Path(sys.argv[1])
sys.exit(0 if p.is_file() and has_nodes(p.read_text(encoding="utf-8", errors="ignore")) else 1)
PY
}

_sub_diag() {
  local f="$1"
  echo "--- 订阅诊断: ${f} ---"
  echo "大小: $(wc -c <"${f}" 2>/dev/null || echo 0) bytes"
  echo "前 3 行:"
  head -n 3 "${f}" 2>/dev/null | sed 's/^/  /'
  local n
  n="$(grep -cE '^[[:space:]]*-[[:space:]]+name:' "${f}" 2>/dev/null || echo 0)"
  echo "proxies 节点数(粗估): ${n}"
  if grep -qi 'MANAGED-CONFIG' "${f}" 2>/dev/null; then
    echo "类型: MANAGED-CONFIG 托管壳（proxies 常为空，需本机下载完整订阅后上传）"
  fi
}

_download_clash_sub() {
  local url="$1" out="$2"
  local ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
  local tmp="${out}.tmp"
  local err="${SUB_LOG}"
  : >"${err}"

  _try_curl() {
    # shellcheck disable=SC2068
    if curl -fsSL --connect-timeout 15 --max-time 120 "$@" "${url}" -o "${tmp}" 2>>"${err}"; then
      if _sub_looks_valid "${tmp}" && _sub_has_proxy_nodes "${tmp}"; then
        mv -f "${tmp}" "${out}"
        return 0
      fi
      echo "WARN: 下载内容无有效代理节点（可能是空壳/HTML）" >>"${err}"
    fi
    rm -f "${tmp}"
    return 1
  }

  # 多种请求头组合，应对订阅站对 curl/机房 IP 的 403 限制
  _try_curl \
    || _try_curl -A "${ua}" \
    || _try_curl -A "${ua}" -H "Accept: text/yaml,application/yaml,*/*" \
    || _try_curl -A "${ua}" -H "Referer: https://www.google.com/" \
    || _try_curl -A "${ua}" -H "Referer: ${url%%\?*}" \
    || return 1
}

echo "[1/4] 下载订阅到 ${SUB_FILE}"
# 若订阅站点对 curl/机房 IP 有限制，可能返回 403。
# 处理策略：
# - CLASH_SUB_FILE：本地订阅文件（推荐：本机下载后 scp 上传）
# - 下载失败时复用已有有效 subscription.yaml
# - 多组 UA/Referer 重试
if [[ -n "${CLASH_SUB_FILE:-}" ]]; then
  echo "使用本地订阅文件: ${CLASH_SUB_FILE}"
  cp -f "${CLASH_SUB_FILE}" "${SUB_FILE}"
elif [[ "${CLASH_SUB_SKIP_DOWNLOAD:-}" == "1" ]] && _sub_looks_valid "${SUB_FILE}" && _sub_has_proxy_nodes "${SUB_FILE}"; then
  echo "跳过下载，复用已有订阅: ${SUB_FILE}"
elif [[ "${CLASH_SUB_SKIP_DOWNLOAD:-}" == "1" ]] && _sub_looks_valid "${SUB_FILE}"; then
  echo "ERROR: ${SUB_FILE} 存在但无代理节点（可能是 403 时留下的空壳配置）"
  _sub_diag "${SUB_FILE}"
  echo "请删除后上传本机下载的完整订阅:"
  echo "  rm -f ${SUB_FILE}"
  echo "  scp subscription.yaml root@服务器:${SUB_FILE}"
  echo "  export CLASH_SUB_SKIP_DOWNLOAD=1"
  echo "  DAEMON=1 bash backpack_quant_trading/tools/proxy/start_clash.sh"
  exit 1
elif _download_clash_sub "${CLASH_SUB_URL}" "${SUB_FILE}"; then
  echo "订阅下载成功"
elif _sub_looks_valid "${SUB_FILE}" && _sub_has_proxy_nodes "${SUB_FILE}"; then
  echo "WARN: 订阅下载失败（常见 403：机房 IP 被订阅站拦截），复用已有 ${SUB_FILE}"
  echo "      若节点过旧，请在本机浏览器下载订阅后执行:"
  echo "      scp subscription.yaml root@服务器:/root/.config/mihomo/subscription.yaml"
  echo "      或 export CLASH_SUB_FILE=/path/to/subscription.yaml"
  if [[ -f "${SUB_LOG}" ]]; then
    echo "      最近错误: $(tr '\n' ' ' <"${SUB_LOG}" | head -c 180)"
  fi
else
  echo "ERROR: 无法下载订阅，且本地无可用 ${SUB_FILE}"
  echo "云服务器常被订阅站返回 403，请在本机电脑操作:"
  echo "  1) 浏览器打开订阅链接，保存为 subscription.yaml"
  echo "  2) scp subscription.yaml root@你的服务器:/root/.config/mihomo/subscription.yaml"
  echo "  3) export CLASH_SUB_SKIP_DOWNLOAD=1"
  echo "  4) bash backpack_quant_trading/tools/proxy/start_clash.sh"
  echo "或: export CLASH_SUB_FILE=/path/to/subscription.yaml"
  if [[ -f "${SUB_LOG}" ]]; then
    echo "curl 详情: $(tr '\n' ' ' <"${SUB_LOG}" | head -c 240)"
  fi
  exit 1
fi

# ─── 基础校验：避免订阅返回 HTML/报错页导致“启动后全直连” ────────────────
if ! _sub_looks_valid "${SUB_FILE}"; then
  echo "ERROR: 订阅内容无效（空文件、HTML 或缺少 proxies/rules 字段）"
  _sub_diag "${SUB_FILE}" 2>/dev/null || true
  echo "请用 CLASH_SUB_FILE 或 scp 上传正确的 subscription.yaml"
  exit 1
fi
if ! _sub_has_proxy_nodes "${SUB_FILE}"; then
  echo "ERROR: 订阅无代理节点（proxies 为空）"
  _sub_diag "${SUB_FILE}"
  echo "删除坏文件后重新上传本机下载的订阅:"
  echo "  rm -f ${SUB_FILE}"
  echo "  scp subscription.yaml root@服务器:${SUB_FILE}"
  exit 1
fi

echo "[2/4] 生成 ${CFG_FILE}（mixed-port 固定 ${MIXED_PORT}，忽略订阅里的端口）"
# 给 Python 片段提供真实路径与端口（避免 here-doc 单引号导致 ${VAR} 不展开）
# 关键：必须 export MIXED_PORT，否则 Python 会用默认 7890 写进配置
export SUB_FILE CFG_FILE MIXED_PORT CLASH_MODE CLASH_LOG_LEVEL CTRL_ADDR
# 订阅文件可能有两种形态：
# - A) 完整 Clash 配置（顶层是 map，包含 proxies/proxy-groups/rules 等）
# - B) 仅节点列表（用于 proxy-providers 的文件，顶层通常是 list 或仅 proxies 列表）
#
# 你的 subscription.yaml（1745 行）属于 A) 完整配置，因此不能当作 proxy-providers 的“列表”解析。
# 这里做自动识别：若是完整配置 → 作为 config.yaml 使用，并覆盖端口/控制器；否则 → 走 provider 方式。
python3 - <<'PY'
import os
from pathlib import Path
import re

sub_file = Path(os.environ["SUB_FILE"])
cfg_file = Path(os.environ["CFG_FILE"])
mixed_port = int(os.getenv("MIXED_PORT", "7890"))
clash_sub_url = os.getenv("CLASH_SUB_URL", "")
clash_mode = os.getenv("CLASH_MODE", "rule").strip() or "rule"
clash_log_level = os.getenv("CLASH_LOG_LEVEL", "info").strip() or "info"
ctrl_addr = os.getenv("CTRL_ADDR", "127.0.0.1:9090").strip() or "127.0.0.1:9090"

text = sub_file.read_text(encoding="utf-8", errors="ignore")

def looks_like_full_config(t: str) -> bool:
    # 粗判：完整配置一般会出现这些 key
    keys = ("proxy-groups:", "rules:", "proxies:", "rule-providers:", "proxy-providers:")
    return sum(1 for k in keys if k in t) >= 3

def normalize_empty_proxies(t: str) -> str:
    # 某些订阅会把空列表输出成 `{}`，但 mihomo 期望是 `[]`
    # 典型：`proxies: {}`、`proxies: {  }` 以及内联 map 里的 `proxies: { }`
    t = re.sub(r"proxies:\s*\{\s*\}", "proxies: []", t)
    return t

def has_any_real_proxy_nodes(t: str) -> bool:
    if re.search(r"^proxy-providers:\s*$", t, re.M):
        return True
    if re.search(r"^proxies:\s*\[\s*\]", t, re.M):
        return False
    in_proxies = False
    for line in t.splitlines():
        if re.match(r"^proxies:\s*$", line):
            in_proxies = True
            continue
        if not in_proxies:
            continue
        if line and line[0] not in " \t" and re.match(r"^[A-Za-z0-9_-]+:", line):
            break
        if re.match(r"^\s+-\s+", line) and "name" in line:
            return True
    return False

def normalize_empty_group_members(t: str) -> str:
    # 部分订阅把 proxy-groups 的 proxies/use 输出为空（[] 或 {}），mihomo 会直接报错：
    # `use` or `proxies` missing
    # 这里做一个保底：若某个 group 的 `proxies: []`（常见于 url-test/select）就塞一个直连组名，
    # 避免启动即失败。你后续仍可在面板里切换到真实节点组。
    #
    # 仅处理 inline map 风格：- { name: 'xxx', type: url-test, proxies: [], ... }
    t = re.sub(
        r"(type:\s*(?:select|url-test|fallback|load-balance)[^}]*?,\s*proxies:\s*)\[\s*\]",
        r"\1['🚀 直连']",
        t,
    )
    # 同样把 proxies: {} 转成 ['🚀 直连']
    t = re.sub(
        r"(type:\s*(?:select|url-test|fallback|load-balance)[^}]*?,\s*proxies:\s*)\{\s*\}",
        r"\1['🚀 直连']",
        t,
    )
    return t

def strip_dns_section(t: str) -> str:
    """去掉订阅里的 dns 段，避免抢系统 53 端口导致异常。"""
    lines = t.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if not skipping and re.match(r"^dns:\s*$", line):
            skipping = True
            continue
        if skipping:
            if line and line[0] not in " \t" and re.match(r"^[A-Za-z0-9_-]+:", line):
                skipping = False
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"

def strip_top_level_lines(t: str) -> str:
    # 去掉常见顶层配置，避免重复 key；我们会在末尾强制写入一组“可控”的配置
    drop = (
        r"^(mixed-port|port|socks-port|redir-port|tproxy-port|external-controller)\s*:\s*.*$",
        r"^(mode|log-level|ipv6)\s*:\s*.*$",
    )
    lines = []
    for line in t.splitlines():
        # 只移除“顶层 key”（不允许有缩进），避免误删 proxies 里的 port 字段
        if line and line[0].isspace():
            lines.append(line)
            continue
        if any(re.match(p, line) for p in drop):
            continue
        lines.append(line)
    return "\n".join(lines).strip() + "\n"

if looks_like_full_config(text):
    # 直接用订阅作为主配置，并强制覆写端口/控制器
    cleaned = normalize_empty_group_members(
        normalize_empty_proxies(strip_dns_section(strip_top_level_lines(text)))
    )
    if not has_any_real_proxy_nodes(cleaned):
        raise SystemExit(
            "ERROR: 订阅配置不包含任何代理节点（proxies 为空且无 proxy-providers）。\n"
            "这会导致 mihomo 只能走 DIRECT，表现为 curl CONNECT 200 后 TLS 握手失败。\n"
            "解决：请换一个包含节点的订阅链接，或在本地下载正确的 subscription.yaml 后上传，\n"
            "然后在服务器上设置：export CLASH_SUB_FILE=/root/subscription.yaml 再运行脚本。"
        )
    # 说明：
    # - 强制 mixed-port 与 controller，避免端口不一致
    # - 强制 log-level=info：否则订阅给 silent 时排障几乎不可能
    # - 强制 ipv6=false：大量云服务器 IPv6 不通/不完整，会导致 TLS 握手阶段直接失败（常见 SSL_ERROR_SYSCALL）
    # - mode 可用 CLASH_MODE=global 临时切换，快速验证“规则导致直连/DIRECT”的可能
    cleaned += (
        f"\nmixed-port: {mixed_port}\n"
        f"external-controller: {ctrl_addr}\n"
        f"log-level: {clash_log_level}\n"
        f"ipv6: false\n"
        f"mode: {clash_mode}\n"
    )
    cfg_file.write_text(cleaned, encoding="utf-8")
else:
    # provider 模式：生成最小 wrapper 配置
    if not clash_sub_url:
        raise SystemExit("provider 模式需要设置 CLASH_SUB_URL（或使用完整订阅配置文件）")
    wrapper = f"""mixed-port: {mixed_port}
allow-lan: false
mode: rule
log-level: info
external-controller: {ctrl_addr}

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
    url: {clash_sub_url}
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
"""
    cfg_file.write_text(wrapper, encoding="utf-8")
PY

# ─── 启动前端口占用检测（避免“其实是旧进程还在跑”）───────────────────────────
is_listening() {
  local p="$1"
  # shellcheck disable=SC2009
  ss -tlnp 2>/dev/null | grep -qE ":[[:space:]]*${p}[[:space:]]"
}

CTRL_PORT="${CTRL_ADDR##*:}"
if is_listening "${CTRL_PORT}"; then
  echo "WARN: 控制器端口 ${CTRL_ADDR} 已被占用（可能已有 mihomo 在运行）。"
  echo "建议：先停掉旧进程：pkill -f \"mihomo\" 或改用 CTRL_ADDR/端口。"
fi
if is_listening "${MIXED_PORT}"; then
  echo "WARN: mixed-port ${MIXED_PORT} 已被占用（可能已有 mihomo 在运行）。"
  echo "建议：先停掉旧进程：pkill -f \"mihomo\" 或 export MIXED_PORT=另一个端口。"
fi

# ─── 准备 GeoIP MMDB（避免 mihomo 启动时在线下载失败直接退出）───────────────
# 你的订阅规则包含 GEOIP,CN,...，如果缺少 Country.mmdb，mihomo 会尝试下载；
# 但云服务器常常拉不下来（timeout / reset），会导致“Parse config error”并退出。
MMDB_FILE="${CONFIG_DIR}/Country.mmdb"
is_valid_mmdb() {
  # 经验校验：有效的 MMDB 文件通常能在二进制中找到 "MaxMind.com" 标记
  # 若下载到的是 HTML/报错页/空文件，一般不包含该标记
  [[ -f "$1" ]] && [[ -s "$1" ]] && strings "$1" 2>/dev/null | grep -q "MaxMind.com"
}

if [[ ! -f "${MMDB_FILE}" ]]; then
  echo "[2.5/4] 准备 GeoIP 数据库 ${MMDB_FILE}"
  if [[ -n "${CLASH_MMDB_FILE:-}" ]]; then
    echo "使用本地 MMDB 文件: ${CLASH_MMDB_FILE}"
    cp -f "${CLASH_MMDB_FILE}" "${MMDB_FILE}"
  else
    echo "尝试在线下载 country-lite.mmdb（失败可改用本地下载后上传）"
    URLS=(
      "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/country-lite.mmdb"
      "https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country-lite.mmdb"
      "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country-lite.mmdb"
    )
    ok=0
    for u in "${URLS[@]}"; do
      if curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 "$u" -o "${MMDB_FILE}"; then
        if is_valid_mmdb "${MMDB_FILE}"; then
          ok=1
          break
        fi
        echo "下载到的 MMDB 无效（可能是 HTML/拦截页），删除后尝试下一个源..."
        rm -f "${MMDB_FILE}"
      fi
    done
    if [[ "${ok}" != "1" ]]; then
      echo "ERROR: 在线下载 MMDB 失败，mihomo 会因 GEOIP 规则无法启动。"
      echo "解决：在你本地电脑下载 country-lite.mmdb，然后 scp 上传到服务器，再设置 CLASH_MMDB_FILE。"
      echo "本地下载地址（任选其一）："
      echo "  1) https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/country-lite.mmdb"
      echo "  2) https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country-lite.mmdb"
      echo "上传后在服务器执行："
      echo "  export CLASH_MMDB_FILE=/root/country-lite.mmdb"
      echo "  bash ./start_clash.sh"
      exit 1
    fi
  fi
fi

# 若文件存在但无效，直接提示用本地替换，避免 mihomo 自己反复下载卡死
if [[ -f "${MMDB_FILE}" ]] && ! is_valid_mmdb "${MMDB_FILE}"; then
  echo "ERROR: 检测到 ${MMDB_FILE} 不是有效 MMDB（mihomo 会报 'MMDB invalid' 并尝试下载）。"
  echo "请删除它并改用本地上传的 country-lite.mmdb："
  echo "  rm -f ${MMDB_FILE}"
  echo "  export CLASH_MMDB_FILE=/root/country-lite.mmdb"
  echo "  bash ./start_clash.sh"
  exit 1
fi

echo "[3/4] 准备 mihomo 二进制"
if [[ ! -x "${MIHOMO_BIN}" ]]; then
  # 说明：GitHub “latest/download/xxx” 的资产名经常变动，所以这里动态解析最新 tag
  # 然后按常见命名规则拼出下载链接：
  # - mihomo-linux-amd64-v<ver>.gz
  # - mihomo-linux-amd64-compatible-v<ver>.gz
  TAG="${MIHOMO_TAG:-}"
  if [[ -z "${TAG}" ]]; then
    TAG="$(curl -fsSL https://api.github.com/repos/MetaCubeX/mihomo/releases/latest | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")"
  fi
  VER="${TAG#v}"
  URL1="https://github.com/MetaCubeX/mihomo/releases/download/${TAG}/mihomo-linux-amd64-compatible-${TAG}.gz"
  URL2="https://github.com/MetaCubeX/mihomo/releases/download/${TAG}/mihomo-linux-amd64-compatible-v${VER}.gz"
  URL3="https://github.com/MetaCubeX/mihomo/releases/download/${TAG}/mihomo-linux-amd64-${TAG}.gz"
  URL4="https://github.com/MetaCubeX/mihomo/releases/download/${TAG}/mihomo-linux-amd64-v${VER}.gz"

  MIHOMO_URL="${MIHOMO_URL:-}"
  if [[ -z "${MIHOMO_URL}" ]]; then
    echo "检测到最新版本: ${TAG}"
    echo "尝试下载 mihomo 资产..."
  else
    echo "使用自定义 MIHOMO_URL: ${MIHOMO_URL}"
  fi
  tmp_gz="$(mktemp)"
  if [[ -n "${MIHOMO_URL}" ]]; then
    curl -fL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 180 "${MIHOMO_URL}" -o "${tmp_gz}"
  else
    # 依次尝试常见命名
    if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 "${URL1}" -o "${tmp_gz}" \
      && ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 "${URL2}" -o "${tmp_gz}" \
      && ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 "${URL3}" -o "${tmp_gz}" \
      && ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 "${URL4}" -o "${tmp_gz}"; then
      echo "GitHub 下载失败，尝试 SourceForge 镜像..."
      SF1="https://sourceforge.net/projects/mihomo.mirror/files/${TAG}/mihomo-linux-amd64-compatible-${TAG}.gz/download"
      SF2="https://sourceforge.net/projects/mihomo.mirror/files/${TAG}/mihomo-linux-amd64-compatible-v${VER}.gz/download"
      SF3="https://sourceforge.net/projects/mihomo.mirror/files/${TAG}/mihomo-linux-amd64-${TAG}.gz/download"
      SF4="https://sourceforge.net/projects/mihomo.mirror/files/${TAG}/mihomo-linux-amd64-v${VER}.gz/download"
      if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 240 "${SF1}" -o "${tmp_gz}" \
        && ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 240 "${SF2}" -o "${tmp_gz}" \
        && ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 240 "${SF3}" -o "${tmp_gz}" \
        && ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 240 "${SF4}" -o "${tmp_gz}"; then
      echo "ERROR: 下载 mihomo 失败。你可以："
      echo "  1) 设置 MIHOMO_URL 指向可下载的 .gz"
      echo "  2) 或手动安装后放到 ${MIHOMO_BIN}"
      exit 1
      fi
    fi
  fi
  gzip -dc "${tmp_gz}" > "${MIHOMO_BIN}"
  chmod +x "${MIHOMO_BIN}"
  rm -f "${tmp_gz}"
else
  echo "已存在: ${MIHOMO_BIN}"
fi

echo "[4/4] 启动 mihomo"
echo "配置目录: ${CONFIG_DIR}"
MIHOMO_LOG="${CONFIG_DIR}/mihomo.log"

if [[ "${DAEMON:-}" == "1" ]]; then
  if pgrep -f "${MIHOMO_BIN}" >/dev/null 2>&1; then
    echo "停止已有 mihomo，用新 config.yaml 在 ${MIXED_PORT} 重启..."
    pkill -f "${MIHOMO_BIN}" 2>/dev/null || true
    sleep 2
  fi
  nohup "${MIHOMO_BIN}" -d "${CONFIG_DIR}" -f "${CFG_FILE}" >>"${MIHOMO_LOG}" 2>&1 &
  pid=$!
  echo "mihomo 后台启动 pid=${pid}，日志: ${MIHOMO_LOG}"
  for i in $(seq 1 8); do
    sleep 1
    if is_listening "${MIXED_PORT}"; then
      echo "mixed-port ${MIXED_PORT} 已监听"
      exit 0
    fi
  done
  echo "WARN: 启动后端口未就绪，查看日志: tail -30 ${MIHOMO_LOG}"
  exit 1
fi

echo "提示：后台启动: DAEMON=1 bash $0"
exec "${MIHOMO_BIN}" -d "${CONFIG_DIR}" -f "${CFG_FILE}"


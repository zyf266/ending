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

echo "[1/4] 下载订阅到 ${SUB_FILE}"
# 若订阅站点对 curl/机房 IP 有限制，可能返回 403。
# 处理策略：
# - 支持通过 CLASH_SUB_FILE 指向本地订阅文件（跳过下载）
# - 否则下载失败时，带浏览器 UA 再重试一次
if [[ -n "${CLASH_SUB_FILE:-}" ]]; then
  echo "使用本地订阅文件: ${CLASH_SUB_FILE}"
  cp -f "${CLASH_SUB_FILE}" "${SUB_FILE}"
else
  if ! curl -fsSL "${CLASH_SUB_URL}" -o "${SUB_FILE}"; then
    echo "订阅下载失败，尝试携带浏览器 UA 重试..."
    UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    curl -fsSL -A "${UA}" "${CLASH_SUB_URL}" -o "${SUB_FILE}"
  fi
fi

# ─── 基础校验：避免订阅返回 HTML/报错页导致“启动后全直连” ────────────────
if [[ ! -s "${SUB_FILE}" ]]; then
  echo "ERROR: 订阅文件为空：${SUB_FILE}"
  echo "可能原因：订阅链接失效/403/机房 IP 被限制/网络问题。"
  exit 1
fi

# 常见：订阅站返回 HTML、JSON 报错、或纯文本提示；这种内容会被当 YAML 读入但不会产生任何节点
if head -n 5 "${SUB_FILE}" | tr -d '\r' | grep -qiE '<!doctype html|<html|access denied|forbidden|unauthorized|登录|subscribe|token|expired'; then
  echo "ERROR: 订阅内容疑似为 HTML/错误页（不是 Clash YAML）。"
  echo "请在服务器上直接查看订阅返回是否正常，或改用 CLASH_SUB_FILE 指向本地正确的 subscription.yaml。"
  exit 1
fi

# 粗判 YAML 形态：至少要包含 proxies/proxy-groups/rules 等关键字之一
if ! grep -qE '^(proxies:|proxy-groups:|proxy-providers:|rules:|rule-providers:)' "${SUB_FILE}"; then
  echo "ERROR: 订阅内容看起来不像 Clash 配置（未发现 proxies/proxy-groups/rules 等关键字段）。"
  echo "建议：检查订阅链接是否返回了加密/压缩/非 YAML 内容，或使用 CLASH_SUB_FILE 传入已解码的 YAML。"
  exit 1
fi

echo "[2/4] 生成 ${CFG_FILE}"
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
    # 订阅常见坑：返回的是“托管配置壳子”（MANAGED-CONFIG），proxies 为空，
    # 且也没有 proxy-providers；这种情况下 mihomo 只能 DIRECT，表现为 CONNECT 200 后 TLS 立刻断。
    # 我们用一个保守判定：出现 `proxies:` 且其下至少有一个 `- name:` 才认为有节点。
    #（不解析 YAML，避免依赖；用文本规则足够抓住该坑）
    if re.search(r"^proxy-providers:\s*$", t, re.M):
        return True  # provider 模式可能没在 proxies 里展开
    return bool(re.search(r"^proxies:\s*$\s*(?:-\s*name:|\s*-\s*\{[^}]*name\s*:)", t, re.M))

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
    cleaned = normalize_empty_group_members(normalize_empty_proxies(strip_top_level_lines(text)))
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

echo "[4/4] 启动 mihomo（前台）"
echo "提示：可用 tmux/nohup 让其后台常驻"
echo "配置目录: ${CONFIG_DIR}"
exec "${MIHOMO_BIN}" -d "${CONFIG_DIR}" -f "${CFG_FILE}"


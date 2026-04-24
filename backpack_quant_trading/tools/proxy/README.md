## 云服务器代理（Clash / Mihomo）

为避免将订阅链接写入仓库（容易泄露），此目录提供脚本：在服务器运行时下载订阅配置并启动 Clash(Mihomo)，然后用环境变量让本项目的 API 进程走代理。

### 1) 准备：设置订阅链接（仅在服务器上）

在你的云服务器执行（把订阅链接用引号包起来）：

```bash
export CLASH_SUB_URL="<<你的clash订阅链接>>"
```

建议写入 `~/.bashrc` 或 systemd 环境文件，避免重登丢失。

### 2) 启动 Clash（Mihomo）

```bash
bash backpack_quant_trading/tools/proxy/start_clash.sh
```

脚本会：
- 下载订阅到 `~/.config/mihomo/subscription.yaml`
- 生成/覆盖 `~/.config/mihomo/config.yaml`（端口默认 `7890`）
- 下载（或复用）`mihomo` 二进制到 `~/.local/bin/mihomo`
- 前台启动 mihomo（你可用 `nohup`/`tmux` 让它后台常驻）

### 3) 让 API 进程走代理启动

```bash
bash backpack_quant_trading/tools/proxy/start_api_with_proxy.sh
```

它会设置：
- `HTTP_PROXY=http://127.0.0.1:7890`
- `HTTPS_PROXY=http://127.0.0.1:7890`
- `ALL_PROXY=socks5://127.0.0.1:7890`

然后执行 `python -m backpack_quant_trading.run_api`。

### 4) 验证

在服务器上：

```bash
curl -I https://www.google.com
curl -4 https://api.ip.sb/ip
```

如果能通且 IP 变成代理出口，则 OK。


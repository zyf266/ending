## 云服务器代理（Clash / Mihomo）

端口固定 **7891**（与 `start_trading_stack.sh` 一致），订阅文件里的 `mixed-port` 会被忽略。

### 1) 本机下载订阅，上传到服务器

```bash
scp subscription.yaml root@服务器:/root/.config/mihomo/subscription.yaml
```

### 2) 启动 mihomo（7891 已在跑则跳过）

```bash
export CLASH_SUB_SKIP_DOWNLOAD=1
DAEMON=1 bash backpack_quant_trading/tools/proxy/start_clash.sh
```

### 3) 验证 + 启动交易栈

```bash
curl -x http://127.0.0.1:7891 https://fapi.binance.com/fapi/v1/ping
bash backpack_quant_trading/tools/start_trading_stack.sh
```

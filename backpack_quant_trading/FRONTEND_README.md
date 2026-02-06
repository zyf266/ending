# Backpack 量化交易终端 - FastAPI + Vue3

前端已迁移至 **FastAPI + Vue3 + Element Plus** 技术栈。

## 目录结构

```
backpack_quant_trading/
├── api/                    # FastAPI 后端
│   ├── main.py            # 入口
│   ├── deps.py            # 认证等依赖
│   └── routers/           # API 路由
│       ├── auth.py
│       ├── grid.py
│       ├── currency_monitor.py
│       └── ...
└── frontend/              # Vue3 前端
    ├── src/
    │   ├── views/        # 页面
    │   ├── api/          # API 封装
    │   ├── stores/       # Pinia 状态
    │   └── router/       # 路由
    └── package.json
```

## 启动方式

### 1. 安装依赖

```bash
# 后端
pip install -r backpack_quant_trading/requirements.txt

# 前端
cd backpack_quant_trading/frontend
npm install
```

### 2. 开发模式（前后端分离）

```bash
# 终端 1：启动 FastAPI 后端
cd backpack_quant_trading
python run_api.py
# 或: uvicorn backpack_quant_trading.api.main:app --reload --port 8000

# 终端 2：启动 Vue 开发服务器
cd backpack_quant_trading/frontend
npm run dev
# 访问 http://localhost:5173
```

Vite 会将 `/api` 代理到 `http://127.0.0.1:8000`，无需额外 CORS 配置。

### 3. 生产模式（单端口）

```bash
cd backpack_quant_trading/frontend
npm run build

cd ..
python run_api.py
# 访问 http://localhost:8000（后端会挂载 frontend/dist）
```

## API 文档

启动后端后访问：http://localhost:8000/docs

## 主要页面（功能已全部迁移）

- `/login` - 登录 / 注册
- `/trading` - 实盘交易：增加策略弹窗、实例列表、停止、实时日志（Backpack/Deepcoin 子进程，Ostium/Hyper Webhook）
- `/dashboard` - 数据大屏：组合概览、净值曲线、持仓、订单、成交、风险事件
- `/ai-lab` - AI 自适应实验室：K 线截图上传、抓取 ETH 行情、AI 综合分析、K 线图表
- `/grid-trading` - 合约网格：配置、启动、停止、实例列表
- `/currency-monitor` - 币种监视：币种选择、监视启动/停止、异动池

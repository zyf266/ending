import sys
import os
import subprocess
import json
import socket
import time
import psutil
import requests  # 添加 requests 库用于调用 Webhook API
import asyncio
import logging
from pathlib import Path

# --- 【终极修复】解决 Python 3.9+ 多线程下 asyncio 事件循环缺失报错 ---
class SafeEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def get_event_loop(self):
        try:
            return super().get_event_loop()
        except RuntimeError:
            loop = self.new_event_loop()
            self.set_event_loop(loop)
            return loop

asyncio.set_event_loop_policy(SafeEventLoopPolicy())
# --------------------------------------------------------------------

# 配置日志
logger = logging.getLogger(__name__)

# 添加项目根目录到Python路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import dash
from dash import dcc, html, Input, Output, State, callback_context, ALL, MATCH
import plotly.graph_objs as go
from backpack_quant_trading.core.ai_adaptive import AIAdaptive
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from werkzeug.security import generate_password_hash, check_password_hash
from web3 import Web3

# 导入配置
from backpack_quant_trading.config.settings import config
from backpack_quant_trading.database.models import DatabaseManager, db_manager, UserInstance
from backpack_quant_trading.main import STRATEGY_REGISTRY, EXCHANGE_REGISTRY, STRATEGY_DISPLAY_NAMES
from backpack_quant_trading.core.binance_monitor import (
    fetch_binance_symbols_usdt,
    BinanceMonitorService,
    get_monitor_instance,
    set_monitor_instance,
    send_dingtalk_alert,
)

# --- 精调 UI 颜色方案 (高级亮色主题) ---
COLORS = {
    'bg': '#F0F2F5',         # 浅灰底色
    'sidebar': '#FFFFFF',    # 纯白侧边栏
    'card': '#FFFFFF',       # 纯白卡片
    'text': '#1F2937',       # 深灰文字
    'text_dim': '#6B7280',   # 辅助文字
    'accent': '#F0B90B',     # 品牌金
    'success': '#10B981',    # 成功绿
    'danger': '#EF4444',     # 危险红
    'border': '#E5E7EB',     # 边框
    'shadow': '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)'
}

# 共享样式
CARD_STYLE = {
    'backgroundColor': COLORS['card'],
    'borderRadius': '12px',
    'padding': '24px',
    'marginBottom': '24px',
    'border': '1px solid ' + COLORS['border'],
    'color': COLORS['text'],
    'boxShadow': COLORS['shadow']
}

MODAL_BASE_STYLE = {
    'position': 'fixed',
    'zIndex': '9999',
    'left': '0',
    'top': '0',
    'width': '100%',
    'height': '100%',
    'backgroundColor': 'rgba(0,0,0,0.5)',
    'backdropFilter': 'blur(10px)',
    'alignItems': 'center',
    'justifyContent': 'center'
}

INPUT_STYLE = {
    'backgroundColor': '#F9FAFB',
    'border': '1px solid ' + COLORS['border'],
    'color': COLORS['text'],
    'padding': '14px 18px',  # 缩小一半：28px 36px -> 14px 18px
    'borderRadius': '5px',  # 缩小一半：10px -> 5px
    'width': '100%',
    'fontSize': '12.5px'  # 缩小一半：25px -> 12.5px
}

# 使用MySQL数据库连接
print(f"[DEBUG] 数据库URL: {config.database_url}")
engine = create_engine(config.database_url)

# 确保 user_instances 表存在（用于实例持久化与账户隔离）
try:
    UserInstance.__table__.create(engine, checkfirst=True)
except Exception as e:
    logger.warning(f"创建 user_instances 表失败（可忽略）: {e}")

# 使用 React 16 避免 React 18 与 Dash/Plotly 组件的兼容性问题（空白页、Object 错误）
try:
    dash._dash_renderer._set_react_version("16.14.0")
except Exception:
    pass

app = dash.Dash(
    __name__, 
    title='Backpack量化交易终端', 
    suppress_callback_exceptions=True,
    update_title='加载中...',
    serve_locally=True  # 本地加载，避免 CDN 慢；若遇空白页可尝试改为 False
)
app.scripts.config.serve_locally = True
app.css.config.serve_locally = True
server = app.server

# 注入全局自定义CSS
app.index_string = f'''
<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
        <style>
            body {{
                margin: 0;
                background-color: #F0F2F5 !important;
                color: #1F2937;
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 24px; /* 缩小一半：48px -> 24px */
            }}
            .sidebar {{
                position: fixed;
                top: 0; left: 0; bottom: 0;
                width: 220px; /* 减小宽度：500px -> 220px */
                background-color: #FFFFFF;
                border-right: 1px solid #E5E7EB;
                padding: 20px 16px; /* 减小内边距：60px 40px -> 20px 16px */
                z-index: 1001;
                box-shadow: 2px 0 8px rgba(0,0,0,0.05);
                overflow-y: auto;
                height: 100vh; /* 确保高度一致 */
                display: flex;
                flex-direction: column; /* 使用 flex 布局确保高度一致 */
            }}
            .content {{
                margin-left: 220px; /* 匹配侧边栏宽度 */
                background-color: #F0F2F5;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
            }}
            .top-header {{
                height: 65px; /* 缩小一半：130px -> 65px */
                background-color: #FFFFFF !important;
                border-bottom: 1px solid #E5E7EB;
                display: flex;
                align-items: center;
                justify-content: flex-end;
                padding: 0 35px; /* 缩小：70px -> 35px */
                position: sticky;
                top: 0;
                z-index: 1000;
            }}
            .page-container {{
                padding: 30px 40px; /* 缩小一半：60px 80px -> 30px 40px */
                flex: 1;
                max-width: 100%;
                overflow-x: hidden;
            }}
            .nav-link {{
                color: #6B7280;
                text-decoration: none;
                padding: 10px 11px; /* 缩小一半：20px 22px -> 10px 11px */
                border-radius: 5px;
                margin-bottom: 4px;
                display: flex;
                align-items: center;
                transition: all 0.2s;
                font-size: 14px; /* 缩小一半：28px -> 14px */
                font-weight: 500;
            }}
            .nav-link:hover {{ background-color: #F9FAFB; color: #111827; }}
            .nav-link.active {{ background-color: rgba(240, 185, 11, 0.1); color: #F0B90B; font-weight: 600; }}
            
            .card-tech {{
                background-color: #FFFFFF;
                border-radius: 8px; /* 缩小：16px -> 8px */
                padding: 20px; /* 缩小一半：40px -> 20px */
                border: 1px solid #E5E7EB;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }}
            
            .btn-primary {{
                background-color: #F0B90B;
                border: none;
                color: #FFFFFF;
                font-weight: 600;
                padding: 12px 24px; /* 缩小一半：24px 48px -> 12px 24px */
                border-radius: 5px;
                cursor: pointer;
                transition: all 0.2s;
                font-size: 16px; /* 缩小一半：32px -> 16px */
            }}
            .btn-primary:hover {{ opacity: 0.9; transform: translateY(-1px); }}
                        
            .btn-danger {{
                background-color: #EF4444;
                border: none;
                color: #FFFFFF;
                font-weight: 600;
                padding: 10px 20px; /* 缩小一半：20px 40px -> 10px 20px */
                border-radius: 5px;
                cursor: pointer;
                transition: all 0.2s;
                font-size: 14px; /* 缩小一半：28px -> 14px */
            }}
            .btn-danger:hover {{ opacity: 0.9; transform: translateY(-1px); }}
            
            .strategy-instance-card {{
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px; /* 缩小：16px -> 8px */
                padding: 18px; /* 缩小一半：35px -> 18px */
                margin-bottom: 12px; /* 缩小：24px -> 12px */
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                border-left: 3px solid #F0B90B; /* 缩小：6px -> 3px */
            }}
            
            /* 表格样式优化 */
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 14px; /* 缩小一半：28px -> 14px */
            }}
            th {{
                padding: 10px 8px; /* 缩小一半：20px 16px -> 10px 8px */
                text-align: left;
                font-weight: 600;
                font-size: 15px; /* 缩小一半：30px -> 15px */
                border-bottom: 2px solid #E5E7EB;
            }}
            td {{
                padding: 9px 8px; /* 缩小一半：18px 16px -> 9px 8px */
                border-bottom: 1px solid #E5E7EB;
                font-size: 14px; /* 缩小一半：28px -> 14px */
            }}
            
            /* 下拉框亮色适配 - 缩小尺寸 */
            .Select-control {{ 
                background-color: #F9FAFB !important; 
                border-color: #E5E7EB !important; 
                height: 40px !important;  /* 缩小一半：80px -> 40px */
                font-size: 16px !important;  /* 缩小一半：32px -> 16px */
            }}
            .Select-value-label {{ 
                color: #1F2937 !important; 
                line-height: 40px !important;  /* 匹配高度 */
                font-size: 16px !important;
            }}
            .Select-placeholder {{ 
                line-height: 40px !important;
                font-size: 16px !important;
            }}
            .Select-menu-outer {{ 
                background-color: #FFFFFF !important; 
                border-color: #E5E7EB !important; 
                font-size: 16px !important;
            }}
            .Select-option {{
                font-size: 16px !important;  /* 缩小一半：32px -> 16px */
                padding: 10px 12px !important;  /* 缩小一半：20px 24px -> 10px 12px */
            }}
            
            pre {{
                background-color: #F9FAFB !important;
                color: #374151 !important;
                border: 1px solid #E5E7EB !important;
            }}
        </style>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>
'''


app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='current-user-store', storage_type='session'),
    dcc.Store(id='control-log-store', storage_type='memory'),
    dcc.Store(id='active-instances', data=[], storage_type='session'),
    dcc.Interval(id='instance-monitor', interval=5000, n_intervals=0), 
    dcc.Interval(id='balance-refresher', interval=15000, n_intervals=0),
    dcc.Interval(id='interval-component', interval=10000, n_intervals=0), # 通用刷新 (10s)
    dcc.Interval(id='balance-interval', interval=30000, n_intervals=0),    # 余额刷新 (30s)
    
    dcc.ConfirmDialog(id='startup-success-dialog', message='🚀 策略已成功启动！'),
    
    # 增加策略弹窗
    html.Div(id='add-strategy-modal', style={**MODAL_BASE_STYLE, 'display': 'none'}, children=[
        html.Div(style={
            'backgroundColor': 'white', 
            'padding': '35px',  # 缩小一半：70px -> 35px
            'borderRadius': '20px',  # 缩小一半：40px -> 20px
            'width': '700px',  # 缩小一半：1400px -> 700px
            'maxWidth': '95vw',
            'maxHeight': '90vh', 
            'overflowY': 'auto', 
            'boxShadow': '0 15px 30px -8px rgba(0,0,0,0.35)'  # 缩小阴影
        }, children=[
            html.H2("配置并启动实盘策略", style={
                'marginBottom': '20px',  # 缩小一半：40px -> 20px
                'fontWeight': '800', 
                'fontSize': '28px',  # 缩小一半：56px -> 28px
                'textAlign': 'center'
            }),
            
            html.Div([
                # 第一排：平台与策略
                html.Div([
                    html.Div([
                        html.Label("交易平台", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',  # 缩小一半：12px -> 6px
                            'display': 'block',
                            'fontSize': '16px'  # 缩小一半：32px -> 16px
                        }),
                        dcc.Dropdown(
                            id='modal-platform', 
                            options=[{'label': k.capitalize(), 'value': k} for k in EXCHANGE_REGISTRY.keys()], 
                            value='backpack',
                            style={'fontSize': '14px'}  # 缩小一半：16px -> 14px
                        ),
                    ], style={'flex': '1', 'marginRight': '12px'}),  # 缩小一半：24px -> 12px
                    html.Div([
                        html.Label("交易策略", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',  # 缩小一半：12px -> 6px
                            'display': 'block',
                            'fontSize': '16px'  # 缩小一半：32px -> 16px
                        }),
                        dcc.Dropdown(
                            id='modal-strategy', 
                            options=[{'label': STRATEGY_DISPLAY_NAMES.get(k, k), 'value': k} for k in STRATEGY_REGISTRY.keys()], 
                            value='mean_reversion',
                            style={'fontSize': '14px'}  # 缩小一半：16px -> 14px
                        ),
                    ], style={'flex': '1'}),
                ], style={'display': 'flex', 'marginBottom': '12px'}),  # 缩小一半：24px -> 12px

                # 密钥区域 (高度一致性适配)
                html.Div(id='modal-credentials-container', children=[
                    # Backpack / Deepcoin 共有
                    html.Div(id='modal-creds-common', children=[
                        html.Div([
                            html.Label("API Key", style={
                                'fontWeight': '700', 
                                'marginBottom': '6px',  # 缩小一半：12px -> 6px
                                'display': 'block',
                                'fontSize': '16px'  # 缩小一半：32px -> 16px
                            }),
                            dcc.Input(id='modal-api-key', type='text', placeholder='输入 API Key', style=INPUT_STYLE),
                        ], style={'flex': '1', 'marginRight': '12px'}),  # 缩小一半：24px -> 12px
                        html.Div([
                            html.Label("API Secret", style={
                                'fontWeight': '700', 
                                'marginBottom': '6px',  # 缩小一半：12px -> 6px
                                'display': 'block',
                                'fontSize': '16px'  # 缩小一半：32px -> 16px
                            }),
                            dcc.Input(id='modal-api-secret', type='password', placeholder='输入 API Secret', style=INPUT_STYLE),
                        ], style={'flex': '1'}),
                    ], style={'display': 'flex', 'marginBottom': '8px'}),  # 缩小一半：16px -> 8px
                    
                    # Deepcoin 独有 (Passphrase)
                    html.Div(id='modal-creds-deepcoin', children=[
                        html.Label("Passphrase (API 口令)", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',  # 缩小一半：12px -> 6px
                            'display': 'block',
                            'fontSize': '16px'  # 缩小一半：32px -> 16px
                        }),
                        dcc.Input(id='modal-passphrase', type='password', placeholder='输入 API Passphrase', style=INPUT_STYLE),
                    ], style={'marginBottom': '8px'}),  # 缩小一半：16px -> 8px
                    
                    # Ostium 独有 (Private Key)
                    html.Div(id='modal-creds-ostium', children=[
                        html.Label("Private Key (钱包私钥)", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',  # 缩小一半：12px -> 6px
                            'display': 'block',
                            'fontSize': '16px'  # 缩小一半：32px -> 16px
                        }),
                        dcc.Input(id='modal-private-key', type='password', placeholder='输入 0x 开头的私钥', style=INPUT_STYLE),
                    ]),
                ], style={
                    'backgroundColor': '#F9FAFB', 
                    'padding': '15px',  # 缩小一半：30px -> 15px
                    'borderRadius': '8px',  # 缩小一半：16px -> 8px
                    'marginBottom': '12px',  # 缩小一半：24px -> 12px
                    'border': '1px dashed #D1D5DB'
                }),

                # 第二排：交易对、保证金、杠杆
                html.Div([
                    html.Div([
                        html.Label("交易对 (Symbol)", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',
                            'display': 'block',
                            'fontSize': '16px'
                        }),
                        dcc.Input(id='modal-symbol', type='text', value='ETH/USDC', style=INPUT_STYLE),
                    ], style={'flex': '1'}),
                    html.Div([
                        html.Label("下单保证金 (Margin)", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',
                            'display': 'block',
                            'fontSize': '16px'
                        }),
                        dcc.Input(id='modal-size', type='number', value=20, min=1, step=1, style=INPUT_STYLE),
                    ], style={'flex': '1'}),
                    html.Div([
                        html.Label("杠杆倍数 (Leverage)", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',
                            'display': 'block',
                            'fontSize': '16px'
                        }),
                        dcc.Input(id='modal-leverage', type='number', value=50, min=1, max=100, style=INPUT_STYLE),
                    ], style={'flex': '1'}),
                ], style={'display': 'flex', 'marginBottom': '12px', 'gap': '12px'}),

                # 第三排：止盈止损
                html.Div([
                    html.Div([
                        html.Label("止盈比例 (%)", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',
                            'display': 'block',
                            'fontSize': '16px'
                        }),
                        dcc.Input(id='modal-tp', type='number', value=2.0, step=0.1, style=INPUT_STYLE),
                    ], style={'flex': '1', 'marginRight': '12px'}),
                    html.Div([
                        html.Label("止损比例 (%)", style={
                            'fontWeight': '700', 
                            'marginBottom': '6px',
                            'display': 'block',
                            'fontSize': '16px'
                        }),
                        dcc.Input(id='modal-sl', type='number', value=1.5, step=0.1, style=INPUT_STYLE),
                    ], style={'flex': '1'}),
                ], style={'display': 'flex', 'marginBottom': '16px', 'gap': '12px'}),
                
                # Ostium 休市时间段配置 (仅在选择 Ostium 平台时显示)
                html.Div(id='ostium-forbidden-hours-section', children=[
                    html.Div([
                        html.Label("休市时间段配置 (北京时间)", style={
                            'fontWeight': '700',
                            'fontSize': '16px',
                            'marginBottom': '8px',
                            'display': 'block'
                        }),
                        html.P("在休市时间段内将自动平仓，不接受新开仓信号", style={
                            'fontSize': '12px',
                            'color': COLORS['text_dim'],
                            'marginBottom': '12px'
                        }),
                    ]),
                    
                    # 添加休市区间
                    html.Div([
                        html.Div([
                            html.Label("开始时间 (小时)", style={'fontSize': '14px', 'marginBottom': '4px', 'display': 'block'}),
                            dcc.Input(id='range-start-hour', type='number', min=0, max=23, value=3, 
                                     style={**INPUT_STYLE, 'width': '100%', 'padding': '8px'}),
                        ], style={'flex': '1', 'marginRight': '8px'}),
                        html.Div([
                            html.Label("结束时间 (小时)", style={'fontSize': '14px', 'marginBottom': '4px', 'display': 'block'}),
                            dcc.Input(id='range-end-hour', type='number', min=0, max=23, value=8,
                                     style={**INPUT_STYLE, 'width': '100%', 'padding': '8px'}),
                        ], style={'flex': '1', 'marginRight': '8px'}),
                        html.Button("添加", id='add-range-button', 
                                   style={
                                       'padding': '8px 16px',
                                       'backgroundColor': COLORS['accent'],
                                       'color': 'white',
                                       'border': 'none',
                                       'borderRadius': '4px',
                                       'cursor': 'pointer',
                                       'fontSize': '14px',
                                       'fontWeight': '600',
                                       'alignSelf': 'flex-end'
                                   }),
                    ], style={'display': 'flex', 'marginBottom': '12px', 'alignItems': 'flex-end'}),
                    
                    # 显示已添加的休市区间
                    html.Div([
                        html.Label("已配置的休市区间:", style={'fontSize': '14px', 'marginBottom': '8px', 'display': 'block'}),
                        html.Div(id='forbidden-ranges-display', style={
                            'display': 'flex',
                            'flexWrap': 'wrap',
                            'gap': '8px'
                        }),
                    ]),
                    
                    # 隐藏的数据存储
                    dcc.Store(id='forbidden-ranges-store', data=[[3, 8], [13, 15], [19, 21]]),  # 默认休市时间
                ], style={
                    'backgroundColor': '#FFF7ED',
                    'padding': '15px',
                    'borderRadius': '8px',
                    'marginBottom': '12px',
                    'border': '1px solid #FED7AA',
                    'display': 'none'  # 默认隐藏，通过回调控制显示
                }),
            ]),

            html.Div([
                html.Button("取消返回", id='btn-modal-close', style={
                    'backgroundColor': '#F3F4F6', 
                    'color': '#4B5563', 
                    'border': 'none', 
                    'padding': '14px 30px',  # 缩小一半：28px 60px -> 14px 30px
                    'borderRadius': '6px',  # 缩小一半：12px -> 6px
                    'marginRight': '12px',  # 缩小一半：24px -> 12px
                    'cursor': 'pointer', 
                    'fontSize': '16px',  # 缩小一半：32px -> 16px
                    'fontWeight': '600'
                }),
                html.Button("确认启动实盘进程", id='btn-modal-launch', className='btn-primary', style={
                    'flex': '1', 
                    'fontSize': '18px',  # 缩小一半：36px -> 18px
                    'borderRadius': '6px',  # 缩小一半：12px -> 6px
                    'padding': '14px 30px'  # 缩小一半：28px 60px -> 14px 30px
                })
            ], style={'display': 'flex', 'marginTop': '12px'})  # 缩小一半：24px -> 12px
        ])
    ]),
    
    html.Div(id='auth-container', style={'display': 'none'}),
    html.Div(id='main-app-container', children=[
        html.Div(id='sidebar-container'),
        html.Div(className='content', children=[
            html.Div(id='header-container'),
            html.Div(id='trading-page-container', className='page-container', style={'display': 'none'}),
            html.Div(id='dashboard-page-container', className='page-container', style={'display': 'none'}),
            html.Div(id='ai-lab-page-container', className='page-container', style={'display': 'none'}),
            html.Div(id='grid-trading-page-container', className='page-container', style={'display': 'none'}),
            html.Div(id='currency-monitor-page-container', className='page-container', style={'display': 'none'})
        ])
    ], style={'display': 'none'})
])


def get_sidebar(current_user, pathname):
    """构建专业侧边栏"""
    if not current_user:
        return html.Div()
        
    role = current_user.get('role', 'user')
    role_label = 'Admin' if role == 'superuser' else 'User'
    
    return html.Div([
        html.Div([
            html.H3('Platform', style={
                'color': COLORS['accent'], 
                'margin': '0', 
                'fontSize': '18px',  # 减小字体：21px -> 18px
                'letterSpacing': '1px',
                'fontWeight': '800'
            }),
            html.P(f'v1.0 {role_label}', style={
                'color': COLORS['text_dim'], 
                'fontSize': '11px',  # 减小字体：13px -> 11px
                'margin': '2px 0 0 0',  # 减小间距：3px -> 2px
                'textTransform': 'uppercase'
            })
        ], style={
            'marginBottom': '20px',  # 增加间距：16px -> 20px
            'textAlign': 'center', 
            'borderBottom': '1px solid ' + COLORS['border'],
            'paddingBottom': '12px'  # 增加内边距：10px -> 12px
        }),
        
        # 导航
        html.Div([
            dcc.Link([
                html.Span("⚡", style={'marginRight': '8px', 'fontSize': '16px'}),
                html.Span("实盘交易", style={'fontSize': '14px', 'fontWeight': '500'})
            ], href='/trading', className=f'nav-link {"active" if pathname == "/trading" or pathname == "/" else ""}', id='nav-trading'),
            
            dcc.Link([
                html.Span("📊", style={'marginRight': '8px', 'fontSize': '16px'}),
                html.Span("数据大屏", style={'fontSize': '14px', 'fontWeight': '500'})
            ], href='/dashboard', className=f'nav-link {"active" if pathname == "/dashboard" else ""}', id='nav-dashboard'),

            dcc.Link([
                html.Span("🤖", style={'marginRight': '8px', 'fontSize': '16px'}),
                html.Span("AI 自适应实验室", style={'fontSize': '14px', 'fontWeight': '500'})
            ], href='/ai-lab', className=f'nav-link {"active" if pathname == "/ai-lab" else ""}', id='nav-ai-lab'),
            
            dcc.Link([
                html.Span("🎯", style={'marginRight': '8px', 'fontSize': '16px'}),
                html.Span("合约网格", style={'fontSize': '14px', 'fontWeight': '500'})
            ], href='/grid-trading', className=f'nav-link {"active" if pathname == "/grid-trading" else ""}', id='nav-grid-trading'),

            dcc.Link([
                html.Span("🔔", style={'marginRight': '8px', 'fontSize': '16px'}),
                html.Span("币种监视", style={'fontSize': '14px', 'fontWeight': '500'})
            ], href='/currency-monitor', className=f'nav-link {"active" if pathname == "/currency-monitor" else ""}', id='nav-currency-monitor'),
        ], style={'flexGrow': '1'}),

        # 侧边栏底部（余额已移除，因同步不稳定）
        html.Div(id='sidebar-balance-area', style={'marginTop': 'auto', 'paddingTop': '20px', 'display': 'none'})
    ], className='sidebar')

def get_header(current_user):
    """构建顶部栏 - 仅保留用户信息和退出按钮"""
    if not current_user:
        return html.Div()
        
    return html.Div([
        # 右侧：用户信息与退出
        html.Div([
            html.Div([
                html.Span("●", style={'color': '#0ecb81', 'marginRight': '5px', 'fontSize': '12px'}),  # 缩小：16px -> 12px
                html.Span(str(current_user['username']), style={'color': COLORS['text'], 'fontSize': '14px', 'fontWeight': '700'}),  # 缩小：18px -> 14px
            ], style={'padding': '4px 8px', 'display': 'flex', 'alignItems': 'center'}),  # 缩小：8px 16px -> 4px 8px
            
            html.Button('退出系统', id='logout-button', className='btn-danger', style={'padding': '6px 14px', 'fontSize': '14px', 'marginLeft': '8px'})  # 缩小：12px 28px -> 6px 14px, 16px -> 14px, 16px -> 8px
        ], style={'display': 'flex', 'alignItems': 'center'})
    ], className='top-header')

@app.callback(
    [Output('auth-container', 'children'),
     Output('auth-container', 'style'),
     Output('main-app-container', 'style'),
     Output('sidebar-container', 'children'),
     Output('header-container', 'children'),
     Output('trading-page-container', 'children'),
     Output('dashboard-page-container', 'children'),
     Output('ai-lab-page-container', 'children'),
     Output('grid-trading-page-container', 'children'),
     Output('currency-monitor-page-container', 'children'),
     Output('trading-page-container', 'style'),
     Output('dashboard-page-container', 'style'),
     Output('ai-lab-page-container', 'style'),
     Output('grid-trading-page-container', 'style'),
     Output('currency-monitor-page-container', 'style')],
    [Input('url', 'pathname'),
     Input('current-user-store', 'data')],
    [State('control-log-store', 'data'),
     State('trading-page-container', 'children'),
     State('dashboard-page-container', 'children'),
     State('ai-lab-page-container', 'children'),
     State('grid-trading-page-container', 'children'),
     State('currency-monitor-page-container', 'children')]
)
def display_page(pathname, current_user, control_log, trading_content, dashboard_content, ai_lab_content, grid_content, currency_monitor_content):
    """页面路由及显示逻辑 (支持状态持久化)"""
    if not current_user:
        # 未登录状态
        return render_auth_layout(), {'display': 'block'}, {'display': 'none'}, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, {'display': 'none'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'}
    
    # 登录状态，显示主容器
    sidebar = get_sidebar(current_user, pathname)
    header = get_header(current_user)
    
    # 初始化内容 (仅在内容为空时加载，防止重复渲染丢失输入状态)
    t_content = dash.no_update
    if not trading_content:
        t_content = render_trading_layout(current_user, control_log)
        
    d_content = dash.no_update
    if not dashboard_content:
        d_content = render_dashboard_layout()

    a_content = dash.no_update
    if not ai_lab_content:
        a_content = render_ai_lab_layout()
    
    g_content = dash.no_update
    if not grid_content:
        g_content = render_grid_trading_layout()

    cm_content = dash.no_update
    if not currency_monitor_content:
        cm_content = render_currency_monitor_layout()

    # 根据路径切换显示状态
    t_style = {'display': 'block'} if pathname == '/trading' or pathname == '/' else {'display': 'none'}
    d_style = {'display': 'block'} if pathname == '/dashboard' else {'display': 'none'}
    a_style = {'display': 'block'} if pathname == '/ai-lab' else {'display': 'none'}
    g_style = {'display': 'block'} if pathname == '/grid-trading' else {'display': 'none'}
    cm_style = {'display': 'block'} if pathname == '/currency-monitor' else {'display': 'none'}

    return dash.no_update, {'display': 'none'}, {'display': 'block'}, sidebar, header, t_content, d_content, a_content, g_content, cm_content, t_style, d_style, a_style, g_style, cm_style


def render_auth_layout():
    """登录页面布局"""
    return html.Div([
        html.Div([
            html.H2('终端登录', style={
                'color': COLORS['accent'], 
                'textAlign': 'center', 
                'marginBottom': '40px', 
                'fontSize': '32px', # 加大标题
                'fontWeight': '700'
            }),
            dcc.Input(
                id='auth-username', 
                type='text',
                value='', # 添加初始值，避免 React 警告
                placeholder='用户名', 
                style={
                    'backgroundColor': '#FFFFFF',
                    'border': '1px solid ' + COLORS['border'],
                    'color': COLORS['text'],
                    'borderRadius': '8px',
                    'width': '100%',
                    'fontSize': '16px',
                    'padding': '14px 16px',
                    'marginBottom': '20px',
                    'boxSizing': 'border-box'
                }
            ),
            dcc.Input(
                id='auth-password', 
                type='password',
                value='', # 添加初始值
                placeholder='密码', 
                style={
                    'backgroundColor': '#FFFFFF',
                    'border': '1px solid ' + COLORS['border'],
                    'color': COLORS['text'],
                    'borderRadius': '8px',
                    'width': '100%',
                    'fontSize': '16px',
                    'padding': '14px 16px',
                    'marginBottom': '20px',
                    'boxSizing': 'border-box'
                }
            ),
            html.Div([
                html.Button('登 录', id='login-button', className='btn-primary', style={
                    'width': '100%', 
                    'marginBottom': '12px', 
                    'fontSize': '16px', # 加大按钮字体
                    'padding': '12px'
                }),
                html.Button('注 册', id='register-button', style={
                    'width': '100%', 
                    'background': 'transparent', 
                    'color': COLORS['text_dim'], 
                    'border': 'none', 
                    'cursor': 'pointer', 
                    'fontSize': '15px',
                    'padding': '10px'
                }),
            ]),
            html.Div(id='auth-message', style={
                'color': COLORS['danger'], 
                'marginTop': '16px', 
                'textAlign': 'center', 
                'fontSize': '15px'
            })
        ], style={
            **CARD_STYLE, 
            'width': '460px', # 稍微加宽
            'padding': '40px', # 加大内边距
            'boxShadow': '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)'
        })
    ], id='auth-area', style={
        'display': 'flex',
        'justifyContent': 'center',
        'alignItems': 'center',
        'minHeight': '100vh', # 全屏高度
        'width': '100%'
    })

def render_trading_layout(current_user, control_log):
    """实盘控制中心 - 优化布局，减少留白，增大字体"""
    return html.Div([
        # 1. 顶部标题区域
        html.Div([
            html.Div([
                html.H2("实盘控制中心 (LIVE TERMINAL)", style={
                    'margin': '0', 
                    'fontWeight': '900', 
                    'fontSize': '28px',  # 缩小一半：56px -> 28px
                    'color': '#111827', 
                    'letterSpacing': '-1px'
                }),
                html.P("并发运行、状态监控与多账户管理", style={
                    'color': COLORS['text_dim'], 
                    'marginTop': '4px',  # 缩小一半：8px -> 4px
                    'fontSize': '16px',  # 缩小一半：32px -> 16px
                    'marginBottom': '0'
                })
            ], style={'flex': '1'}),
            html.Button([
                html.Span("+ ", style={'fontSize': '16px', 'marginRight': '5px', 'fontWeight': '900'}),  # 缩小一半：32px -> 16px
                "增加新策略"
            ], id='btn-add-strategy', className='btn-primary', style={
                'padding': '14px 28px',  # 缩小一半：28px 56px -> 14px 28px
                'borderRadius': '8px',  # 缩小一半：16px -> 8px
                'fontSize': '16px'  # 缩小一半：32px -> 16px
            })
        ], style={
            'display': 'flex', 
            'justifyContent': 'space-between', 
            'alignItems': 'flex-start', 
            'marginBottom': '16px'  # 缩小一半：32px -> 16px
        }),

        # 2. 活动实例网格
        html.Div([
            html.H4("运行中的策略实例 (ACTIVE INSTANCES)", style={
                'marginBottom': '10px',  # 缩小一半：20px -> 10px
                'fontWeight': '800', 
                'fontSize': '18px',  # 缩小一半：36px -> 18px
                'color': '#374151'
            }),
            html.Div(id='active-instances-container', style={
                'display': 'grid', 
                'gridTemplateColumns': 'repeat(auto-fill, minmax(240px, 1fr))',  # 缩小一半：480px -> 240px
                'gap': '12px'  # 缩小一半：24px -> 12px
            })
        ], style={'marginBottom': '20px'}),  # 缩小一半：40px -> 20px

        # 3. 实时日志区域
        html.Div([
            html.H4("终端实时输出日志 (SYSTEM LOGS)", style={
                'marginBottom': '10px',  # 缩小一半：20px -> 10px
                'fontWeight': '800', 
                'fontSize': '18px',  # 缩小一半：36px -> 18px
                'color': '#374151'
            }),
            html.Div([
                html.Pre(id='control-log', style={
                    'backgroundColor': '#FFFFFF', 
                    'color': '#374151', 
                    'padding': '14px',  # 缩小一半：28px -> 14px
                    'borderRadius': '6px',  # 缩小一半：12px -> 6px
                    'height': '400px',  # 缩小一半：800px -> 400px
                    'overflowY': 'auto',
                    'fontSize': '13px',  # 缩小一半：26px -> 13px
                    'border': '1px solid #E5E7EB',
                    'lineHeight': '1.8',  # 优化行高
                    'boxShadow': 'inset 0 1px 4px rgba(0,0,0,0.03)',  # 缩小阴影
                    'fontFamily': 'JetBrains Mono, monospace', 
                    'whiteSpace': 'pre-wrap',
                    'margin': '0'  # 移除默认 margin
                })
            ])
        ])
    ])

def render_dashboard_layout():
    """数据大屏布局 - 优化布局，减少留白，增大字体"""
    return html.Div([
        # 标题区域
        html.Div([
            html.H2('数据资产监控大屏', style={
                'margin': '0', 
                'fontWeight': '800', 
                'fontSize': '28px',  # 缩小一半：56px -> 28px
                'letterSpacing': '1px'
            }),
            html.Div([
                html.Span("NETWORK ONLINE", style={
                    'color': COLORS['success'], 
                    'fontSize': '14px',  # 缩小一半：28px -> 14px
                    'fontWeight': 'bold', 
                    'marginRight': '6px'  # 缩小一半：12px -> 6px
                }),
                html.Span(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style={
                    'color': COLORS['text_dim'], 
                    'fontFamily': 'monospace',
                    'fontSize': '14px'  # 缩小一半：28px -> 14px
                })
            ], style={'display': 'flex', 'alignItems': 'center'})
        ], style={
            'display': 'flex', 
            'justifyContent': 'space-between', 
            'alignItems': 'center', 
            'marginBottom': '12px',  # 缩小一半：24px -> 12px
            'borderLeft': '2px solid ' + COLORS['accent'],  # 缩小一半：4px -> 2px
            'paddingLeft': '8px'  # 缩小一半：16px -> 8px
        }),
        
        # 概览卡片 (Grid)
        html.Div(id='portfolio-summary', className='portfolio-grid', 
                style={
                    'display': 'grid', 
                    'gridTemplateColumns': 'repeat(4, 1fr)', 
                    'gap': '10px',  # 缩小一半：20px -> 10px
                    'marginBottom': '16px'  # 缩小一半：32px -> 16px
                }),

        # 图表区域
        html.Div([
            html.Div([
                html.H4('📈 组合累计净值曲线 (Equity Curve)', style={
                    'color': COLORS['accent'], 
                    'marginBottom': '10px',  # 缩小一半：20px -> 10px
                    'fontSize': '18px'  # 缩小一半：36px -> 18px
                }),
                dcc.Graph(id='portfolio-chart', config={'displayModeBar': False}, style={'height': '200px'})  # 缩小一半：400px -> 200px
            ], className='card-tech')
        ], style={'marginBottom': '16px'}),  # 缩小一半：32px -> 16px

        # 持仓 & 订单 (等宽等高布局)
        html.Div([
            html.Div([
                html.H4('💼 当前活动仓位 (Active Positions)', style={
                    'color': COLORS['accent'], 
                    'marginBottom': '8px',  # 缩小一半：16px -> 8px
                    'fontSize': '16px'  # 缩小一半：20px -> 16px
                }),
                html.Div(id='positions-table')
            ], className='card-tech', style={'flex': '1', 'marginRight': '10px', 'minHeight': '225px'}),  # 缩小一半：20px -> 10px, 450px -> 225px
            
            html.Div([
                html.H4('📋 最近委托订单 (Recent Orders)', style={
                    'color': COLORS['accent'], 
                    'marginBottom': '8px',  # 缩小一半：16px -> 8px
                    'fontSize': '16px'  # 缩小一半：20px -> 16px
                }),
                html.Div(id='orders-table')
            ], className='card-tech', style={'flex': '1'}),
        ], style={'display': 'flex', 'marginBottom': '16px'}),  # 缩小一半：32px -> 16px

        # 交易历史 & 风险 (等宽等高布局)
        html.Div([
            html.Div([
                html.H4('📝 历史成交统计 (Trade History)', style={
                    'color': COLORS['accent'], 
                    'marginBottom': '8px',  # 缩小一半：16px -> 8px
                    'fontSize': '16px'  # 缩小一半：20px -> 16px
                }),
                html.Div(id='trades-table')
            ], className='card-tech', style={'flex': '1', 'marginRight': '10px', 'minHeight': '225px'}),  # 缩小一半：20px -> 10px, 450px -> 225px
            
            html.Div([
                html.H4('⚠️ 风险异常监控 (Risk Monitoring)', style={
                    'color': COLORS['danger'], 
                    'marginBottom': '8px',  # 缩小一半：16px -> 8px
                    'fontSize': '16px'  # 缩小一半：20px -> 16px
                }),
                html.Div(id='risk-events-table')
            ], className='card-tech', style={'flex': '1'}),
        ], style={'display': 'flex'}),
    ])

def render_ai_lab_layout():
    """AI 自适应实验室布局 - 优化布局，减少留白，增大字体"""
    return html.Div([
        dcc.Store(id='ai-suggested-points', data={'buy': [], 'sell': []}), # 存储 AI 建议的点位
        html.Div([
            html.H2('AI 自适应实验室', style={
                'margin': '0', 
                'fontWeight': '1000', 
                'fontSize': '20px',  # 缩小：32px -> 20px
                'letterSpacing': '1px'  # 缩小：2px -> 1px
            }),
            html.Div([
                html.Span("AI ADAPTIVE", style={
                    'backgroundColor': COLORS['accent'], 
                    'color': 'black', 
                    'padding': '2px 5px',  # 缩小：4px 10px -> 2px 5px
                    'borderRadius': '2px',  # 缩小：4px -> 2px
                    'fontSize': '10px',  # 缩小：14px -> 10px
                    'fontWeight': 'bold', 
                    'marginRight': '6px'  # 缩小：12px -> 6px
                }),
                html.Span("视觉识别 + 数据驱动 双模分析", style={
                    'color': COLORS['text_dim'],
                    'fontSize': '12px'  # 缩小：16px -> 12px
                })
            ], style={'display': 'flex', 'alignItems': 'center'})
        ], style={
            'display': 'flex', 
            'justifyContent': 'space-between', 
            'alignItems': 'center', 
            'marginBottom': '16px',  # 缩小：32px -> 16px
            'borderLeft': '2px solid ' + COLORS['accent'],  # 缩小：4px -> 2px
            'paddingLeft': '8px'  # 缩小：16px -> 8px
        }),

        # 垂直居中布局：输入区 -> K线图 -> 分析报告
        html.Div([
            # 顶部：输入区域（居中放大至 3倍）
            html.Div([
                html.Div([
                    html.H4('输入数据', style={'color': COLORS['accent'], 'marginBottom': '16px', 'fontSize': '20px', 'textAlign': 'center', 'fontWeight': '900'}),  # 缩小：32px -> 16px, 48px -> 20px
                    
                    html.Label('1. 上传 K 线截图', style={'color': COLORS['text'], 'display': 'block', 'marginBottom': '8px', 'fontSize': '14px', 'fontWeight': '700'}),  # 缩小：16px -> 8px, 32px -> 14px
                    dcc.Upload(
                        id='upload-kline-image',
                        children=html.Div(['拖拽或 ', html.A('选择图片')], style={'fontSize': '14px', 'color': COLORS['text_dim']}),  # 缩小：32px -> 14px
                        style={'width': '100%', 'height': '70px', 'lineHeight': '70px', 'borderWidth': '1.5px', 'borderStyle': 'dashed', 'borderRadius': '8px', 'textAlign': 'center', 'marginBottom': '12px', 'borderColor': COLORS['border'], 'backgroundColor': '#F9FAFB'},  # 缩小：140px -> 70px, 3px -> 1.5px, 16px -> 8px, 24px -> 12px
                        multiple=False
                    ),
                    html.Div(id='upload-image-preview', style={'marginBottom': '12px', 'textAlign': 'center'}),  # 缩小：24px -> 12px

                    html.Label('2. 原始 OHLC 数据 (JSON格式)', style={'color': COLORS['text'], 'display': 'block', 'marginBottom': '8px', 'fontSize': '14px', 'fontWeight': '700'}),  # 缩小：16px -> 8px, 32px -> 14px
                    html.Div([
                        html.Button('抓取最新行情 (ETH)', id='fetch-latest-kline-btn', className='btn-primary', style={'width': '100%', 'marginBottom': '8px', 'backgroundColor': '#F0B90B', 'color': '#FFFFFF', 'border': 'none', 'fontSize': '14px', 'padding': '12px'}),  # 缩小：16px -> 8px, 30px -> 14px, 24px -> 12px
                    ]),
                    dcc.Textarea(
                        id='raw-kline-data',
                        placeholder='例如: [{"time": "10:00", "open": 65000, "high": 65500, ...}]',
                        style={'width': '100%', 'height': '175px', 'backgroundColor': '#F9FAFB', 'color': COLORS['text'], 'border': '1px solid ' + COLORS['border'], 'borderRadius': '8px', 'padding': '16px', 'marginBottom': '12px', 'fontSize': '12px'}  # 缩小：350px -> 175px, 16px -> 8px, 32px -> 16px, 24px -> 12px, 28px -> 12px
                    ),

                    html.Label('3. 分析指令 (驯化提示词)', style={'color': COLORS['text'], 'display': 'block', 'marginBottom': '8px', 'fontSize': '14px', 'fontWeight': '700'}),  # 缩小：16px -> 8px, 32px -> 14px
                    dcc.Input(
                        id='ai-user-query',
                        value='请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。',
                        style={'width': '100%', 'backgroundColor': '#F9FAFB', 'color': COLORS['text'], 'border': '1px solid ' + COLORS['border'], 'borderRadius': '8px', 'padding': '16px', 'marginBottom': '16px', 'fontSize': '14px'}  # 缩小：16px -> 8px, 32px -> 16px, 32px -> 16px, 30px -> 14px
                    ),

                    html.Button('开始 AI 综合分析', id='run-ai-analysis-btn', className='btn-primary', style={'width': '100%', 'fontSize': '16px', 'padding': '16px'})  # 缩小：36px -> 16px, 36px -> 16px
                ], className='card-tech', style={'padding': '35px'})  # 缩小：70px -> 35px
            ], style={'maxWidth': '1500px', 'margin': '0 auto 24px auto'}),  # 缩小：3000px -> 1500px, 48px -> 24px

            # 中间：K 线图表（正下方）
            html.Div([
                html.H4('K 线策略可视化', style={'color': COLORS['accent'], 'marginBottom': '16px', 'fontSize': '20px', 'textAlign': 'center', 'fontWeight': '900'}),  # 缩小：32px -> 16px, 48px -> 20px
                dcc.Graph(id='ai-kline-chart', style={'height': '400px'})  # 缩小：800px -> 400px
            ], className='card-tech', style={'marginBottom': '24px'}),  # 缩小：48px -> 24px

            # 底部：AI 分析报告（正下方）
            html.Div([
                html.H4('DeepSeek V3 策略分析报告', style={'color': COLORS['accent'], 'marginBottom': '16px', 'fontSize': '20px', 'textAlign': 'center', 'fontWeight': '900'}),  # 缩小：32px -> 16px, 48px -> 20px
                dcc.Loading(
                    id="loading-ai",
                    type="default",
                    children=html.Div(id='ai-analysis-output', style={'whiteSpace': 'pre-wrap', 'color': COLORS['text'], 'fontSize': '14px', 'lineHeight': '2.2', 'maxHeight': '350px', 'overflowY': 'auto', 'padding': '20px'})  # 缩小：32px -> 14px, 700px -> 350px, 40px -> 20px
                )
            ], className='card-tech')
        ])
    ])


def render_currency_monitor_layout():
    """币种监视布局：多选币种、K线级别、币种池、异动钉钉预警"""
    return html.Div([
        dcc.Store(id='currency-monitor-symbols-store', data=[]),
        dcc.Store(id='currency-monitor-timeframes-store', data=[]),
        dcc.Store(id='currency-monitor-alerted-store', data=[]),
        dcc.Store(id='currency-monitor-running-store', data=False),
        dcc.Store(id='currency-monitor-pending-remove', data=None),
        dcc.Store(id='currency-monitor-clear-trigger', data=0),
        dcc.ConfirmDialog(id='currency-monitor-remove-confirm', message='确定要移除该监视吗？', displayed=False),
        dcc.Interval(id='currency-monitor-refresh', interval=5000, n_intervals=0),
        html.Div([
            html.H2('币种监视', style={
                'margin': '0',
                'fontWeight': '800',
                'fontSize': '24px',
                'color': COLORS['text']
            }),
            html.P('特别K-倍数判定策略，异动时钉钉预警', style={
                'margin': '8px 0 0 0',
                'color': COLORS['text_dim'],
                'fontSize': '14px'
            })
        ], style={'marginBottom': '24px'}),

        html.Div([
            html.H3('监视配置', style={
                'margin': '0 0 16px 0',
                'fontSize': '18px',
                'fontWeight': '700',
                'color': COLORS['text']
            }),
            html.Div([
                html.Div([
                    html.Label('币种 (多选)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                    html.Div([
                        html.Button('全选', id='currency-monitor-select-all', style={
                            'padding': '6px 12px', 'fontSize': '12px', 'marginRight': '8px', 'marginBottom': '8px',
                            'backgroundColor': COLORS['accent'], 'color': 'white', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'
                        }),
                        html.Button('清空', id='currency-monitor-clear-all', style={
                            'padding': '6px 12px', 'fontSize': '12px', 'marginBottom': '8px',
                            'backgroundColor': COLORS['border'], 'color': COLORS['text'], 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'
                        }),
                    ]),
                    dcc.Dropdown(
                        id='currency-monitor-symbols',
                        options=[],
                        value=[],
                        multi=True,
                        placeholder='选择要监视的币种...',
                        style={'fontSize': '14px'}
                    ),
                ], style={'flex': '1', 'marginRight': '24px'}),
                html.Div([
                    html.Label('K线级别 (多选)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                    dcc.Checklist(
                        id='currency-monitor-timeframes',
                        options=[
                            {'label': ' 2小时', 'value': '2小时'},
                            {'label': ' 4小时', 'value': '4小时'},
                            {'label': ' 天', 'value': '天'},
                            {'label': ' 周', 'value': '周'},
                        ],
                        value=[],
                        labelStyle={'display': 'block', 'marginBottom': '6px', 'fontSize': '14px'},
                        style={'padding': '8px'}
                    ),
                ], style={'flex': '0 0 180px'}),
            ], style={'display': 'flex', 'marginBottom': '20px'}),

            html.Div([
                html.Button('开始监视', id='currency-monitor-start', className='btn-primary', style={'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}),
                html.Button('停止监视', id='currency-monitor-stop', className='btn-danger', style={'marginRight': '12px', 'padding': '10px 24px', 'opacity': 0.5, 'cursor': 'not-allowed', 'pointerEvents': 'none'}),
                html.Button('模拟测试', id='currency-monitor-test-btn', style={
                    'padding': '10px 24px', 'backgroundColor': '#6B7280', 'color': 'white', 'border': 'none',
                    'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px'
                }, title='模拟异动，币种池变红 10 分钟并发送钉钉'),
            ], style={'marginBottom': '20px'}),

            html.Div([
                html.Label('币种池 (异动时变红)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                html.P('已有监视时，选择更多币种/级别后点击「开始监视」可追加；下方选择要移除的项后点击「移除」', style={
                    'margin': '0 0 8px 0', 'color': COLORS['text_dim'], 'fontSize': '12px'
                }),
                html.Div(id='currency-monitor-pool', style={
                    'display': 'flex', 'flexWrap': 'wrap', 'gap': '8px',
                    'padding': '12px', 'backgroundColor': '#F9FAFB', 'borderRadius': '8px', 'minHeight': '60px',
                    'border': '1px solid ' + COLORS['border']
                }),
                html.Div([
                    dcc.Dropdown(
                        id='currency-monitor-remove-select',
                        placeholder='选择要移除的监视...',
                        options=[],
                        value=None,
                        style={'width': '220px', 'fontSize': '13px'},
                        clearable=True,
                    ),
                    html.Button('移除', id='currency-monitor-remove-btn', style={
                        'padding': '8px 16px', 'fontSize': '13px', 'cursor': 'pointer',
                        'backgroundColor': COLORS['danger'], 'color': 'white', 'border': 'none', 'borderRadius': '5px',
                    }),
                ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'center', 'marginTop': '12px'}),
            ]),
        ], className='card-tech', style={'padding': '24px'}),
    ])


# --- 辅助：当 session 中无 id 时，从 DB 按 username 查回 user_id（兼容旧会话） ---
def _resolve_user_id(current_user):
    """从 current_user 获取 user_id；若无 id 但有 username，从 DB 查回"""
    uid = (current_user or {}).get('id')
    if uid is not None:
        return uid
    username = (current_user or {}).get('username')
    if not username:
        return None
    try:
        user = db_manager.get_user_by_username(username)
        return user.id if user else None
    except Exception as e:
        logger.warning(f"按 username 查 user_id 失败: {e}")
        return None


# --- 币种监视相关回调 ---
@app.callback(
    Output('currency-monitor-symbols', 'options'),
    [Input('url', 'pathname'),
     Input('current-user-store', 'data')],
    prevent_initial_call=True,
)
def currency_monitor_load_symbols(pathname, current_user):
    """进入币种监视页时加载币安 USDT 交易对（仅登录后组件存在时更新）"""
    if pathname != '/currency-monitor' or not current_user:
        raise dash.exceptions.PreventUpdate
    try:
        symbols = fetch_binance_symbols_usdt()
        return [{'label': s, 'value': s} for s in symbols]
    except Exception as e:
        logger.error(f"加载币种列表失败: {e}")
        return [{'label': s, 'value': s} for s in ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']]


@app.callback(
    Output('currency-monitor-symbols', 'value'),
    Input('currency-monitor-select-all', 'n_clicks'),
    Input('currency-monitor-clear-all', 'n_clicks'),
    State('currency-monitor-symbols', 'options'),
    prevent_initial_call=True
)
def currency_monitor_select_clear(select_clicks, clear_clicks, options):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    bid = ctx.triggered[0]['prop_id'].split('.')[0]
    if bid == 'currency-monitor-select-all':
        return [o['value'] for o in options] if options else []
    if bid == 'currency-monitor-clear-all':
        return []
    raise dash.exceptions.PreventUpdate


@app.callback(
    [Output('currency-monitor-running-store', 'data', allow_duplicate=True),
     Output('currency-monitor-start', 'style'),
     Output('currency-monitor-stop', 'style'),
     Output('currency-monitor-symbols', 'value', allow_duplicate=True),
     Output('currency-monitor-timeframes', 'value', allow_duplicate=True),
     Output('currency-monitor-clear-trigger', 'data', allow_duplicate=True)],
    Input('currency-monitor-start', 'n_clicks'),
    Input('currency-monitor-stop', 'n_clicks'),
    State('currency-monitor-symbols', 'value'),
    State('currency-monitor-timeframes', 'value'),
    State('currency-monitor-running-store', 'data'),
    State('current-user-store', 'data'),
    prevent_initial_call=True
)
def currency_monitor_start_stop(start_clicks, stop_clicks, symbols, timeframes, running, current_user):
    user_id = _resolve_user_id(current_user)
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    bid = ctx.triggered[0]['prop_id'].split('.')[0]

    if bid == 'currency-monitor-start':
        # 本次必须至少选择一个币种和一个级别，才有新增意义
        if not symbols or not timeframes:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # 【币种监视取消隔离】全局共享，所有账户看到同一配置
        mon = get_monitor_instance()
        base_pairs = []
        
        # 1. 优先从内存实例获取当前配对
        if mon:
            base_pairs = mon._pairs or []
            logger.info(f"币种监视合并：从内存获取到已有配对 {base_pairs}")
        
        # 2. 如果内存没有，从全局配置恢复
        if not base_pairs:
            try:
                cfg_result = db_manager.get_currency_monitor_config()
                if cfg_result:
                    _, cfg_json = cfg_result
                    cfg = json.loads(cfg_json)
                    if 'pairs' in cfg:
                        base_pairs = [(str(p[0]).upper(), str(p[1])) for p in cfg['pairs']]
                    else:
                        base_pairs = [(s, t) for s in cfg.get('symbols', []) for t in cfg.get('timeframes', [])]
                    logger.info(f"币种监视合并：从全局配置恢复到已有配对 {base_pairs}")
            except Exception as e:
                logger.error(f"合并时从数据库恢复配置失败: {e}")

        # 3. 计算本次新增的配对
        new_pairs = [(s, t) for s in (symbols or []) for t in (timeframes or [])]
        
        # 4. 合并去重
        seen = set()
        merged_pairs = []
        for p in (base_pairs + new_pairs):
            key = (str(p[0]).upper(), str(p[1]))
            if key not in seen:
                seen.add(key)
                merged_pairs.append(key)

        if not merged_pairs:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        logger.info(f"币种监视合并结果: {merged_pairs}")

        # 先停掉旧实例，再用合并后的配对启动新实例
        if mon:
            mon.stop()

        new_mon = BinanceMonitorService(pairs=merged_pairs, user_id=None)  # user_id=None 表示全局共享
        set_monitor_instance(new_mon)
        new_mon.start()
        
        cfg = json.dumps({'pairs': merged_pairs})
        try:
            db_manager.save_currency_monitor_config(cfg)
            logger.info(f"币种监视已保存到全局配置: pairs={merged_pairs}")
        except Exception as e:
            logger.error(f"保存币种监视到 DB 失败: {e}")
        # 成功启动后，清空上方多选框（用户需求：点完开始就清空，只在池子里显示）
        # 同时设置 clear-trigger 触发专用清空回调，确保多选框被清空
        btn_start = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}
        btn_stop = {'padding': '10px 24px', 'cursor': 'pointer'}
        return True, btn_start, btn_stop, [], [], round(time.time() * 1000)

    if bid == 'currency-monitor-stop':
        logger.info("币种监视：用户请求停止监视")
        mon = get_monitor_instance()
        if mon:
            mon.stop()
            set_monitor_instance(None)
            db_manager.delete_currency_monitor_config()
        btn_start = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}
        btn_stop = {'padding': '10px 24px', 'opacity': 0.5, 'cursor': 'not-allowed', 'pointerEvents': 'none'}
        # 停止监控时不强制清空上方多选框，交给用户自行调整
        return False, btn_start, btn_stop, dash.no_update, dash.no_update, dash.no_update

    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update


@app.callback(
    [Output('currency-monitor-symbols', 'value', allow_duplicate=True),
     Output('currency-monitor-timeframes', 'value', allow_duplicate=True)],
    [Input('currency-monitor-clear-trigger', 'data'),
     Input('currency-monitor-start', 'n_clicks')],
    prevent_initial_call=True,
)
def currency_monitor_clear_on_start(clear_trigger, start_clicks):
    """开始监视后强制清空币种和K线级别多选框（由 clear-trigger 或 开始监视 按钮触发）"""
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    # 开始监视按钮点击 或 clear-trigger 更新时清空
    tid = ctx.triggered[0]['prop_id'].split('.')[0]
    if tid == 'currency-monitor-start' and (start_clicks or 0) > 0:
        return [], []
    if tid == 'currency-monitor-clear-trigger' and clear_trigger and clear_trigger > 0:
        return [], []
    raise dash.exceptions.PreventUpdate


@app.callback(
    [Output('currency-monitor-alerted-store', 'data'),
     Output('currency-monitor-pool', 'children'),
     Output('currency-monitor-remove-select', 'options'),
     Output('currency-monitor-remove-select', 'value')],
    [Input('currency-monitor-refresh', 'n_intervals'),
     Input('currency-monitor-test-btn', 'n_clicks'),
     Input('url', 'pathname'),
     Input('currency-monitor-start', 'n_clicks'),
     Input('currency-monitor-running-store', 'data')],
    [State('currency-monitor-symbols', 'value'),
     State('currency-monitor-timeframes', 'value'),
     State('currency-monitor-alerted-store', 'data'),
     State('current-user-store', 'data')],
    prevent_initial_call=False,
)
def currency_monitor_refresh_pool(n, n_test, pathname, start_clicks, running, symbols, timeframes, alerted_data, current_user):
    """定时刷新异动状态和币种池显示（仅币种监视页、已登录时更新，避免多输出冲突）"""
    if pathname != '/currency-monitor' or not current_user:
        raise dash.exceptions.PreventUpdate

    alerted = list(alerted_data) if alerted_data else []
    mon = get_monitor_instance()

    # 模拟测试：点击后加入异动、发钉钉、变红 10 分钟
    ctx = dash.callback_context
    if ctx.triggered and 'currency-monitor-test-btn' in ctx.triggered[0].get('prop_id', ''):
        if mon and (n_test or 0) > 0:
            mon.add_alerted_for_test(symbols or [], timeframes or [])
            for s in (symbols or []):
                for t in (timeframes or []):
                    send_dingtalk_alert(str(s), str(t), "【模拟测试】品种涨幅强于ETH且满足连阳")

    if mon:
        alerted_pairs = mon.get_alerted_pairs()
        alerted = [f"{s}|{t}" for (s, t) in alerted_pairs]
        # 【修复】使用真实的配对列表，彻底解决笛卡尔积显示错误
        display_pairs = mon._pairs
    else:
        # 兼容性处理：如果没有运行中的监视器，尝试使用传入的 symbols/timeframes
        display_pairs = [(s, t) for s in (symbols or []) for t in (timeframes or [])]

    pool_items = []
    remove_options = []
    for s, t in display_pairs:
        key = f"{s}|{t}"
        remove_options.append({'label': f'{s} {t}', 'value': key})
        is_alerted = key in alerted
        color = COLORS['danger'] if is_alerted else '#2563EB'
        pool_items.append(
            html.Span(
                f"{s} {t}",
                style={
                    'display': 'inline-block',
                    'padding': '6px 12px',
                    'borderRadius': '6px',
                    'backgroundColor': '#fff',
                    'border': f'1px solid {color}',
                    'color': color,
                    'fontSize': '13px',
                    'fontWeight': '600',
                }
            )
        )
    if not pool_items:
        pool_items = [html.Span('请选择币种和K线级别后开始监视', style={'color': COLORS['text_dim'], 'fontSize': '14px'})]
    return alerted, pool_items, remove_options, dash.no_update


@app.callback(
    [Output('currency-monitor-alerted-store', 'data', allow_duplicate=True),
     Output('currency-monitor-pool', 'children', allow_duplicate=True),
     Output('currency-monitor-remove-select', 'options', allow_duplicate=True),
     Output('currency-monitor-remove-select', 'value', allow_duplicate=True),
     Output('currency-monitor-symbols', 'value', allow_duplicate=True),
     Output('currency-monitor-timeframes', 'value', allow_duplicate=True),
     Output('currency-monitor-running-store', 'data', allow_duplicate=True),
     Output('currency-monitor-start', 'style', allow_duplicate=True),
     Output('currency-monitor-stop', 'style', allow_duplicate=True)],
    Input('currency-monitor-remove-btn', 'n_clicks'),
    State('currency-monitor-remove-select', 'value'),
    State('current-user-store', 'data'),
    prevent_initial_call=True,
)
def currency_monitor_remove_pair(n_clicks, selected_value, current_user):
    """选择要移除的项后点击「移除」按钮执行移除（避免动态组件 pattern-matching 问题）"""
    if not n_clicks or not selected_value or not current_user:
        raise dash.exceptions.PreventUpdate

    parts = str(selected_value).split('|', 1)
    if len(parts) != 2:
        raise dash.exceptions.PreventUpdate
    symbol, timeframe = str(parts[0]).strip(), str(parts[1]).strip()
    if not symbol or not timeframe:
        raise dash.exceptions.PreventUpdate

    mon = get_monitor_instance()
    if not mon:
        raise dash.exceptions.PreventUpdate

    mon.remove_pair(symbol, timeframe)
    logger.info(f"币种监视已移除: {symbol} {timeframe}")

    if not mon._pairs:
        mon.stop()
        set_monitor_instance(None)
        db_manager.delete_currency_monitor_config()
        symbols, timeframes = [], []
        running = False
        btn_start = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}
        btn_stop = {'marginRight': '12px', 'padding': '10px 24px', 'opacity': 0.5, 'cursor': 'not-allowed', 'pointerEvents': 'none'}
    else:
        cfg = json.dumps({'pairs': [[s, t] for s, t in mon._pairs]})
        db_manager.save_currency_monitor_config(cfg)
        symbols, timeframes = mon.symbols, mon.timeframes
        running = True
        btn_start = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}
        btn_stop = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}

    pairs = mon.get_alerted_pairs() if mon else set()
    alerted = [f"{s}|{t}" for (s, t) in pairs]

    pool_items = []
    remove_options = []
    for s, t in (mon._pairs if mon and mon._pairs else []):
        key = f"{s}|{t}"
        remove_options.append({'label': f'{s} {t}', 'value': key})
        is_alerted = key in alerted
        color = COLORS['danger'] if is_alerted else '#2563EB'
        pool_items.append(
            html.Span(
                f"{s} {t}",
                style={
                    'display': 'inline-block',
                    'padding': '6px 12px',
                    'borderRadius': '6px',
                    'backgroundColor': '#fff',
                    'border': f'1px solid {color}',
                    'color': color,
                    'fontSize': '13px',
                    'fontWeight': '600',
                }
            )
        )
    if not pool_items:
        pool_items = [html.Span('请选择币种和K线级别后开始监视', style={'color': COLORS['text_dim'], 'fontSize': '14px'})]

    return alerted, pool_items, remove_options, None, symbols, timeframes, running, btn_start, btn_stop


@app.callback(
    [Output('currency-monitor-symbols', 'value', allow_duplicate=True),
     Output('currency-monitor-timeframes', 'value', allow_duplicate=True),
     Output('currency-monitor-running-store', 'data', allow_duplicate=True),
     Output('currency-monitor-start', 'style', allow_duplicate=True),
     Output('currency-monitor-stop', 'style', allow_duplicate=True)],
    [Input('currency-monitor-refresh', 'n_intervals'),
     Input('url', 'pathname'),
     Input('current-user-store', 'data')],
    prevent_initial_call=True,
)
def currency_monitor_restore_state(n, pathname, current_user):
    """周期性将后台监视器状态同步到前端（币种监视全局共享，刷新后恢复）"""
    if pathname != '/currency-monitor' or not current_user:
        raise dash.exceptions.PreventUpdate

    mon = get_monitor_instance()

    # 【币种监视取消隔离】无监视器时从全局配置恢复并启动
    if not mon:
        try:
            cfg_result = db_manager.get_currency_monitor_config()
            if cfg_result:
                _, cfg_json = cfg_result
                cfg = json.loads(cfg_json)
                if 'pairs' in cfg:
                    pairs = [(str(p[0]).upper(), str(p[1])) for p in cfg['pairs']]
                else:
                    pairs = [(s, t) for s in cfg.get('symbols', []) for t in cfg.get('timeframes', [])]
                if pairs:
                    new_mon = BinanceMonitorService(pairs=pairs, user_id=None)
                    set_monitor_instance(new_mon)
                    new_mon.start()
                    logger.info(f"从全局配置恢复并启动币种监视: {pairs}")
        except Exception as e:
            logger.warning(f"从 DB 恢复币种监视失败: {e}")

    mon = get_monitor_instance()

    if mon:
        btn_start = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}
        btn_stop = {'padding': '10px 24px', 'cursor': 'pointer'}
        return dash.no_update, dash.no_update, True, btn_start, btn_stop

    if db_manager.get_currency_monitor_config():
        btn_start = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}
        btn_stop = {'padding': '10px 24px', 'opacity': 0.5, 'cursor': 'not-allowed', 'pointerEvents': 'none'}
        return dash.no_update, dash.no_update, False, btn_start, btn_stop

    btn_start = {'marginRight': '12px', 'padding': '10px 24px', 'cursor': 'pointer'}
    btn_stop = {'padding': '10px 24px', 'opacity': 0.5, 'cursor': 'not-allowed', 'pointerEvents': 'none'}
    return dash.no_update, dash.no_update, False, btn_start, btn_stop


# 删除旧的 render_auth_area 回调，逻辑已合并至 display_page


@app.callback(
    Output('current-user-store', 'data'),
    Output('auth-message', 'children'),
    Input('login-button', 'n_clicks'),
    Input('register-button', 'n_clicks'),
    State('auth-username', 'value'),
    State('auth-password', 'value'),
    State('current-user-store', 'data'),
    prevent_initial_call=True
)
def handle_auth(login_clicks, register_clicks, username, password, current_user):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    db_manager = DatabaseManager()

    if not username or not password:
        return dash.no_update, '用户名和密码不能为空'

    # 注册
    if button_id == 'register-button':
        print(f"[DEBUG] 处理注册请求: {username}")
        try:
            existing = db_manager.get_user_by_username(username)
            if existing:
                return dash.no_update, '用户名已存在'

            # 第一位用户自动设为超级用户，其余为普通用户
            role = 'user'
            try:
                # 简单检查是否已有用户
                session = db_manager.get_session()
                from backpack_quant_trading.database.models import User
                has_user = session.query(User).first() is not None
                session.close()
                if not has_user:
                    role = 'superuser'
            except Exception as e:
                print(f"[DEBUG] 检查初始用户失败: {e}")
                role = 'user'

            password_hash = generate_password_hash(password)
            user = db_manager.create_user(username, password_hash, role=role)
            print(f"[DEBUG] 注册成功: {username}, role={role}")
            return {'id': user.id, 'username': user.username, 'role': user.role}, '注册成功并已登录'
        except Exception as e:
            print(f"[DEBUG] 注册过程发生异常: {e}")
            import traceback
            traceback.print_exc()
            return dash.no_update, f'注册失败: {str(e)}'

    # 登录
    if button_id == 'login-button':
        print(f"[DEBUG] 处理登录请求: {username}")
        try:
            user = db_manager.get_user_by_username(username)
            if not user:
                return dash.no_update, '用户不存在'
            if not check_password_hash(user.password_hash, password):
                return dash.no_update, '密码错误'
            print(f"[DEBUG] 登录成功: {username}")
            return {'id': user.id, 'username': user.username, 'role': user.role}, ''
        except Exception as e:
            print(f"[DEBUG] 登录过程发生异常: {e}")
            return dash.no_update, f'登录失败: {str(e)}'
    
    return dash.no_update, dash.no_update

# 注：已移除 sync_user_id_from_db，因其会错误覆盖当前用户（如 zzz）为其他用户（zyf）
# 当 session 无 id 时，_resolve_user_id 会按 username 从 DB 查回，但不修改 store，避免覆盖

# 单独处理登出逻辑
@app.callback(
    Output('current-user-store', 'data', allow_duplicate=True),
    Input('logout-button', 'n_clicks'),
    prevent_initial_call=True
)
def handle_logout(n_clicks):
    if n_clicks:
        return None
    return dash.no_update

@app.callback(
    Output('forbidden-ranges-store', 'data'),
    Input('add-range-button', 'n_clicks'),
    Input({'type': 'remove-range-btn', 'index': ALL}, 'n_clicks'),
    State('range-start-hour', 'value'),
    State('range-end-hour', 'value'),
    State('forbidden-ranges-store', 'data'),
    prevent_initial_call=True
)
def manage_forbidden_ranges(add_clicks, remove_clicks, start, end, current_ranges):
    """管理休市区间列表 (添加/删除)"""
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_ranges
    
    triggered_id = ctx.triggered[0]['prop_id']
    
    # 1. 处理删除逻辑
    if 'remove-range-btn' in triggered_id:
        import json
        prop_id_dict = json.loads(triggered_id.split('.')[0])
        idx_to_remove = prop_id_dict['index']
        if 0 <= idx_to_remove < len(current_ranges):
            new_ranges = [r for i, r in enumerate(current_ranges) if i != idx_to_remove]
            return new_ranges
            
    # 2. 处理添加逻辑
    if 'add-range-button' in triggered_id:
        if start is not None and end is not None:
            if start >= end:
                return current_ranges # 简单校验：结束时间必须大于开始时间
            
            # 避免重复
            new_range = [start, end]
            if new_range not in current_ranges:
                current_ranges.append(new_range)
                # 排序
                current_ranges.sort(key=lambda x: x[0])
                return current_ranges
                
    return current_ranges

# AI 实验室相关回调
@app.callback(
    Output('upload-image-preview', 'children'),
    Input('upload-kline-image', 'contents'),
    State('upload-kline-image', 'filename')
)
def update_ai_image_preview(contents, filename):
    if contents is not None:
        return html.Img(src=contents, style={'maxWidth': '100%', 'maxHeight': '200px', 'borderRadius': '8px', 'border': '1px solid ' + COLORS['border']})
    return html.Div("未上传图片", style={'color': COLORS['text_dim'], 'fontSize': '12px'})

@app.callback(
    [Output('ai-analysis-output', 'children'),
     Output('ai-suggested-points', 'data')],
    Input('run-ai-analysis-btn', 'n_clicks'),
    State('upload-kline-image', 'contents'),
    State('raw-kline-data', 'value'),
    State('ai-user-query', 'value'),
    prevent_initial_call=True
)
def process_ai_analysis(n_clicks, image_contents, raw_data, user_query):
    if n_clicks is None:
        return "", {'buy': [], 'sell': []}
    
    ai = AIAdaptive()
    temp_path = None
    
    if image_contents:
        import base64
        data = image_contents.split(',')[1]
        temp_path = "temp_kline_upload.png"
        with open(temp_path, "wb") as f:
            f.write(base64.b64decode(data))
    
    kline_json = None
    if raw_data:
        try:
            kline_json = json.loads(raw_data)
        except:
            kline_json = raw_data
            
    # 明确告知 AI 交易对信息，防止其默认使用 BTC 进行分析
    target_symbol = "ETH_USDC_PERP"
    full_query = f"注意：当前分析的品种是 {target_symbol}。请不要混淆。{user_query}"
    
    result = ai.analyze_kline(image_path=temp_path, kline_data=kline_json, user_query=full_query)
    analysis_text = result.get('analysis', '')
    
    # --- 自动解析点位逻辑 ---
    import re
    suggested_points = {'buy': [], 'sell': []}
    
    def clean_price(p_str):
        # 清除干扰符号：逗号、美元符号、星号、空格等
        return re.sub(r'[,\$￥\*%\sA-Za-z]', '', p_str)

    # 寻找专门的回测标注区块
    marker_section = re.search(r"【回测标注数据】.*?(买入点位.*)", analysis_text, re.DOTALL | re.S)
    search_text = marker_section.group(1) if marker_section else analysis_text

    # 增强正则匹配
    buy_match = re.search(r"买入点位[:：]\s*\[(.*?)\]", search_text)
    if buy_match:
        for item in buy_match.group(1).split(','):
            try:
                price = float(clean_price(item))
                if price > 0: suggested_points['buy'].append(price)
            except: continue

    sell_match = re.search(r"卖出点位[:：]\s*\[(.*?)\]", search_text)
    if sell_match:
        for item in sell_match.group(1).split(','):
            try:
                price = float(clean_price(item))
                if price > 0: suggested_points['sell'].append(price)
            except: continue
    
    if temp_path and os.path.exists(temp_path):
        os.remove(temp_path)
        
    return analysis_text, suggested_points

@app.callback(
    Output('raw-kline-data', 'value'),
    Input('fetch-latest-kline-btn', 'n_clicks'),
    prevent_initial_call=True
)
def fetch_latest_kline_data(n_clicks):
    """从 Backpack 获取最新的 100 根 K 线数据"""
    if n_clicks is None:
        return dash.no_update
    
    try:
        import asyncio
        from backpack_quant_trading.core.api_client import BackpackAPIClient
        
        async def get_data():
            client = BackpackAPIClient()
            import requests
            
            # 1. 获取服务器时间
            try:
                import requests
                resp = requests.get("https://api.backpack.exchange/api/v1/time", timeout=5)
                server_time_ms = int(resp.text)
            except:
                server_time_ms = int(time.time() * 1000)

            # 2. 核心修复：根据 OpenAPI 文档，klines 接口的 startTime 必须是【秒级时间戳】
            # 我们将毫秒除以 1000 转换为秒
            server_time_s = server_time_ms // 1000
            safe_start_time = int(server_time_s - (150 * 60)) # 回溯 150 分钟
            
            url = f"https://api.backpack.exchange/api/v1/klines?symbol=ETH_USDC_PERP&interval=1m&startTime={safe_start_time}"
            klines_resp = requests.get(url, timeout=10)
            if klines_resp.status_code != 200:
                raise Exception(f"API 报错: {klines_resp.text}")
            
            klines = klines_resp.json()
            
            # 转换为 AI 实验室需要的格式 (注意：返回的数据可能已经是秒级或毫秒级，需适配)
            formatted_data = []
            for k in klines:
                if isinstance(k, list):
                    ts = int(k[0])
                    # 如果返回的是秒，转为毫秒供前端绘图
                    if ts < 10000000000: ts *= 1000 
                    formatted_data.append({
                        "time": ts, 
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4])
                    })
                else:
                    # 字典格式 (Backpack API 返回 start/end 为 ISO 字符串)
                    raw_ts = k.get('start', k.get('timestamp', k.get('t', 0)))
                    try:
                        # 使用 pandas 强大的日期解析能力处理 ISO 字符串或数字
                        dt = pd.to_datetime(raw_ts)
                        ts = int(dt.timestamp() * 1000)
                    except:
                        ts = 0
                        
                    formatted_data.append({
                        "time": ts,
                        "open": float(k.get('open', k.get('o', 0))),
                        "high": float(k.get('high', k.get('h', 0))),
                        "low": float(k.get('low', k.get('l', 0))),
                        "close": float(k.get('close', k.get('c', 0)))
                    })
            return json.dumps(formatted_data, indent=2)

        return asyncio.run(get_data())
    except Exception as e:
        return f"抓取数据失败: {str(e)}"

@app.callback(
    Output('ai-kline-chart', 'figure'),
    Input('raw-kline-data', 'value'),
    Input('ai-suggested-points', 'data')
)
def update_ai_kline_chart(raw_data, suggested_points):
    fig = go.Figure()
    fig.update_layout(
        template='plotly_white',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(gridcolor='#F1F3F5', rangeslider=dict(visible=False)),
        yaxis=dict(gridcolor='#F1F3F5')
    )
    
    if not raw_data:
        return fig
        
    try:
        data_json = json.loads(raw_data)
        # 支持您提供的这种 {"data": [...]} 格式
        if isinstance(data_json, dict) and 'data' in data_json:
            data_json = data_json['data']
            
        df = pd.DataFrame(data_json)
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        
        fig.add_trace(go.Candlestick(
            x=df['time'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            name='市场数据'
        ))

        # --- 绘制 AI 标注 ---
        if suggested_points:
            # 标注买入 (在全图中寻找最接近的价格点)
            for p in suggested_points.get('buy', []):
                # 寻找价格最接近的那一根K线，以便在横轴上准确定位
                idx = (df['close'] - p).abs().idxmin()
                target_time = df.loc[idx, 'time']
                fig.add_annotation(
                    x=target_time, y=p, text="B",
                    showarrow=True, arrowhead=2, arrowcolor=COLORS['success'],
                    ax=0, ay=-40, bgcolor=COLORS['success'], font=dict(color='black')
                )
            # 标注卖出
            for p in suggested_points.get('sell', []):
                idx = (df['close'] - p).abs().idxmin()
                target_time = df.loc[idx, 'time']
                fig.add_annotation(
                    x=target_time, y=p, text="S",
                    showarrow=True, arrowhead=2, arrowcolor=COLORS['danger'],
                    ax=0, ay=40, bgcolor=COLORS['danger'], font=dict(color='white')
                )
                
    except Exception as e:
        print(f"绘制K线错误: {e}")
        return go.Figure() # 发生错误时返回空图表而非报错
        
    return fig
@app.callback(
    Output('forbidden-ranges-display', 'children'),
    Input('forbidden-ranges-store', 'data')
)
def render_forbidden_ranges_tags(ranges):
    """渲染休市区间的标签 (带删除按钮)"""
    if not ranges:
        return html.P("未设置休市区间 (全天可交易)", style={'color': COLORS['text_dim'], 'fontSize': '12px'})
        
    tags = []
    for i, r in enumerate(ranges):
        tags.append(
            html.Div([
                html.Span(f"{r[0]:02d}:00 - {r[1]:02d}:00", style={'marginRight': '8px'}),
                html.Span("×", 
                         id={'type': 'remove-range-btn', 'index': i},
                         style={'cursor': 'pointer', 'fontWeight': 'bold', 'color': COLORS['danger'], 'padding': '2px 5px'})
            ], style={
                'backgroundColor': 'rgba(240, 185, 11, 0.15)',
                'border': '1px solid ' + COLORS['accent'],
                'color': COLORS['accent'],
                'borderRadius': '4px',
                'padding': '4px 8px',
                'display': 'flex',
                'alignItems': 'center',
                'fontSize': '12px'
            })
        )
    return tags


@app.callback(
    Output('add-strategy-modal', 'style'),
    [Input('btn-add-strategy', 'n_clicks'),
     Input('btn-modal-close', 'n_clicks'),
     Input('startup-success-dialog', 'submit_n_clicks'),
     Input('url', 'pathname'),
     Input('current-user-store', 'data')],
)
def toggle_modal(n_add, n_close, n_success, pathname, current_user):
    """弹窗仅在用户实际点击「增加策略」时显示；刷新/登录/路由变化时强制关闭"""
    ctx = dash.callback_context
    if not ctx.triggered:
        return {**MODAL_BASE_STYLE, 'display': 'none'}

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # 必须：trigger 来自按钮 且 n_add>0（用户真实点击），否则一律关闭
    if trigger_id == 'btn-add-strategy' and (n_add or 0) > 0:
        return {**MODAL_BASE_STYLE, 'display': 'flex'}
    return {**MODAL_BASE_STYLE, 'display': 'none'}


def is_port_in_use(port: int, host: str = '127.0.0.1') -> bool:
    """检测端口是否被占用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            return result == 0  # 0 表示端口已被占用
    except:
        return False


def get_webhook_pid() -> int:
    """寻找 Webhook 服务进程的 PID"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            # 检查命令行是否包含 webhook_service 模块
            cmdline = proc.info.get('cmdline') or []
            if any('webhook_service' in arg for h in cmdline for arg in ([h] if isinstance(h, str) else [])):
                return proc.info['pid']
    except:
        pass
    return 0


@app.callback(
    [Output('modal-creds-common', 'style'),
     Output('modal-creds-deepcoin', 'style'),
     Output('modal-creds-ostium', 'style'),
     Output('ostium-forbidden-hours-section', 'style')],
    [Input('modal-platform', 'value')]
)
def toggle_modal_creds(platform):
    """根据平台动态切换弹窗内的密钥输入框和休市时间段配置"""
    common_style = {'display': 'none'}
    deepcoin_style = {'display': 'none'}
    ostium_style = {'display': 'none'}
    forbidden_hours_style = {'display': 'none'}
    
    if platform == 'backpack':
        common_style = {'display': 'flex'}
    elif platform == 'deepcoin':
        common_style = {'display': 'flex'}
        deepcoin_style = {'display': 'block'}
    elif platform == 'ostium':
        ostium_style = {'display': 'block'}
        # 显示休市时间段配置
        forbidden_hours_style = {
            'backgroundColor': '#FFF7ED',
            'padding': '15px',
            'borderRadius': '8px',
            'marginBottom': '12px',
            'border': '1px solid #FED7AA',
            'display': 'block'
        }
    elif platform == 'hyperliquid':
        # Hyperliquid 也使用私钥，但不需要休市时间配置
        ostium_style = {'display': 'block'}
        forbidden_hours_style = {'display': 'none'}
        
    return common_style, deepcoin_style, ostium_style, forbidden_hours_style


@app.callback(
    [Output('active-instances', 'data'),
     Output('startup-success-dialog', 'displayed')],
    [Input('btn-modal-launch', 'n_clicks'),
     Input('instance-monitor', 'n_intervals'),
     Input('balance-refresher', 'n_intervals'),
     Input({'type': 'btn-stop-instance', 'index': ALL}, 'n_clicks')],
    [State('active-instances', 'data'),
     State('modal-platform', 'value'),
     State('modal-strategy', 'value'),
     State('modal-symbol', 'value'),
     State('modal-size', 'value'),
     State('modal-leverage', 'value'),
     State('modal-tp', 'value'),
     State('modal-sl', 'value'),
     State('modal-api-key', 'value'),
     State('modal-api-secret', 'value'),
     State('modal-passphrase', 'value'),
     State('modal-private-key', 'value'),
     State('forbidden-ranges-store', 'data'),
     State('current-user-store', 'data')]
)
def manage_instances(n_launch, n_monitor, n_balance, n_stops, current_instances, 
                     platform, strategy, symbol, size, leverage, tp, sl, 
                     api_key, api_secret, passphrase, private_key, forbidden_ranges, user):
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'] if ctx.triggered else ""
    current_instances = current_instances or []
    
    # 首次加载或刷新时，从数据库恢复当前用户的实例（仅显示本账户的）
    user_id = (user or {}).get('id')
    if not current_instances and is_port_in_use(8005) and user_id:
        try:
            # 获取当前用户在 DB 中登记的实盘 instance_id 列表
            my_live_ids = set(db_manager.get_user_instance_ids(user_id, 'live'))
            if not my_live_ids:
                pass
            else:
                response = requests.get("http://127.0.0.1:8005/instances", timeout=5)
                if response.status_code == 200:
                    instances_data = response.json()
                    webhook_instances = instances_data.get('instances', [])
                    w_pid = get_webhook_pid()
                    for inst_info in webhook_instances:
                        inst_id = inst_info.get('instance_id', inst_info) if isinstance(inst_info, dict) else inst_info
                        if inst_id not in my_live_ids:
                            continue  # 非本账户实例，跳过
                        if isinstance(inst_info, str):
                            recovered_platform = 'hyperliquid' if inst_id.startswith('hl_') else 'ostium'
                            recovered_symbol = 'USD/JPY'
                            recovered_strategy = f'{recovered_platform.capitalize()} ({inst_id})'
                        else:
                            recovered_platform = inst_info.get('exchange', 'ostium')
                            recovered_symbol = inst_info.get('symbol', 'USD/JPY')
                            recovered_strategy = inst_info.get('strategy', inst_id)
                        current_instances.append({
                            'id': inst_id,
                            'pid': w_pid,
                            'platform': recovered_platform,
                            'strategy_name': recovered_strategy,
                            'symbol': recovered_symbol,
                            'start_time': '--:--',
                            'balance': '--',
                            'webhook_instance_id': inst_id,
                            'status': 'running'
                        })
                    if current_instances:
                        logger.info(f"🔄 恢复当前用户 {len(current_instances)} 个实盘实例")
        except Exception as e:
            logger.debug(f"恢复实例列表失败: {e}")

    # 1. 停止逻辑
    if 'btn-stop-instance' in trigger_id:
        try:
            import json as _json
            prop_dict = _json.loads(trigger_id.split('.')[0])
            instance_id = prop_dict['index']
            new_instances = []
            for inst in current_instances:
                if inst['id'] == instance_id:
                    # 检查是否为 Webhook 实例 (Ostium 或 Hyperliquid)
                    if inst.get('platform') in ['ostium', 'hyperliquid'] and 'webhook_instance_id' in inst:
                        # 调用 Webhook API 注销实例
                        webhook_instance_id = inst['webhook_instance_id']
                        webhook_port = 8005
                        unregister_url = f"http://127.0.0.1:{webhook_port}/unregister_instance/{webhook_instance_id}"
                        
                        try:
                            response = requests.post(unregister_url, timeout=5)
                            if response.status_code == 200:
                                logger.info(f"✅ Webhook 实例 {webhook_instance_id} 已注销")
                                if user_id:
                                    db_manager.delete_user_instance(user_id, 'live', webhook_instance_id)
                            else:
                                logger.warning(f"⚠️ 注销 Webhook 实例失败: HTTP {response.status_code}")
                        except Exception as e:
                            logger.warning(f"⚠️ 调用注销 API 失败: {e}")
                    else:
                        # 非-Webhook 实例，杀死进程
                        try:
                            import psutil
                            if inst['pid'] > 0:  # 确保 PID 有效
                                proc = psutil.Process(inst['pid'])
                                for child in proc.children(recursive=True): child.kill()
                                proc.kill()
                                logger.info(f"✅ 停止实例: {inst['id']} (PID: {inst['pid']})")
                                if user_id:
                                    db_manager.delete_user_instance(user_id, 'live', inst['id'])
                        except Exception as e:
                            logger.warning(f"⚠️ 停止进程失败: {e}")
                else:
                    new_instances.append(inst)
            return new_instances, False
        except Exception as e:
            logger.error(f"停止实例失败: {e}")

    # 2. 启动逻辑 (注入完整参数)
    if 'btn-modal-launch' in trigger_id and n_launch:
        # 特殊处理：Ostium 和 Hyperliquid 使用 Webhook 模式，需要检测 8005 端口是否已启动
        if platform in ['ostium', 'hyperliquid']:
            webhook_port = 8005
            
            # 生成实例 ID
            prefix = "hl" if platform == "hyperliquid" else "ostium"
            instance_id = f"{prefix}_{datetime.now().strftime('%H%M%S_%f')}"
            
            # 检查 Webhook 服务是否启动
            if not is_port_in_use(webhook_port):
                # 第一次启动 Ostium，需要启动 Webhook 服务
                logger.info(f"检测到 {webhook_port} 端口未被占用，启动 Webhook 服务...")
                
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                env['PYTHONPATH'] = project_root + (os.pathsep + env['PYTHONPATH'] if 'PYTHONPATH' in env else "")
                
                cmd = [
                    sys.executable, '-u', '-m', 'backpack_quant_trading.webhook_service'
                ]
                
                try:
                    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'log'))
                    if not os.path.exists(log_dir): os.makedirs(log_dir)
                    log_path = os.path.join(log_dir, 'webhook_console.log')
                    
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(f"\n{'='*20} [{datetime.now().strftime('%H:%M:%S')}] Launching Webhook Service (Port {webhook_port}) {'='*20}\n")
                        process = subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, cwd=project_root)
                    
                    logger.info(f"Webhook 服务进程已启动 (PID: {process.pid})，异步等待端口启用...")
                except Exception as e: 
                    logger.error(f"启动 Webhook 服务失败: {e}")
                    return current_instances, False
            
            # Webhook 服务已运行，异步注册新引擎实例
            logger.info(f"Webhook 服务已在端口 {webhook_port} 运行，准备注册实例: {instance_id}")
            
            # 调试:检查 private_key 是否为空
            if not private_key:
                logger.error(f"❌ Private Key 为空! private_key={private_key}")
                return current_instances, False
            
            logger.info(f"✅ Private Key 已提供,长度: {len(str(private_key))}")
            
            # 处理休市时间段 - 转换为逗号分隔的字符串
            forbidden_hours_str = ""
            if platform == 'ostium' and forbidden_ranges:
                hours_set = set()
                for start, end in forbidden_ranges:
                    for h in range(start, end):
                        hours_set.add(h)
                forbidden_hours_str = ','.join(str(h) for h in sorted(hours_set))
                logger.info(f"休市时间段: {forbidden_hours_str}")
            
            # 构建注册请求
            register_url = f"http://127.0.0.1:{webhook_port}/register_instance"
            strategy_display_name = STRATEGY_DISPLAY_NAMES.get(strategy, strategy)
            register_data = {
                "instance_id": instance_id,
                "exchange": platform,  # 明确指定交易所
                "private_key": str(private_key or ""),
                "strategy_name": strategy_display_name,  # 添加策略名
                "symbol": symbol,
                "leverage": int(leverage) if leverage else 50,
                "margin_amount": str(size),
                "stop_loss_ratio": sl / 100,
                "take_profit_ratio": tp / 100,
                "forbidden_hours": forbidden_hours_str
            }
            
            # 先创建实例卡片（显示"注册中..."）
            w_pid = process.pid if 'process' in locals() else get_webhook_pid()
            new_instance = {
                'id': instance_id,
                'pid': w_pid,  # 使用 Webhook 服务的 PID
                'platform': platform,
                'strategy_name': f'{strategy_display_name} ({symbol})',
                'symbol': symbol,
                'start_time': datetime.now().strftime('%H:%M'),
                'balance': '注册中...',
                'webhook_instance_id': instance_id,
                'status': 'registering'  # 标记为注册中
            }
            current_instances.append(new_instance)
            if user_id:
                import json
                # 仅存平台/策略/交易对等元数据，不存 API Key、私钥等敏感信息
                cfg = json.dumps({'platform': platform, 'strategy': strategy_display_name, 'symbol': symbol})
                db_manager.save_user_instance(user_id, 'live', instance_id, cfg)

            # 立即返回，不等待注册完成
            logger.info(f"⏳ 实例 {instance_id} 已添加到列表，后台异步注册中...")
            
            # 后台异步注册（使用 threading）
            import threading
            import asyncio
            def async_register():
                # 修复 Python 3.9+ 在新线程中缺失事件循环的问题
                try:
                    asyncio.get_event_loop()
                except RuntimeError:
                    asyncio.set_event_loop(asyncio.new_event_loop())
                
                import time
                max_retries = 5  # 增加到 5 次
                retry_delay = 1.0  # 增加延迟到 1 秒
                
                for attempt in range(max_retries):
                    try:
                        response = requests.post(register_url, json=register_data, timeout=10)  # 增加超时到 10 秒
                        if response.status_code == 200:
                            result = response.json()
                            logger.info(f"✅ 引擎实例注册成功: {instance_id}")
                            logger.info(f"📋 配置: {result.get('config', {})}")
                            webhook_url = f"http://127.0.0.1:{webhook_port}/webhook"
                            logger.info(f"🔗 TradingView Webhook URL: {webhook_url}")
                            logger.info(f"🎯 实例 ID: {instance_id}")
                            return
                        else:
                            logger.warning(f"⚠️ 注册失败 (HTTP {response.status_code})，第 {attempt + 1}/{max_retries} 次尝试")
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                    except requests.exceptions.Timeout:
                        logger.warning(f"⚠️ Webhook 服务响应较慢，第 {attempt + 1}/{max_retries} 次尝试...")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                    except requests.exceptions.ConnectionError:
                        logger.warning(f"⚠️ Webhook 服务还未就绪，第 {attempt + 1}/{max_retries} 次尝试...")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                    except Exception as e:
                        logger.error(f"❌ 注册失败: {e}")
                        return
                
                logger.error(f"❌ 实例 {instance_id} 注册失败，请检查日志")
            
            # 启动后台线程
            thread = threading.Thread(target=async_register, daemon=True)
            thread.start()
            
            return current_instances, True
        
        # 非-Ostium 平台的启动逻辑
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        # 将密钥注入环境变量，供子进程读取
        if platform == 'backpack':
            env['BACKPACK_API_KEY'] = str(api_key or "")
            env['BACKPACK_API_SECRET'] = str(api_secret or "")
        elif platform == 'deepcoin':
            env['DEEPCOIN_API_KEY'] = str(api_key or "")
            env['DEEPCOIN_API_SECRET'] = str(api_secret or "")
            env['DEEPCOIN_PASSPHRASE'] = str(passphrase or "")
        elif platform == 'ostium':
            env['OSTIUM_PRIVATE_KEY'] = str(private_key or "")

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        env['PYTHONPATH'] = project_root + (os.pathsep + env['PYTHONPATH'] if 'PYTHONPATH' in env else "")
        
        # 构建命令，加入下单保证金、杠杆、止盈、止损
        cmd = [
            sys.executable, '-u', '-m', 'backpack_quant_trading.main',
            '--mode', 'live', 
            '--strategy', strategy, 
            '--exchange', platform, 
            '--symbols', symbol, 
            '--position-size', str(size),  # AI策略:保证金; 其他策略:仓位比例
            '--leverage', str(leverage),    # 杠杆倍数
            '--take-profit', str(tp / 100),  # 转为小数: 2.0% -> 0.02
            '--stop-loss', str(sl / 100)     # 转为小数: 1.5% -> 0.015
        ]
        
        try:
            log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'log'))
            if not os.path.exists(log_dir): os.makedirs(log_dir)
            log_path = os.path.join(log_dir, 'live_console.log')
            
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*20} [{datetime.now().strftime('%H:%M:%S')}] Launching Instance: {platform} {'='*20}\n")
                process = subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, cwd=project_root)
            
            inst_id = f"{platform}_{strategy}_{datetime.now().strftime('%H%M%S')}"
            new_instance = {
                'id': inst_id,
                'pid': process.pid,
                'platform': platform,
                'strategy_name': STRATEGY_DISPLAY_NAMES.get(strategy, strategy),
                'symbol': symbol,
                'start_time': datetime.now().strftime('%H:%M'),
                'balance': '--'
            }
            current_instances.append(new_instance)
            if user_id:
                import json
                # 仅存元数据，不存 API Key、私钥
                cfg = json.dumps({'platform': platform, 'strategy': strategy, 'symbol': symbol})
                db_manager.save_user_instance(user_id, 'live', inst_id, cfg)
            return current_instances, True
        except Exception as e: print(f"Launch Error: {e}")

    # 3. 状态与余额轮询
    if 'instance-monitor' in trigger_id or 'balance-refresher' in trigger_id:
        from sqlalchemy import create_engine
        from backpack_quant_trading.config.settings import config
        engine = create_engine(config.database_url)
        import psutil
        alive_instances = []
        changed = False
        for inst in current_instances:
            # Webhook 实例 (pid=0) 总是认为活着，需要检查 8005 端口
            if inst.get('platform') in ['ostium', 'hyperliquid'] and inst.get('pid') == 0:
                # 检查 Webhook 服务是否还在运行
                if is_port_in_use(8005):
                    # 检查是否仍在注册中
                    if inst.get('status') == 'registering':
                        # 尝试查询 Webhook API 检查是否注册成功
                        try:
                            webhook_instance_id = inst.get('webhook_instance_id', inst['id'])
                            check_url = f"http://127.0.0.1:8005/instances"
                            response = requests.get(check_url, timeout=5)
                            if response.status_code == 200:
                                instances_data = response.json()
                                logger.info(f"🔍 查询实例列表: {instances_data.get('instances', [])}")
                                logger.info(f"🔍 当前检查实例 ID: {webhook_instance_id}")
                                # 检查实例是否已注册
                                if webhook_instance_id in instances_data.get('instances', []):
                                    inst['balance'] = '同步中...'
                                    inst['status'] = 'running'
                                    changed = True
                                    logger.info(f"✅ 实例 {webhook_instance_id} 注册成功，状态已更新")
                                else:
                                    logger.warning(f"⚠️ 实例 {webhook_instance_id} 还未注册")
                            else:
                                logger.warning(f"⚠️ 查询 Webhook API 失败: HTTP {response.status_code}")
                        except Exception as e:
                            logger.error(f"❌ 检查注册状态失败: {e}")
                    
                    # 刷新余额
                    if 'balance-refresher' in trigger_id and inst.get('status') != 'registering':
                        try:
                            # 使用 Webhook API 查询余额
                            webhook_instance_id = inst.get('webhook_instance_id', inst['id'])
                            balance_url = f"http://127.0.0.1:8005/balance/{webhook_instance_id}"
                            response = requests.get(balance_url, timeout=5)
                            if response.status_code == 200:
                                balance_data = response.json()
                                inst['balance'] = f"{balance_data['balance']:.2f}"
                                changed = True
                        except Exception as e:
                            logger.debug(f"查询余额失败: {e}")
                    alive_instances.append(inst)
                else:
                    changed = True  # Webhook 服务已停止
            elif inst.get('pid', 0) > 0 and psutil.pid_exists(inst['pid']):
                if 'balance-refresher' in trigger_id:
                    try:
                        # 增加查询字段适配
                        res = pd.read_sql_query(f"SELECT portfolio_value FROM portfolio_history WHERE source='{inst['platform']}' ORDER BY timestamp DESC LIMIT 1", engine)
                        if not res.empty:
                            # 【修复】确保转换为float,避免字符串格式化错误
                            portfolio_value = float(res.iloc[0]['portfolio_value'])
                            inst['balance'] = f"{portfolio_value:.2f}"
                            changed = True
                    except Exception as e:
                        logger.debug(f"查询余额失败: {e}")
                        pass
                alive_instances.append(inst)
            else:
                changed = True
        if changed or 'balance-refresher' in trigger_id: 
            return alive_instances, False

    return current_instances or [], False


@app.callback(
    Output('active-instances-container', 'children'),
    [Input('active-instances', 'data')]
)
def update_instance_cards(instances):
    if not instances:
        return html.Div([
            html.P("暂无运行中的策略，请增加新策略", style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})
        ])
    
    return [
        html.Div([
            # 左侧信息区
            html.Div([
                # 平台标签和状态
                html.Div([
                    html.Span(inst['platform'].capitalize(), style={
                        'backgroundColor': '#F0B90B' if inst['platform'] == 'ostium' else '#3B82F6',
                        'color': 'white',
                        'padding': '2px 8px',
                        'borderRadius': '4px',
                        'fontSize': '10px',
                        'fontWeight': 'bold',
                        'marginRight': '8px'
                    }),
                    html.Span(
                        "● REGISTERING" if inst.get('status') == 'registering' else "● RUNNING",
                        style={
                            'color': '#FFA500' if inst.get('status') == 'registering' else COLORS['success'],
                            'fontSize': '10px',
                            'fontWeight': 'bold'
                        }
                    )
                ], style={'marginBottom': '8px'}),
                
                # 策略名称
                html.H3(inst['strategy_name'], style={
                    'margin': '0 0 6px 0',
                    'fontSize': '15px',
                    'fontWeight': '700',
                    'color': COLORS['text']
                }),
                
                # 交易对
                html.P("💹 " + str(inst['symbol']), style={
                    'margin': '0 0 4px 0',
                    'fontSize': '12px',
                    'color': COLORS['text']
                }),
                
                # 启动时间和 PID
                html.P("🕒 " + str(inst['start_time']) + " | PID: " + str(inst['pid']), style={
                    'margin': '0',
                    'fontSize': '10px',
                    'color': COLORS['text_dim']
                })
            ], style={'flex': '1'}),
            
            # 右侧余额和操作区
            html.Div([
                html.Div([
                    html.P("💰 账户余额", style={
                        'margin': '0',
                        'fontSize': '10px',
                        'color': COLORS['text_dim']
                    }),
                    html.H2(f"{inst['balance']} USD", style={
                        'margin': '4px 0 0 0',
                        'color': COLORS['accent'],
                        'fontSize': '16px',
                        'fontWeight': '800'
                    })
                ], style={'textAlign': 'right', 'marginBottom': '10px'}),
                
                html.Button("停止", id={'type': 'btn-stop-instance', 'index': inst['id']}, style={
                    'backgroundColor': COLORS['danger'],
                    'color': 'white',
                    'border': 'none',
                    'padding': '6px 16px',
                    'borderRadius': '4px',
                    'cursor': 'pointer',
                    'fontSize': '12px',
                    'fontWeight': '600',
                    'width': '100%',
                    'transition': 'all 0.2s'
                })
            ], style={'minWidth': '110px', 'display': 'flex', 'flexDirection': 'column'})
        ], style={
            'backgroundColor': COLORS['card'],
            'border': '1px solid ' + COLORS['border'],
            'borderRadius': '8px',
            'padding': '14px',
            'marginBottom': '12px',
            'display': 'flex',
            'alignItems': 'center',
            'boxShadow': COLORS['shadow'],
            'transition': 'all 0.2s'
        }) for inst in instances
    ]


@app.callback(
    Output('control-log', 'children'),
    [Input('interval-component', 'n_intervals')],
    [State('active-instances', 'data'),
     State('control-log-store', 'data')]
)
def update_terminal_logs(n, active_instances, status_logs):
    """从日志文件读取实时内容 (最新在上)"""
    if not dash.callback_context.outputs_list:
        return dash.no_update
    
    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'log'))
    
    # 智能检测日志文件: 如果有任何 Webhook 相关的平台，显示 webhook 日志
    has_webhook_platform = False
    has_live_trading_platform = False
    
    if active_instances and len(active_instances) > 0:
        for inst in active_instances:
            if inst.get('platform') in ['ostium', 'hyperliquid']:
                has_webhook_platform = True
            else:
                has_live_trading_platform = True
    
    # 决定显示哪个日志
    log_files = []
    if has_webhook_platform:
        log_files.append(('webhook_server.log', 'Webhook 服务日志'))
    if has_live_trading_platform:
        log_files.append(('live_console.log', '实盘策略日志'))
    
    # 如果没有实例，默认显示 live 日志
    if not log_files:
        log_files.append(('live_console.log', '系统日志'))
    
    all_log_lines = []
    
    # 辅助函数：高效读取文件末尾
    def tail_file(filename, n=200):
        file_path = os.path.join(log_dir, filename)
        if not os.path.exists(file_path):
            return [f"[等待 {filename} 生成...]"]
        try:
            with open(file_path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                # 预估缓冲区大小 (假设每行 200 字节)
                buffer_size = n * 300 
                if buffer_size > size: buffer_size = size
                
                f.seek(-buffer_size, os.SEEK_END)
                chunk = f.read(buffer_size).decode('utf-8', errors='replace')
                lines = chunk.splitlines()
                return lines[-n:]
        except Exception as e:
            return [f"[读取 {filename} 失败: {e}]"]

    # 读取所有相关日志文件
    for log_filename, log_label in log_files:
        lines = tail_file(log_filename, 200)
        for line in lines:
            line = line.strip()
            if not line: continue
            if len(log_files) > 1:
                all_log_lines.append(f"[{log_label}] {line}")
            else:
                all_log_lines.append(line)
    
    # 增强的时间戳提取正则 (支持多种格式和逗号/点分隔的毫秒)
    import re
    time_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2})')

    def extract_time(log_line):
        match = time_pattern.search(log_line)
        return match.group(1) if match else "0000-00-00 00:00:00"

    # 排序：最新在最上面 (reverse=True)
    all_log_lines.sort(key=extract_time, reverse=True)
    
    # 截取展示
    display_logs = all_log_lines[:150]
    
    if not display_logs:
        return "等待日志输出..."
        
    # 构建最终显示内容，增加来源图例说明
    header = f"{'='*20} 实时日志聚合视图 (当前活跃平台: {', '.join([f[1] for f in log_files])}) {'='*20}\n"
    return header + "\n".join(display_logs)

@app.callback(
    Output('sidebar-balance-area', 'children'),
    [Input('balance-interval', 'n_intervals'),
     Input('active-instances', 'data')],
    [State('current-user-store', 'data')]
)
def update_sidebar_balance(n, active_instances, current_user):
    """更新侧边栏余额"""
    if not current_user: 
        return ""
    
    # 从活动实例中获取平台，如果没有则默认使用 'backpack'
    exchange = 'backpack'  # 默认值
    if active_instances and len(active_instances) > 0:
        # 使用第一个活动实例的平台
        exchange = active_instances[0].get('platform', 'backpack')
    
    # 【关键修复】统一小写处理
    exchange = exchange.lower()
    
    if exchange == 'ostium':
        try:
            from eth_account import Account
            rpc_url = config.ostium.RPC_URL
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            
            # 使用配置文件中的私钥
            pk = config.ostium.PRIVATE_KEY
            
            if not pk:
                return html.Div([
                    html.P("💰 钱包余额", style={'color': COLORS['accent'], 'fontSize': '11px', 'margin': '0 0 8px 0'}),
                    html.P("未配置私钥", style={'fontSize': '12px', 'color': COLORS['text_dim']})
                ])
                
            account = Account.from_key(pk)
            wallet_address = account.address
            
            eth_balance = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
            
            # USDC on Arbitrum (Example address)
            usdc_address = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
            usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
            usdc_contract = w3.eth.contract(address=usdc_address, abi=usdc_abi)
            try:
                usdc_balance = usdc_contract.functions.balanceOf(wallet_address).call() / (10 ** 6)
            except:
                usdc_balance = 0
            
            return html.Div([
                html.P("💰 Ostium 钱包", style={'color': COLORS['accent'], 'fontSize': '11px', 'margin': '0 0 8px 0'}),
                html.Div([
                    html.P(f"{eth_balance:.4f} ETH", style={'margin': '0', 'fontSize': '14px', 'fontWeight': '600'}),
                    html.P(f"{usdc_balance:.2f} USDC", style={'margin': '4px 0 0 0', 'fontSize': '13px', 'color': COLORS['text_dim']}),
                    html.P(f"{wallet_address[:6]}...{wallet_address[-4:]}", style={'fontSize': '10px', 'color': COLORS['text_dim'], 'marginTop': '8px'})
                ])
            ])
        except Exception as e:
            return html.P(f"获取余额失败", style={'fontSize': '10px', 'color': COLORS['danger']})
    
    # Backpack / Deepcoin 余额
    # 【关键修复】显示首字母大写的平台名称
    platform_display_name = exchange.capitalize()  # backpack -> Backpack, deepcoin -> Deepcoin
    
    try:
        # 尝试从数据库 portfolio_history 获取最新记录
        portfolio_df = pd.read_sql_query(
            f"SELECT * FROM portfolio_history WHERE source = '{exchange}' ORDER BY timestamp DESC LIMIT 1",
            engine
        )
        if not portfolio_df.empty:
            latest = portfolio_df.iloc[0]
            val = float(latest.get('portfolio_value', 0))
            cash = float(latest.get('cash_balance', 0))
            return html.Div([
                html.P(f"💰 {platform_display_name} 资产", style={'color': COLORS['accent'], 'fontSize': '11px', 'margin': '0 0 8px 0'}),
                html.P(f"${val:,.2f}", style={'margin': '0', 'fontSize': '14px', 'fontWeight': '600'}),
                html.P(f"现金: ${cash:,.2f}", style={'margin': '4px 0 0 0', 'fontSize': '12px', 'color': COLORS['text_dim']})
            ])
    except:
        pass

    return html.Div([
        html.P(f"💰 {platform_display_name} 资产", style={'color': COLORS['accent'], 'fontSize': '11px', 'margin': '0 0 8px 0'}),
        html.P("等待API连接...", style={'fontSize': '12px', 'color': COLORS['text_dim']})
    ])



@app.callback(
    [Output('portfolio-summary', 'children'),
     Output('portfolio-chart', 'figure'),
     Output('positions-table', 'children'),
     Output('orders-table', 'children'),
     Output('trades-table', 'children'),
     Output('risk-events-table', 'children')],
    [Input('interval-component', 'n_intervals'),
     Input('active-instances', 'data')]
)
def update_dashboard(n, active_instances):
    """更新数据大屏 (增加平台过滤 & 样式美化)"""
    # 从活动实例中获取平台，如果没有则默认使用 'backpack'
    selected_exchange = 'backpack'  # 默认值
    if active_instances and len(active_instances) > 0:
        # 使用第一个活动实例的平台
        selected_exchange = active_instances[0].get('platform', 'backpack')
    
    if not dash.callback_context.outputs_list:
        return [dash.no_update] * 6
        
    # 初始化数据
    try:
        # 查询组合历史数据 - 增加平台过滤
        portfolio_df = pd.read_sql_query(
            f"SELECT * FROM portfolio_history WHERE source = '{selected_exchange}' ORDER BY timestamp DESC LIMIT 100",
            engine
        )
    except:
        portfolio_df = pd.DataFrame()

    try:
        # 持仓数据
        positions_df = pd.read_sql_query(
            f"SELECT * FROM positions WHERE source = '{selected_exchange}' AND closed_at IS NULL",
            engine
        )
    except:
        positions_df = pd.DataFrame()

    try:
        # 订单数据
        orders_df = pd.read_sql_query(
            f"SELECT * FROM orders WHERE source = '{selected_exchange}' ORDER BY created_at DESC LIMIT 20",
            engine
        )
    except:
        orders_df = pd.DataFrame()

    try:
        # 交易记录
        trades_df = pd.read_sql_query(
            f"SELECT * FROM trades WHERE source = '{selected_exchange}' ORDER BY created_at DESC LIMIT 20",
            engine
        )
    except:
        trades_df = pd.DataFrame()

    try:
        # 风险事件
        risk_df = pd.read_sql_query(
            f"SELECT * FROM risk_events WHERE source = '{selected_exchange}' ORDER BY created_at DESC LIMIT 10",
            engine
        )
    except:
        risk_df = pd.DataFrame()

    # 1. 概览卡片渲染
    if not portfolio_df.empty:
        latest = portfolio_df.iloc[0]
        prev = portfolio_df.iloc[1] if len(portfolio_df) > 1 else latest
        
        def create_summary_card(title, value, unit="$", is_pnl=False):
            val_num = float(value or 0)
            color = COLORS['text']
            prefix = ""
            if is_pnl:
                color = COLORS['success'] if val_num > 0 else COLORS['danger'] if val_num < 0 else COLORS['text']
                prefix = "+" if val_num > 0 else ""
            
            return html.Div([
                html.Div([
                    html.P(title, style={'color': COLORS['text_dim'], 'fontSize': '12px', 'margin': '0', 'textTransform': 'uppercase', 'letterSpacing': '1px'}),
                    html.Div(style={'width': '12px', 'height': '2px', 'backgroundColor': color, 'marginTop': '4px'})
                ], style={'marginBottom': '16px'}),
                html.H3(f"{prefix}{unit if unit == '$' else ''}{val_num:,.2f}{unit if unit != '$' else ''}", 
                        className='num-font',
                        style={'margin': '0', 'color': color, 'fontSize': '28px', 'fontWeight': '800', 'textShadow': f'0 0 10px {color}44'})
            ], className='card-tech')

        summary = [
            create_summary_card("总资产价值", latest.get('portfolio_value', 0)),
            create_summary_card("可用现金", latest.get('cash_balance', 0)),
            create_summary_card("当日盈亏", latest.get('daily_pnl', 0), is_pnl=True),
            create_summary_card("当日收益率", latest.get('daily_return', 0), unit="", is_pnl=True)
        ]
    else:
        summary = [html.P("等待数据更新...", style={'color': COLORS['text_dim']})]

    # 2. 净值图表美化
    fig = go.Figure()
    if not portfolio_df.empty:
        df_sorted = portfolio_df.sort_values('timestamp')
        fig.add_trace(go.Scatter(
            x=df_sorted['timestamp'],
            y=df_sorted['portfolio_value'],
            mode='lines',
            fill='tozeroy',
            name='组合价值',
            line=dict(color=COLORS['accent'], width=2),
            fillcolor='rgba(240, 185, 11, 0.1)'
        ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(
            showgrid=True, gridcolor='#2b2f36', gridwidth=1,
            tickfont=dict(color=COLORS['text_dim'], size=10),
            rangeslider=dict(visible=False)
        ),
        yaxis=dict(
            showgrid=True, gridcolor='#2b2f36', gridwidth=1,
            tickfont=dict(color=COLORS['text_dim'], size=10),
            side='right'
        ),
        font=dict(family='Inter, monospace', color=COLORS['text']),
        hovermode='x unified',
        height=400,
        showlegend=False
    )

    # 3. 持仓表格
    if not positions_df.empty:
        positions_table = html.Table([
            html.Thead(html.Tr([
                html.Th('交易对'), html.Th('方向'), html.Th('数量'), 
                html.Th('入场价'), html.Th('当前价'), html.Th('未实现盈亏')
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(row['symbol'], style={'fontWeight': '600'}),
                    html.Td(row['side'].upper(), style={'color': COLORS['success'] if row['side'] == 'long' else COLORS['danger']}),
                    html.Td(f"{float(row['quantity'] or 0):.4f}"),
                    html.Td(f"${float(row['entry_price'] or 0):,.2f}"),
                    html.Td(f"${float(row.get('current_price') or 0):,.2f}"),
                    html.Td(
                        f"${float(row.get('unrealized_pnl') or 0):,.2f}",
                        style={'color': COLORS['success'] if float(row.get('unrealized_pnl') or 0) > 0 else COLORS['danger'], 'fontWeight': '600'}
                    )

                ]) for _, row in positions_df.iterrows()
            ])
        ])
    else:
        positions_table = html.Div("无活跃持仓", style={'textAlign': 'center', 'padding': '40px', 'color': COLORS['text_dim']})

    # 4. 订单表格
    if not orders_df.empty:
        orders_table = html.Table([
            html.Thead(html.Tr([
                html.Th('交易对'), html.Th('类型'), html.Th('方向'), 
                html.Th('价格'), html.Th('数量'), html.Th('状态')
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(row['symbol']),
                    html.Td(row['order_type'].upper()),
                    html.Td(row['side'].upper(), style={'color': COLORS['success'] if row['side'] == 'buy' else COLORS['danger']}),
                    html.Td(f"${float(row['price'] or 0):,.2f}" if pd.notna(row['price']) else "市价"),
                    html.Td(f"{float(row['quantity'] or 0):.4f}"),
                    html.Td(row['status'].upper(), style={'color': COLORS['accent'] if row['status'] in ['open', 'new'] else COLORS['text_dim']})

                ]) for _, row in orders_df.head(8).iterrows()
            ])
        ])
    else:
        orders_table = html.Div("无活跃订单", style={'textAlign': 'center', 'padding': '40px', 'color': COLORS['text_dim']})

    # 5. 交易历史
    if not trades_df.empty:
        trades_table = html.Table([
            html.Thead(html.Tr([
                html.Th('时间'), html.Th('交易对'), html.Th('方向'), 
                html.Th('价格'), html.Th('成交额'), html.Th('盈亏')
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(str(row['created_at'])[11:19], style={'color': COLORS['text_dim']}),
                    html.Td(row['symbol']),
                    html.Td(row['side'].upper(), style={'color': COLORS['success'] if row['side'] in ['buy', 'long'] else COLORS['danger']}),
                    html.Td(f"${float(row['price'] or 0):,.2f}"),
                    html.Td(f"{float(row['quantity'] or 0):.4f}"),
                    html.Td(
                        f"${float(row.get('pnl_amount') or 0):,.2f}" if pd.notna(row.get('pnl_amount')) else "-",
                        style={'color': COLORS['success'] if float(row.get('pnl_amount') or 0) > 0 else COLORS['danger']}
                    )

                ]) for _, row in trades_df.head(8).iterrows()
            ])
        ])
    else:
        trades_table = html.Div("暂无成交历史", style={'textAlign': 'center', 'padding': '40px', 'color': COLORS['text_dim']})

    # 6. 风险事件
    if not risk_df.empty:
        risk_table = html.Div([
            html.Div([
                html.Div([
                    html.Span(row['event_type'], style={'color': COLORS['danger'] if row['severity'] == 'high' else COLORS['accent'], 'fontWeight': '600', 'fontSize': '12px'}),
                    html.Span(str(row['created_at'])[11:19], style={'float': 'right', 'color': COLORS['text_dim'], 'fontSize': '11px'})
                ], style={'marginBottom': '4px'}),
                html.P(row['description'], style={'margin': '0', 'fontSize': '13px', 'lineHeight': '1.4'})
            ], style={'padding': '12px', 'borderBottom': '1px solid ' + COLORS['border']})
            for _, row in risk_df.head(5).iterrows()
        ])
    else:
        risk_table = html.Div("系统运行正常", style={'textAlign': 'center', 'padding': '40px', 'color': COLORS['success']})

    return summary, fig, positions_table, orders_table, trades_table, risk_table


def render_grid_trading_layout():
    """合约网格交易布局"""
    return html.Div([
        # 页面标题
        html.Div([
            html.H2('合约网格交易', style={
                'margin': '0',
                'fontWeight': '800',
                'fontSize': '24px',
                'color': COLORS['text']
            }),
            html.P('自动化网格交易策略，高频买低卖高', style={
                'margin': '8px 0 0 0',
                'color': COLORS['text_dim'],
                'fontSize': '14px'
            })
        ], style={'marginBottom': '30px'}),
        
        # 网格配置卡片
        html.Div([
            html.H3('网格配置', style={
                'margin': '0 0 20px 0',
                'fontSize': '18px',
                'fontWeight': '700',
                'color': COLORS['text']
            }),
            
            html.Div([
                # 交易所选择和认证方式
                html.Div([
                    html.Div([
                        html.Label('选择交易所', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Dropdown(
                            id='grid-exchange',
                            options=[
                                {'label': '🎒 Backpack', 'value': 'backpack'},
                                {'label': '🪙 Deepcoin', 'value': 'deepcoin'},
                                {'label': '🌊 Ostium', 'value': 'ostium'},
                                {'label': '⚡ Hyper', 'value': 'hyper'},
                                {'label': 'HIP-3 (XYZ) 主网', 'value': 'hip3'},
                                {'label': 'HIP-3 测试网', 'value': 'hip3_testnet'}
                            ],
                            value='backpack',
                            clearable=False,
                            style={'borderRadius': '8px'}
                        )
                    ], style={'flex': '1', 'marginRight': '20px'}),
                    
                    html.Div([
                        html.Label('认证方式', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.RadioItems(
                            id='grid-auth-mode',
                            options=[
                                {'label': ' 系统默认', 'value': 'default'},
                                {'label': ' 手动输入', 'value': 'manual'}
                            ],
                            value='default',
                            labelStyle={'display': 'inline-block', 'marginRight': '20px', 'fontSize': '14px'},
                            style={'paddingTop': '10px'}
                        )
                    ], style={'flex': '1'}),
                ], style={'display': 'flex', 'marginBottom': '20px'}),

                # 手动密钥输入框 (默认隐藏)
                html.Div(id='grid-manual-keys-container', children=[
                    # Backpack / Deepcoin 共有
                    html.Div(id='grid-creds-common', children=[
                        html.Div([
                            html.Label('API Key / Access Key', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                            dcc.Input(id='grid-api-key', type='text', placeholder='输入 API Key', style={
                                'width': '100%', 'padding': '10px', 'borderRadius': '8px', 'border': '1px solid ' + COLORS['border']
                            })
                        ], style={'flex': '1', 'marginRight': '20px'}),
                        html.Div([
                            html.Label('Secret Key / Refresh Key', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                            dcc.Input(id='grid-secret-key', type='password', placeholder='输入 Secret Key', style={
                                'width': '100%', 'padding': '10px', 'borderRadius': '8px', 'border': '1px solid ' + COLORS['border']
                            })
                        ], style={'flex': '1'})
                    ], style={'display': 'flex', 'marginBottom': '15px'}),

                    # Deepcoin 独有 (Passphrase)
                    html.Div(id='grid-creds-deepcoin', children=[
                        html.Label('Passphrase (API 口令)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(id='grid-passphrase', type='password', placeholder='输入 API Passphrase', style={
                            'width': '100%', 'padding': '10px', 'borderRadius': '8px', 'border': '1px solid ' + COLORS['border']
                        })
                    ], style={'marginBottom': '15px'}),

                    # Ostium / Hyper 共用 (Private Key)
                    html.Div(id='grid-creds-ostium', children=[
                        html.Label('Private Key (Ostium/Hyper/HIP-3 钱包私钥)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(id='grid-private-key', type='password', placeholder='输入 0x 开头的私钥', style={
                            'width': '100%', 'padding': '10px', 'borderRadius': '8px', 'border': '1px solid ' + COLORS['border']
                        })
                    ], style={'marginBottom': '15px'}),
                ], style={
                    'display': 'none',
                    'backgroundColor': '#F9FAFB',
                    'padding': '15px',
                    'borderRadius': '8px',
                    'marginBottom': '20px',
                    'border': '1px dashed #D1D5DB'
                }),

                # 第一行：交易对、价格区间
                html.Div([
                    html.Div([
                        html.Label('交易对', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(
                            id='grid-symbol',
                            type='text',
                            value='ETH-USDT-SWAP',
                            placeholder='ETH-USDT-SWAP',
                            style={
                                'width': '100%',
                                'padding': '10px',
                                'fontSize': '14px',
                                'borderRadius': '8px',
                                'border': '1px solid ' + COLORS['border'],
                            }
                        )
                    ], style={'flex': '1', 'marginRight': '20px'}),
                    
                    html.Div([
                        html.Label('价格下限 (USDT)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(
                            id='grid-price-lower',
                            type='number',
                            value=3000,
                            placeholder='3000',
                            style={
                                'width': '100%',
                                'padding': '10px',
                                'fontSize': '14px',
                                'borderRadius': '8px',
                                'border': '1px solid ' + COLORS['border'],
                            }
                        )
                    ], style={'flex': '1', 'marginRight': '20px'}),
                    
                    html.Div([
                        html.Label('价格上限 (USDT)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(
                            id='grid-price-upper',
                            type='number',
                            value=3500,
                            placeholder='3500',
                            style={
                                'width': '100%',
                                'padding': '10px',
                                'fontSize': '14px',
                                'borderRadius': '8px',
                                'border': '1px solid ' + COLORS['border'],
                            }
                        )
                    ], style={'flex': '1'}),
                ], style={'display': 'flex', 'marginBottom': '20px'}),
                
                # 第二行：网格数量、单格投资
                html.Div([
                    html.Div([
                        html.Label('网格数量', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(
                            id='grid-count',
                            type='number',
                            value=20,
                            min=5,
                            max=100,
                            placeholder='20',
                            style={
                                'width': '100%',
                                'padding': '10px',
                                'fontSize': '14px',
                                'borderRadius': '8px',
                                'border': '1px solid ' + COLORS['border'],
                            }
                        )
                    ], style={'flex': '1', 'marginRight': '20px'}),
                    
                    html.Div([
                        html.Label('单格投资 (USDT)', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(
                            id='grid-investment-per-grid',
                            type='number',
                            value=10,
                            placeholder='10',
                            style={
                                'width': '100%',
                                'padding': '10px',
                                'fontSize': '14px',
                                'borderRadius': '8px',
                                'border': '1px solid ' + COLORS['border'],
                            }
                        )
                    ], style={'flex': '1', 'marginRight': '20px'}),
                    
                    html.Div([
                        html.Label('杠杆倍数', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Input(
                            id='grid-leverage',
                            type='number',
                            value=10,
                            min=1,
                            max=100,
                            placeholder='10',
                            style={
                                'width': '100%',
                                'padding': '10px',
                                'fontSize': '14px',
                                'borderRadius': '8px',
                                'border': '1px solid ' + COLORS['border'],
                            }
                        )
                    ], style={'flex': '1'}),
                ], style={'display': 'flex', 'marginBottom': '20px'}),

                # 网格类型：双向 / 做多网格 / 做空网格
                html.Div([
                    html.Div([
                        html.Label('网格类型', style={'fontWeight': '600', 'marginBottom': '8px', 'display': 'block', 'fontSize': '14px'}),
                        dcc.Dropdown(
                            id='grid-mode',
                            options=[
                                {'label': '双向网格（当前价下挂多、上挂空）', 'value': 'long_short'},
                                {'label': '做多网格（仅当前价下挂多，平仓点在上方）', 'value': 'long_only'},
                                {'label': '做空网格（仅当前价上挂空，平仓点在下方）', 'value': 'short_only'}
                            ],
                            value='long_short',
                            clearable=False,
                            style={'borderRadius': '8px'}
                        )
                    ], style={'flex': '1', 'maxWidth': '400px'}),
                ], style={'marginBottom': '20px'}),
                
                # 计算信息显示
                html.Div(id='grid-calculation-info', style={
                    'padding': '15px',
                    'backgroundColor': '#F9FAFB',
                    'borderRadius': '8px',
                    'marginBottom': '20px',
                    'fontSize': '14px',
                    'color': COLORS['text']
                }),
                
                # 启动按钮（支持多网格：单格 / 多+空 同时启动）
                html.Div([
                    html.Button('启动当前类型网格', id='btn-start-grid', className='btn-primary', style={
                        'padding': '12px 24px',
                        'fontSize': '16px',
                        'fontWeight': '600',
                        'borderRadius': '8px',
                        'marginRight': '10px'
                    }),
                    html.Button('同时启动多单+空单', id='btn-start-both', className='btn-primary', style={
                        'padding': '12px 24px',
                        'fontSize': '16px',
                        'fontWeight': '600',
                        'borderRadius': '8px',
                        'marginRight': '10px',
                        'backgroundColor': COLORS.get('primary', '#3B82F6')
                    }),
                    html.Button('停止全部网格', id='btn-stop-grid', className='btn-danger', style={
                        'padding': '12px 24px',
                        'fontSize': '16px',
                        'fontWeight': '600',
                        'borderRadius': '8px'
                    })
                ], style={'marginTop': '20px'})
            ])
        ], style={**CARD_STYLE}),

        # 运行中的网格实例（点击「启动当前类型网格」新增，每个卡片有停止按钮）
        html.Div([
            html.H3('运行中的网格实例', style={
                'margin': '0 0 16px 0',
                'fontSize': '18px',
                'fontWeight': '700',
                'color': COLORS['text']
            }),
            html.Div(id='grid-status-display', children=[
                html.P('网格未启动，点击上方「启动当前类型网格」新增实例', style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})
            ], style={
                'display': 'grid',
                'gridTemplateColumns': 'repeat(auto-fill, minmax(260px, 1fr))',
                'gap': '12px'
            }),
            # 状态自动刷新组件（每3秒刷新一次）
            dcc.Interval(
                id={'type': 'grid-refresh', 'index': 'status'},
                interval=3000,  # 3秒
                n_intervals=0
            )
        ], style={**CARD_STYLE}),
        
        # 交易记录卡片
        html.Div([
            html.H3('交易记录', style={
                'margin': '0 0 20px 0',
                'fontSize': '18px',
                'fontWeight': '700',
                'color': COLORS['text']
            }),
            html.Div(id='grid-trades-display', children=[
                html.P('暂无交易记录', style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})
            ])
        ], style={**CARD_STYLE}),
        
        # 网格日志卡片
        html.Div([
            html.H3('网格日志', style={
                'margin': '0 0 20px 0',
                'fontSize': '18px',
                'fontWeight': '700',
                'color': COLORS['text']
            }),
            html.Div(id='grid-logs-display', children=[
                html.P('暂无日志', style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})
            ], style={
                'maxHeight': '400px',
                'overflowY': 'auto',
                'backgroundColor': '#1E1E1E',
                'padding': '15px',
                'borderRadius': '8px',
                'fontFamily': 'Consolas, Monaco, monospace',
                'fontSize': '12px',
                'lineHeight': '1.6',
                'color': '#D4D4D4'
            }),
            # 日志自动刷新组件（每2秒刷新一次）
            dcc.Interval(
                id={'type': 'grid-refresh', 'index': 'logs'},
                interval=2000,  # 2秒
                n_intervals=0
            )
        ], style={**CARD_STYLE})
    ])


# 密钥输入框显示切换回调
@app.callback(
    [Output('grid-manual-keys-container', 'style'),
     Output('grid-creds-common', 'style'),
     Output('grid-creds-deepcoin', 'style'),
     Output('grid-creds-ostium', 'style')],
    [Input('grid-auth-mode', 'value'),
     Input('grid-exchange', 'value')]
)
def toggle_grid_manual_keys(auth_mode, exchange):
    if auth_mode != 'manual':
        return {'display': 'none'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'}
    
    # 基础容器样式
    container_style = {
        'display': 'block',
        'backgroundColor': '#F9FAFB',
        'padding': '15px',
        'borderRadius': '8px',
        'marginBottom': '20px',
        'border': '1px dashed #D1D5DB'
    }
    
    common_style = {'display': 'flex', 'marginBottom': '15px'} if exchange in ['backpack', 'deepcoin'] else {'display': 'none'}
    deepcoin_style = {'display': 'block', 'marginBottom': '15px'} if exchange == 'deepcoin' else {'display': 'none'}
    ostium_style = {'display': 'block', 'marginBottom': '15px'} if exchange in ['ostium', 'hyper', 'hip3', 'hip3_testnet'] else {'display': 'none'}
    
    return container_style, common_style, deepcoin_style, ostium_style


# 网格交易计算回调
@app.callback(
    Output('grid-calculation-info', 'children'),
    [Input('grid-price-lower', 'value'),
     Input('grid-price-upper', 'value'),
     Input('grid-count', 'value'),
     Input('grid-investment-per-grid', 'value'),
     Input('grid-leverage', 'value')]
)
def update_grid_calculation(price_lower, price_upper, grid_count, investment, leverage):
    """实时计算网格参数"""
    if not all([price_lower, price_upper, grid_count, investment, leverage]):
        return "请填写完整参数"
    
    if price_lower >= price_upper:
        return html.Div("⚠️ 价格下限必须小于上限", style={'color': COLORS['danger']})
    
    # 计算网格间距
    price_range = price_upper - price_lower
    grid_spacing = price_range / grid_count
    grid_spacing_percent = (grid_spacing / price_lower) * 100
    
    # 计算总投资
    total_investment = investment * grid_count
    
    # 计算实际持仓价值（考虑杠杆）
    position_value = total_investment * leverage
    
    # 计算单格利润
    # 1. 绝对金额利润 (考虑杠杆)
    profit_per_grid = investment * leverage * grid_spacing_percent / 100
    # 2. 收益率百分比 (对标欧意: 间距 * 杠杆 - 预估双边手续费)
    # 预估双边手续费率约 0.1% (0.05% * 2)
    profit_rate_percent = grid_spacing_percent * leverage - (0.1 * leverage)

    # 预估爆仓价 (对标欧意: 加入 0.5% 维持保证金率)
    avg_price = (price_lower + price_upper) / 2
    liq_price = avg_price * (1 - 1/leverage + 0.005) if leverage > 1 else 0
    
    return html.Div([
        html.Div([
            html.Span('📊 网格间距: ', style={'fontWeight': '600'}),
            html.Span(f'${grid_spacing:.2f} ({grid_spacing_percent:.2f}%)')
        ], style={'marginBottom': '10px'}),
        
        html.Div([
            html.Span('💰 总投资: ', style={'fontWeight': '600'}),
            html.Span(f'${total_investment:.2f} (保证金)')
        ], style={'marginBottom': '10px'}),
        
        html.Div([
            html.Span('📈 实际持仓价值: ', style={'fontWeight': '600'}),
            html.Span(f'${position_value:.2f} ({leverage}x杠杆)')
        ], style={'marginBottom': '10px'}),
        
        html.Div([
            html.Span('💵 单网格收益率: ', style={'fontWeight': '600'}),
            html.Span(f'{profit_rate_percent:.2f}% (${profit_per_grid:.2f})', style={'color': COLORS['success'], 'fontWeight': '700'})
        ], style={'marginBottom': '10px'}),
        
        html.Div([
            html.Span('🎯 建议网格数: ', style={'fontWeight': '600'}),
            html.Span(f'{grid_count} 格 (间距 {grid_spacing_percent:.2f}%)')
        ], style={'marginBottom': '10px'}),

        html.Div([
            html.Span('💥 预估强平价: ', style={'fontWeight': '600'}),
            html.Span(f'${liq_price:.2f}', style={'color': COLORS['danger'], 'fontWeight': '700'})
        ])
    ])


# 多网格管理器（替代单例 active_grid_strategy）
from backpack_quant_trading.strategy.grid_strategy import grid_manager

# 网格交易启动/停止回调（点击启动新增实例，每卡片有停止按钮）
@app.callback(
    Output('grid-status-display', 'children'),
    [Input('btn-start-grid', 'n_clicks'),
     Input('btn-start-both', 'n_clicks'),
     Input('btn-stop-grid', 'n_clicks'),
     Input({'type': 'btn-stop-grid-instance', 'index': ALL}, 'n_clicks'),
     Input({'type': 'grid-refresh', 'index': ALL}, 'n_intervals')],
    [State('grid-exchange', 'value'),
     State('grid-auth-mode', 'value'),
     State('grid-api-key', 'value'),
     State('grid-secret-key', 'value'),
     State('grid-passphrase', 'value'),
     State('grid-private-key', 'value'),
     State('grid-symbol', 'value'),
     State('grid-price-lower', 'value'),
     State('grid-price-upper', 'value'),
     State('grid-count', 'value'),
     State('grid-investment-per-grid', 'value'),
     State('grid-leverage', 'value'),
     State('grid-mode', 'value'),
     State('current-user-store', 'data')],
    prevent_initial_call=True
)
def manage_grid_trading(n_start, n_start_both, n_stop, n_stops, n_refresh,
    exchange, auth_mode, api_key, secret_key, passphrase, private_key, symbol, price_lower, price_upper, grid_count, investment, leverage, grid_mode, current_user):
    """管理网格交易启动/停止（点击启动新增实例，每卡片有停止按钮）"""
    user_id = (current_user or {}).get('id')
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    def _render_grid_cards(grids_dict):
        """生成运行中实例的卡片（每卡片有停止按钮）"""
        if not grids_dict:
            return html.P("网格未启动，点击上方「启动当前类型网格」新增实例", style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})
        cards = []
        for gid, info in grids_dict.items():
            mode_label = {'long_short': '双向', 'long_only': '做多', 'short_only': '做空'}.get(info['grid_mode'], info['grid_mode'])
            cards.append(html.Div([
                html.Div([
                    html.Div([
                        html.Span(info['exchange'].upper(), style={
                            'backgroundColor': COLORS['accent'], 'color': 'white', 'padding': '2px 8px',
                            'borderRadius': '4px', 'fontSize': '10px', 'fontWeight': 'bold', 'marginRight': '8px'
                        }),
                        html.Span("● 运行中", style={'color': COLORS['success'], 'fontSize': '10px', 'fontWeight': 'bold'})
                    ], style={'marginBottom': '8px'}),
                    html.H3(f"{info['symbol']} | {mode_label}", style={'margin': '0 0 6px 0', 'fontSize': '15px', 'fontWeight': '700', 'color': COLORS['text']}),
                    html.P(f"价格 ${info['current_price']:.2f} | 成交 {info['total_trades']} 次", style={'margin': '0', 'fontSize': '12px', 'color': COLORS['text_dim']})
                ], style={'flex': '1'}),
                html.Button("停止", id={'type': 'btn-stop-grid-instance', 'index': gid}, style={
                    'backgroundColor': COLORS['danger'], 'color': 'white', 'border': 'none', 'padding': '6px 16px',
                    'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': '600'
                })
            ], style={
                'backgroundColor': COLORS['card'], 'border': '1px solid ' + COLORS['border'], 'borderRadius': '8px',
                'padding': '14px', 'display': 'flex', 'alignItems': 'center', 'boxShadow': COLORS['shadow']
            }))
        return cards

    prop_id = ctx.triggered[0]['prop_id']
    trigger_id = prop_id.split('.')[0]

    def _filter_by_user(grids_dict):
        """仅显示当前用户的网格"""
        if not user_id:
            return {}
        my_ids = set(db_manager.get_user_instance_ids(user_id, 'grid'))
        return {k: v for k, v in grids_dict.items() if k in my_ids}

    # 停止单个实例（卡片上的停止按钮）
    if 'btn-stop-grid-instance' in trigger_id:
        try:
            tid = json.loads(trigger_id)
            grid_id = tid.get('index', '')
            if grid_id:
                grid_manager.stop(str(grid_id))
                if user_id:
                    db_manager.delete_user_instance(user_id, 'grid', str(grid_id))
        except Exception:
            pass
        all_grids = _filter_by_user(grid_manager.get_all())
        return _render_grid_cards(all_grids)

    # 以下为原主表单逻辑
    all_grids_raw = grid_manager.get_all()
    all_grids = _filter_by_user(all_grids_raw)

    def _create_api_client():
        if exchange == 'backpack':
            from backpack_quant_trading.core.api_client import BackpackAPIClient
            return BackpackAPIClient(
                access_key=api_key if auth_mode == 'manual' else config.backpack.ACCESS_KEY,
                refresh_key=secret_key if auth_mode == 'manual' else config.backpack.REFRESH_KEY
            )
        elif exchange == 'deepcoin':
            from backpack_quant_trading.core.deepcoin_client import DeepcoinAPIClient
            return DeepcoinAPIClient(
                api_key=api_key if auth_mode == 'manual' else config.deepcoin.API_KEY,
                secret_key=secret_key if auth_mode == 'manual' else config.deepcoin.SECRET_KEY,
                passphrase=passphrase if auth_mode == 'manual' else config.deepcoin.PASSPHRASE
            )
        elif exchange == 'ostium':
            from backpack_quant_trading.core.ostium_client import OstiumAPIClient
            return OstiumAPIClient(private_key=private_key if auth_mode == 'manual' else config.ostium.PRIVATE_KEY)
        elif exchange in ('hyper', 'hip3', 'hip3_testnet'):
            from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient
            base = "https://api.hyperliquid-testnet.xyz" if exchange == 'hip3_testnet' else "https://api.hyperliquid.xyz"
            pk = private_key if auth_mode == 'manual' else (getattr(config.hyperliquid, 'PRIVATE_KEY', '') if hasattr(config, 'hyperliquid') else '')
            return HyperliquidAPIClient(private_key=pk or None, base_url=base)
        raise ValueError(f"不支持的交易所: {exchange}")

    def _add_one(mode):
        api_client = _create_api_client()
        data_client = None
        if exchange not in ('hyper', 'hip3', 'hip3_testnet'):
            from backpack_quant_trading.core.api_client import BackpackAPIClient
            data_client = BackpackAPIClient(public_only=True)
        instance_id = f"inst_{int(time.time())}"  # 每次启动生成唯一ID，支持多次点击新增
        ok, msg = grid_manager.add_and_start(
            symbol=symbol,
            price_lower=float(price_lower),
            price_upper=float(price_upper),
            grid_count=int(grid_count),
            investment_per_grid=float(investment),
            leverage=int(leverage),
            api_client=api_client,
            data_client=data_client,
            grid_mode=mode,
            exchange=exchange or 'backpack',
            instance_id=instance_id
        )
        if ok and user_id:
            # 仅存交易对/模式/交易所，不存 API Key、私钥
            cfg = json.dumps({'symbol': symbol, 'grid_mode': mode, 'exchange': exchange or 'backpack'})
            db_manager.save_user_instance(user_id, 'grid', msg if isinstance(msg, str) else instance_id, cfg)
        return ok, msg

    # 停止全部（仅停止当前用户的网格）
    if 'btn-stop-grid' in trigger_id and n_stop:
        my_ids = set(db_manager.get_user_instance_ids(user_id, 'grid')) if user_id else set()
        for gid in my_ids:
            grid_manager.stop(str(gid))
            if user_id:
                db_manager.delete_user_instance(user_id, 'grid', str(gid))
        return html.P("🛑 已停止全部网格", style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})

    # 同时启动多单+空单
    if 'btn-start-both' in trigger_id and n_start_both:
        if not all([symbol, price_lower, price_upper, grid_count, investment, leverage]):
            return html.Div([html.P("⚠️ 请填写完整参数", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
        if auth_mode == 'manual':
            if exchange == 'backpack' and (not api_key or not secret_key):
                return html.Div([html.P("⚠️ 请输入 Backpack API Key 和 Secret", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
            if exchange == 'deepcoin' and (not api_key or not secret_key or not passphrase):
                return html.Div([html.P("⚠️ 请输入 Deepcoin API Key, Secret 和 Passphrase", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
            if exchange in ('ostium', 'hyper', 'hip3', 'hip3_testnet') and not private_key:
                return html.Div([html.P("⚠️ 请输入 Ostium/Hyper/HIP-3 私钥", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
        if price_lower >= price_upper:
            return html.Div([html.P("⚠️ 价格下限必须小于上限", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
        try:
            ok1, msg1 = _add_one('long_only')
            ok2, msg2 = _add_one('short_only')
            all_grids = _filter_by_user(grid_manager.get_all())
            status = _render_grid_cards(all_grids)
            if not ok1 and not ok2:
                return html.Div([html.P(f"⚠️ {msg1}; {msg2}", style={'color': COLORS['danger']}), status])
            return status
        except Exception as e:
            return html.Div([html.P(f"❌ 启动失败: {e}", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])

    # 启动当前类型网格（每次点击新增一个实例）
    if 'btn-start-grid' in trigger_id and n_start:
        if not all([symbol, price_lower, price_upper, grid_count, investment, leverage]):
            return html.Div([html.P("⚠️ 请填写完整参数", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
        if auth_mode == 'manual':
            if exchange == 'backpack' and (not api_key or not secret_key):
                return html.Div([html.P("⚠️ 请输入 Backpack API Key 和 Secret", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
            if exchange == 'deepcoin' and (not api_key or not secret_key or not passphrase):
                return html.Div([html.P("⚠️ 请输入 Deepcoin API Key, Secret 和 Passphrase", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
            if exchange in ('ostium', 'hyper', 'hip3', 'hip3_testnet') and not private_key:
                return html.Div([html.P("⚠️ 请输入 Ostium/Hyper/HIP-3 私钥", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
        if price_lower >= price_upper:
            return html.Div([html.P("⚠️ 价格下限必须小于上限", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])
        try:
            ok, msg = _add_one(grid_mode or 'long_short')
            all_grids = _filter_by_user(grid_manager.get_all())
            if not ok:
                return html.Div([html.P(f"⚠️ {msg}", style={'color': COLORS['danger']}), _render_grid_cards(all_grids)])
            return _render_grid_cards(all_grids)
        except Exception as e:
            return html.Div([html.P(f"❌ 启动失败: {e}", style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '20px'})])

    # 刷新状态（仅显示当前用户的网格）
    return _render_grid_cards(all_grids)


# 网格交易记录回调
@app.callback(
    Output('grid-trades-display', 'children'),
    [Input({'type': 'grid-refresh', 'index': ALL}, 'n_intervals')],
    prevent_initial_call=True
)
def update_grid_trades(n_intervals):
    """更新网格交易记录（使用主网格）"""
    primary = grid_manager.get_primary_for_display()
    if not primary:
        return html.P('暂无交易记录', style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})

    try:
        df = primary.get_grid_levels_df()
        
        # 过滤已成交的订单
        filled_df = df[df['status'] == 'filled'].copy()
        
        if filled_df.empty:
            return html.P('暂无交易记录', style={'color': COLORS['text_dim'], 'textAlign': 'center', 'padding': '40px'})
        
        # 按时间倒序排列
        filled_df = filled_df.sort_values('filled_time', ascending=False)
        
        # 创建表格
        table_header = [
            html.Thead(html.Tr([
                html.Th('时间', style={'padding': '12px', 'textAlign': 'left', 'fontWeight': '600'}),
                html.Th('方向', style={'padding': '12px', 'textAlign': 'center', 'fontWeight': '600'}),
                html.Th('价格', style={'padding': '12px', 'textAlign': 'right', 'fontWeight': '600'}),
                html.Th('数量', style={'padding': '12px', 'textAlign': 'right', 'fontWeight': '600'})
            ]))
        ]
        
        table_rows = []
        for _, row in filled_df.head(10).iterrows():  # 只显示最近10条
            side_color = COLORS['success'] if row['side'] == 'buy' else COLORS['danger']
            side_text = '买入' if row['side'] == 'buy' else '卖出'
            
            time_str = row['filled_time'].strftime('%m-%d %H:%M:%S') if pd.notna(row['filled_time']) else '-'
            
            table_rows.append(html.Tr([
                html.Td(time_str, style={'padding': '12px', 'fontSize': '13px'}),
                html.Td(
                    html.Span(side_text, style={
                        'padding': '4px 8px',
                        'borderRadius': '4px',
                        'fontSize': '12px',
                        'fontWeight': '600',
                        'backgroundColor': side_color + '20',
                        'color': side_color
                    }),
                    style={'textAlign': 'center'}
                ),
                html.Td(f"${row['price']:.2f}", style={'padding': '12px', 'textAlign': 'right', 'fontSize': '13px', 'fontWeight': '500'}),
                html.Td(f"{row['quantity']:.4f}", style={'padding': '12px', 'textAlign': 'right', 'fontSize': '13px'})
            ]))
        
        table_body = [html.Tbody(table_rows)]
        
        return html.Table(
            table_header + table_body,
            style={
                'width': '100%',
                'borderCollapse': 'collapse',
                'fontSize': '14px'
            }
        )
        
    except Exception as e:
        logger.error(f"更新交易记录失败: {e}", exc_info=True)
        return html.P('加载失败', style={'color': COLORS['danger'], 'textAlign': 'center', 'padding': '40px'})


# 网格交易日志更新回调
@app.callback(
    Output('grid-logs-display', 'children'),
    [Input({'type': 'grid-refresh', 'index': 'logs'}, 'n_intervals')],
    prevent_initial_call=True
)
def update_grid_logs(n_intervals):
    """更新网格日志显示"""
    try:
        log_file = Path("./log/app_" + datetime.now().strftime('%Y%m%d') + ".log")
        if not log_file.exists():
            return html.P('暂无日志', style={'color': '#666', 'textAlign': 'center', 'padding': '40px'})
        
        # 读取最后100行日志
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        
        # 筛选出网格相关的日志行
        grid_lines = []
        for line in all_lines[-200:]:  # 从最后200行中筛选
            if 'grid_strategy' in line.lower() or '网格' in line or 'grid' in line.lower():
                grid_lines.append(line.strip())
        
        if not grid_lines:
            return html.P('暂无网格日志', style={'color': '#666', 'textAlign': 'center', 'padding': '40px'})
        
        # 倒序显示（最新在上）
        grid_lines = list(reversed(grid_lines[-50:]))  # 只显示最近50条
        
        # 渲染日志行（带颜色高亮）
        log_elements = []
        for line in grid_lines:
            # 根据日志级别设置颜色
            color = '#D4D4D4'  # 默认浅灰
            if '| ERROR' in line or '❌' in line:
                color = '#FF6B6B'  # 红色
            elif '| WARNING' in line or '⚠️' in line:
                color = '#FFD93D'  # 黄色
            elif '| INFO' in line or '✅' in line or '🚀' in line:
                color = '#6BCF7F'  # 绿色
            elif '| DEBUG' in line:
                color = '#74B9FF'  # 蓝色
            
            log_elements.append(
                html.Div(line, style={
                    'color': color,
                    'marginBottom': '4px',
                    'whiteSpace': 'pre-wrap',
                    'wordBreak': 'break-word'
                })
            )
        
        return log_elements
    except Exception as e:
        return html.P(f'日志加载失败: {str(e)}', style={'color': '#FF6B6B', 'textAlign': 'center', 'padding': '40px'})


# --- Dash 验证布局：列出所有页面可能出现的组件，避免前端出现
# "A nonexistent object was used in an `Input`" 的红色报错（例如 btn-add-strategy） ---
app.validation_layout = html.Div([
    app.layout,
    # 使用占位用户构建各个页面的完整布局，供 Dash 校验回调依赖
    render_trading_layout({'username': 'validation', 'role': 'user'}, control_log=""),
    render_dashboard_layout(),
    render_ai_lab_layout(),
    render_currency_monitor_layout(),
    render_grid_trading_layout(),
])


if __name__ == '__main__':
    # 启用 debug 模式但关闭前端报错弹窗；dev_tools_props_check=False 减少 React 校验导致的 Object 错误
    app.run(host='0.0.0.0', port=8050, debug=True, dev_tools_ui=False, dev_tools_props_check=False)

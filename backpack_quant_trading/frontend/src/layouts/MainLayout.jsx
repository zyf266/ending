import React, { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Zap,
  BarChart2,
  FlaskConical,
  LayoutGrid,
  Bell,
  RefreshCw,
  TrendingUp,
  Layers,
  Repeat,
  ChevronRight,
  Menu,
  X,
} from 'lucide-react'
import ChatBot from '../components/ChatBot'
import './MainLayout.css'

// 导航配置：支持父菜单 + 子菜单
const navItems = [
  {
    type: 'item',
    icon: Zap,
    label: '实盘交易',
    to: '/trading',
  },
  {
    type: 'group',
    icon: FlaskConical,
    label: 'AI 实验室',
    to: '/ai-lab',
    children: [
      { to: '/ai-lab', label: '加密AI分析' },
      { to: '/stock-ai', label: 'A股 AI 选股' },
      { to: '/okx-console', label: 'OKX 操作台' },
    ],
  },
  { type: 'item', to: '/currency-monitor', icon: Bell, label: '币种监视' },
  { type: 'item', to: '/strategies', icon: Layers, label: 'AI策略矩阵' },
]

const pageTitles = {
  '/trading': '策略交易',
  '/dashboard': '数据大屏',
  '/ai-lab': '加密AI分析',
  '/grid-trading': '网格交易',
  '/currency-monitor': '币种监视',
  '/stock-ai': 'A股 AI 选股',
  '/strategies': 'AI策略矩阵',
  '/okx-console': 'OKX 操作台',
}

function getPageTitle(pathname) {
  if (pathname.startsWith('/strategies')) return 'AI策略矩阵'
  if (pathname === '/trading') return '策略交易'
  // AI 实验室父菜单下的三个子页面，统一父标题
  if (pathname === '/ai-lab' || pathname === '/stock-ai' || pathname === '/okx-console') return 'AI 实验室'
  return pageTitles[pathname] || '沐龙量化'
}

const MainLayout = () => {
  const [user, setUser] = useState(() => {
    const stored = localStorage.getItem('user')
    return stored ? JSON.parse(stored) : null
  })

  const [showTradingGroup, setShowTradingGroup] = useState(false)
  const [showAiGroup, setShowAiGroup] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const navigate = useNavigate()
  const location = useLocation()

  // 路由切换时关闭侧边栏
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!user) {
      const stored = localStorage.getItem('user')
      if (stored) setUser(JSON.parse(stored))
    }
  }, [user])

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login')
  }

  const pageTitle = getPageTitle(location.pathname)

  return (
    <div className="main-layout">
      {/* 移动端遗罩层 */}
      <div
        className={`sidebar-overlay${sidebarOpen ? ' open' : ''}`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`sidebar${sidebarOpen ? ' open' : ''}`}>
        <div className="logo-section">
          <div className="logo-wrapper">
            <div className="logo-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <div>
              <div className="logo-text">ApexAI Quant</div>
              <div className="logo-subtext">Admin · v1.0</div>
            </div>
          </div>
        </div>

        <nav className="nav">
          {navItems.map((item) => {
            if (item.type === 'group') {
              const { icon: Icon, label, to, children } = item
              const inGroup = children.some((c) => location.pathname === c.to)
              const isTradingGroup = label === '实盘交易'
              const isAiGroup = label === 'AI 实验室'
              const opened = isTradingGroup ? showTradingGroup : isAiGroup ? showAiGroup : true
              return (
                <div key={label}>
                  <button
                    type="button"
                    className={`nav-link nav-link-parent${inGroup ? ' active' : ''}`}
                    onClick={() => {
                      if (isTradingGroup) setShowTradingGroup((v) => !v)
                      else if (isAiGroup) setShowAiGroup((v) => !v)
                    }}
                  >
                    <Icon className="nav-icon" size={20} />
                    <span>{label}</span>
                  </button>
                  {opened && (
                    <div className="nav-sub">
                      {children.map((child) => (
                        <NavLink
                          key={child.to}
                          to={child.to}
                          className={({ isActive }) =>
                            `nav-link nav-link-child${isActive ? ' active' : ''}`
                          }
                        >
                          <span>{child.label}</span>
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              )
            }

            const { to, icon: Icon, label } = item
            const isStrategies = to === '/strategies' && location.pathname.startsWith('/strategies')
            return (
              <NavLink
                key={label}
                to={to}
                className={({ isActive }) => `nav-link${isActive || isStrategies ? ' active' : ''}`}
              >
                <Icon className="nav-icon" size={20} />
                <span>{label}</span>
              </NavLink>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="footer-content">
            <div className="footer-avatar">ML</div>
            <div className="footer-info">
              <div className="footer-status">
                <span className="status-dot" />
                <span className="status-text">运行正常</span>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <div className="content">
        <header className="header">
          <div className="header-left">
            {/* 移动端汉堡菜单按钮 */}
            <button
              type="button"
              className="hamburger-btn"
              aria-label="展开菜单"
              onClick={() => setSidebarOpen((v) => !v)}
            >
              {sidebarOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
            <h1 className="page-title">{pageTitle}</h1>
            <span className="status-badge">
              <span className="status-dot" />
              实时更新中
            </span>
          </div>
          <div className="header-right">
            <button type="button" className="icon-btn desktop-only" aria-label="通知">
              <Bell size={22} />
            </button>
            <button type="button" className="icon-btn desktop-only" aria-label="刷新">
              <RefreshCw size={22} />
            </button>
            <div className="user-info">
              <div className="user-avatar">
                {(user?.username || '用').slice(0, 2).toUpperCase()}
              </div>
              <div className="user-details desktop-only">
                <div className="user-name">{user?.username || 'zyf'} {user?.role === 'superuser' ? '管理员' : '用户'}</div>
              </div>
            </div>
            <button
              type="button"
              className="btn-logout"
              onClick={handleLogout}
            >
              退出
            </button>
          </div>
        </header>
        <main className="page-content">
          <Outlet />
        </main>
      </div>
      <ChatBot />
    </div>
  )
}

export default MainLayout

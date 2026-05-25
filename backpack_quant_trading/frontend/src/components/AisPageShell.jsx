import React from 'react'

/** 玻璃态标题区 + 内容区（背景由 MainLayout 全局提供） */
const AisPageShell = ({ title, subtitle, children, className = '' }) => {
  return (
    <div className={`page ais-page ${className}`.trim()}>
      <div className="ais-shell">
        {(title || subtitle) && (
          <header className="ais-header">
            {title && <h3 className="ais-title">{title}</h3>}
            {subtitle && <p className="ais-sub">{subtitle}</p>}
          </header>
        )}
        {children}
      </div>
    </div>
  )
}

export default AisPageShell

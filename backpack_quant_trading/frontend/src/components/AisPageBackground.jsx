import React from 'react'

/** 全站统一的 AI 选股风格渐进渐变背景（由 MainLayout 挂载一次） */
const AisPageBackground = ({ className = 'ais-layout-bg' }) => (
  <div className={`ais-bg ${className}`.trim()} aria-hidden>
    <div className="ais-bg-mesh" />
    <div className="ais-bg-orb ais-bg-orb-1" />
    <div className="ais-bg-orb ais-bg-orb-2" />
    <div className="ais-bg-orb ais-bg-orb-3" />
    <div className="ais-bg-grid" />
    <div className="ais-bg-shimmer" />
  </div>
)

export default AisPageBackground

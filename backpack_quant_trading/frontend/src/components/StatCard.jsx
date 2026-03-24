import React from 'react'
import './StatCard.css'

export function StatCard({ title, value, change, isPositive, icon: Icon, iconColor, percentage }) {
  return (
    <div className="stat-card">
      <div className="stat-progress">
        <div className="stat-progress-bar" style={{ width: '60%' }} />
      </div>
      <div className="stat-header">
        <div className="stat-info">
          <p className="stat-label">{title}</p>
          <div className="stat-value-wrapper">
            <h3 className="stat-value">{value}</h3>
            {percentage != null && percentage !== '' && (
              <span className="stat-percentage">{percentage}</span>
            )}
          </div>
          {change != null && change !== '' && (
            <span className={`stat-change ${isPositive ? 'positive' : 'negative'}`}>
              {change}
            </span>
          )}
        </div>
        <div className={`stat-icon ${iconColor || 'bg-blue-500'}`}>
          {Icon && <Icon className="stat-icon-svg" />}
        </div>
      </div>
    </div>
  )
}

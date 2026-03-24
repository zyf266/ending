import React from 'react'

export function CircularProgress({ percentage, color = '#3b82f6' }) {
  const radius = 20
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (percentage / 100) * circumference
  const size = 56

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="h-full w-full -rotate-90" viewBox="0 0 52 52">
        <circle cx="26" cy="26" r={radius} stroke="#e5e7eb" strokeWidth="4" fill="none" />
        <circle
          cx="26"
          cy="26"
          r={radius}
          stroke={color}
          strokeWidth="4"
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-300"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-sm font-semibold" style={{ color }}>
          {percentage}%
        </span>
      </div>
    </div>
  )
}

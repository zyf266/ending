import React from 'react';
import { TrendingUp, TrendingDown, Shield } from 'lucide-react';

interface StrategyCardProps {
  name: string;
  code: string;
  status: '运行中' | '测试中' | '已暂停';
  progress: number;
  description: string;
  annualizedReturn: number;
  totalReturn: number;
  sharpeRatio: number;
  riskLevel: string;
}

export function StrategyCard({
  name,
  code,
  status,
  progress,
  description,
  annualizedReturn,
  totalReturn,
  sharpeRatio,
  riskLevel
}: StrategyCardProps) {
  const statusColors = {
    '运行中': 'bg-green-100 text-green-600',
    '测试中': 'bg-blue-100 text-blue-600',
    '已暂停': 'bg-orange-100 text-orange-600'
  };

  const progressColor = progress >= 80 ? 'stroke-green-500' : progress >= 60 ? 'stroke-blue-500' : 'stroke-orange-500';
  const progressTextColor = progress >= 80 ? 'text-green-600' : progress >= 60 ? 'text-blue-600' : 'text-orange-600';
  
  const circumference = 2 * Math.PI * 28;
  const offset = circumference * (1 - progress / 100);

  return (
    <div className="bg-white rounded-xl p-6 border border-gray-200 hover:border-blue-500 hover:shadow-lg transition-all cursor-pointer">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-lg font-semibold text-gray-900">{name}</h3>
            <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[status]}`}>
              {status}
            </span>
          </div>
          <div className="text-sm text-gray-600">{code}</div>
        </div>
        
        {/* Circular Progress */}
        <div className="relative w-16 h-16">
          <svg className="w-16 h-16 transform -rotate-90" viewBox="0 0 64 64">
            <circle
              cx="32"
              cy="32"
              r="28"
              fill="none"
              stroke="#f3f4f6"
              strokeWidth="4"
            />
            <circle
              cx="32"
              cy="32"
              r="28"
              fill="none"
              className={progressColor}
              strokeWidth="4"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              strokeLinecap="round"
            />
          </svg>
          <div className={`absolute inset-0 flex items-center justify-center text-sm font-bold ${progressTextColor}`}>
            {progress}%
          </div>
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-gray-600 mb-4 line-clamp-2">
        {description}
      </p>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        {/* Annualized Return */}
        <div className="bg-blue-50 rounded-lg p-3">
          <div className="flex items-center gap-1 mb-1">
            <TrendingUp className="w-4 h-4 text-blue-600" />
            <span className="text-xs text-gray-600">平均年化</span>
          </div>
          <div className="text-lg font-bold text-green-600">
            {annualizedReturn.toFixed(2)}%
          </div>
        </div>

        {/* Total Return */}
        <div className="bg-red-50 rounded-lg p-3">
          <div className="flex items-center gap-1 mb-1">
            <TrendingDown className="w-4 h-4 text-red-600" />
            <span className="text-xs text-gray-600">本金回撤</span>
          </div>
          <div className="text-lg font-bold text-red-600">
            {totalReturn.toFixed(2)}%
          </div>
        </div>
      </div>

      {/* Bottom Info */}
      <div className="flex justify-between pt-3 border-t border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-teal-100 rounded-full flex items-center justify-center">
            <div className="w-3 h-3 bg-teal-500 rounded-full"></div>
          </div>
          <div>
            <div className="text-xs text-gray-600">盈利因子</div>
            <div className="text-sm font-semibold text-gray-900">{sharpeRatio.toFixed(2)}</div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-green-100 rounded-full flex items-center justify-center">
            <Shield className="w-4 h-4 text-green-600" />
          </div>
          <div>
            <div className="text-xs text-gray-600">风险评级</div>
            <div className="text-sm font-semibold text-green-600">{riskLevel}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

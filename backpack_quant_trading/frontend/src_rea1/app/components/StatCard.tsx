import React from 'react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  label: string;
  value: string;
  change?: string;
  changeType?: 'positive' | 'negative';
  percentage?: string;
  icon: LucideIcon;
  iconColor: string;
}

export function StatCard({
  label,
  value,
  change,
  changeType,
  percentage,
  icon: Icon,
  iconColor
}: StatCardProps) {
  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200 relative overflow-hidden">
      {/* Progress bar at bottom */}
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-gray-100">
        <div className="h-full w-3/5 bg-blue-600"></div>
      </div>
      
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-sm text-gray-600 mb-1">{label}</div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-gray-900">{value}</span>
            {percentage && (
              <span className="text-sm text-gray-600">{percentage}</span>
            )}
          </div>
          {change && (
            <div className={`text-sm mt-1 ${
              changeType === 'positive' ? 'text-green-600' : 'text-red-600'
            }`}>
              {change}
            </div>
          )}
        </div>
        
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-white ${iconColor}`}>
          <Icon className="w-6 h-6" />
        </div>
      </div>
    </div>
  );
}

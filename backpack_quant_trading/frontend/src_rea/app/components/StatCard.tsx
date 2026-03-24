import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string;
  change?: string;
  isPositive?: boolean;
  icon: LucideIcon;
  iconColor: string;
}

export function StatCard({ title, value, change, isPositive, icon: Icon, iconColor }: StatCardProps) {
  return (
    <div className="bg-white rounded-xl p-4 border border-gray-200">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-xs text-gray-500 mb-1">{title}</p>
          <div className="flex items-baseline gap-2">
            <h3 className="text-2xl font-bold text-gray-900">{value}</h3>
            {change && (
              <span className={`text-xs font-medium ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
                {change}
              </span>
            )}
          </div>
        </div>
        <div className={`p-2 rounded-lg ${iconColor}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
    </div>
  );
}

import { CircularProgress } from './CircularProgress';
import { TrendingUp, TrendingDown, Target, AlertTriangle } from 'lucide-react';

interface MetricCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  isPositive?: boolean;
  bgColor: string;
}

function MetricCard({ icon, label, value, isPositive, bgColor }: MetricCardProps) {
  const valueColor = isPositive === undefined 
    ? 'text-gray-900' 
    : isPositive 
    ? 'text-green-600' 
    : 'text-red-600';

  return (
    <div className={`${bgColor} rounded-lg p-3`}>
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      <div className={`text-base font-semibold ${valueColor}`}>
        {value}
      </div>
    </div>
  );
}

interface StrategyCardProps {
  title: string;
  code: string;
  description: string;
  status: string;
  statusColor: string;
  progress: number;
  progressColor: string;
  annualReturn: string;
  drawdown: string;
  profitFactor: string;
  riskIndex: string;
  isRiskWarning?: boolean;
}

export function StrategyCard({
  title,
  code,
  description,
  status,
  statusColor,
  progress,
  progressColor,
  annualReturn,
  drawdown,
  profitFactor,
  riskIndex,
  isRiskWarning = false,
}: StrategyCardProps) {
  return (
    <div className="bg-white rounded-2xl p-5 border border-gray-200 hover:shadow-lg transition-shadow duration-200">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <h3 className="text-base font-bold text-gray-900 mb-1">{title}</h3>
          <p className="text-xs text-gray-400">{code}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${statusColor}`}>
            {status}
          </span>
          <CircularProgress percentage={progress} color={progressColor} />
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-gray-600 leading-relaxed mb-4">
        {description}
      </p>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 gap-2.5">
        <MetricCard
          icon={<TrendingUp className="w-4 h-4 text-blue-500" />}
          label="平均年化"
          value={annualReturn}
          isPositive={true}
          bgColor="bg-blue-50"
        />
        <MetricCard
          icon={<TrendingDown className="w-4 h-4 text-red-500" />}
          label="本金回撤"
          value={drawdown}
          isPositive={false}
          bgColor="bg-red-50"
        />
        <MetricCard
          icon={<Target className="w-4 h-4 text-green-600" />}
          label="盈利因子"
          value={profitFactor}
          bgColor="bg-green-50"
        />
        <MetricCard
          icon={<AlertTriangle className={`w-4 h-4 ${isRiskWarning ? 'text-red-500' : 'text-green-600'}`} />}
          label="风险指数"
          value={riskIndex}
          bgColor={isRiskWarning ? "bg-red-50" : "bg-green-50"}
        />
      </div>
    </div>
  );
}

interface CircularProgressProps {
  percentage: number;
  color?: string;
}

export function CircularProgress({ percentage, color = '#3b82f6' }: CircularProgressProps) {
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percentage / 100) * circumference;

  return (
    <div className="relative w-12 h-12">
      <svg className="w-12 h-12 transform -rotate-90">
        {/* Background circle */}
        <circle
          cx="24"
          cy="24"
          r={radius}
          stroke="#e5e7eb"
          strokeWidth="4"
          fill="none"
        />
        {/* Progress circle */}
        <circle
          cx="24"
          cy="24"
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
        <span className="text-xs font-semibold" style={{ color }}>
          {percentage}%
        </span>
      </div>
    </div>
  );
}

import { healthColor } from "../lib/format";

export function ScoreGauge({ score, size = 140 }: { score: number; size?: number }) {
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));
  const offset = circumference * (1 - clamped / 100);
  const colors = healthColor(clamped);

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={10}
          fill="none"
          className="stroke-border"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={10}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={`transition-[stroke-dashoffset] duration-[var(--dur-slow)] ease-[var(--ease-out)] motion-reduce:transition-none ${colors.ring}`}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className={`cp-stat text-3xl font-semibold ${colors.text}`}>
          {Math.round(clamped)}
        </span>
        <span className="cp-label">/ 100</span>
      </div>
    </div>
  );
}

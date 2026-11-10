/**
 * The Activity lens: a node's changes in the last 365 days (sum of
 * `churn_365d` over the files it stands for), bucketed 0-5 RELATIVE to the
 * busiest node currently on screen. Square-root scaling keeps one very hot
 * box from flattening every other box into bucket 1. Bucket 0 means no
 * change at all in the window -- genuinely quiet, not merely "low".
 */
export type ActivityBucket = 0 | 1 | 2 | 3 | 4 | 5;

export function activityBucket(value: number, max: number): ActivityBucket {
  if (value <= 0 || max <= 0) return 0;
  return Math.min(5, Math.max(1, Math.ceil(5 * Math.sqrt(value / max)))) as ActivityBucket;
}

export function activityColor(bucket: ActivityBucket): string {
  return `var(--cp-activity-${bucket})`;
}

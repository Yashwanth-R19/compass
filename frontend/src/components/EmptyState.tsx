import type { ReactNode } from "react";

/** "Computed, and genuinely empty" -- deliberately visually distinct from
 * LoadingState (a skeleton, no border) and from a pending/"not computed
 * yet" render (also a skeleton, via StageGate). A dashed hairline border is
 * the one visual marker of "this ran and found nothing," so the three
 * states (pending / empty / has-data) never look interchangeable at a
 * glance (CLAUDE.md's 202 contract). */
export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border-strong py-16 text-center">
      <p className="text-sm font-medium text-text">{title}</p>
      {message ? <p className="max-w-sm text-sm text-text-muted">{message}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

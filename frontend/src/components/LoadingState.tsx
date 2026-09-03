import { Skeleton } from "./ui/Skeleton";

/** The generic fallback skeleton -- used by StageGate whenever a page
 * doesn't supply its own shape-matched `skeleton` prop. */
export function LoadingState({ label }: { label?: string }) {
  return (
    <div className="flex flex-col gap-3 py-2" role="status" aria-label={label ?? "Loading"}>
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-20 w-full" />
      <div className="flex gap-3">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-20" />
      </div>
    </div>
  );
}

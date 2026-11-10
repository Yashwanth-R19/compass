import { X } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { DiagramAiResponse } from "../../api/types";
import { RateLimitedError } from "../../api/client";
import { MAP_COPY, aiRateLimitedLine, aiUnavailableLine } from "../../content/map";
import { Skeleton } from "../ui/Skeleton";

/** The AI's architecture summary (when AI labels are on), or a single quiet
 * line explaining why there's none. Never blocks the computed map. */
export function AiSummaryBanner({
  query,
  onDismiss,
}: {
  query: UseQueryResult<DiagramAiResponse, unknown>;
  onDismiss: () => void;
}) {
  if (query.isPending || query.isFetching) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-border p-3" aria-live="polite">
        <span className="text-xs text-text-muted">{MAP_COPY.aiLoading}</span>
        <Skeleton className="h-3 w-2/3" />
        <Skeleton className="h-3 w-full" />
      </div>
    );
  }
  if (query.isError) {
    const text =
      query.error instanceof RateLimitedError
        ? aiRateLimitedLine(query.error.retryAfterSeconds)
        : aiUnavailableLine(null);
    return <p className="text-xs text-text-muted">{text}</p>;
  }
  const result = query.data;
  if (!result.available) {
    return <p className="text-xs text-text-muted">{aiUnavailableLine(result.reason)}</p>;
  }
  if (!result.payload?.summary) return null;
  return (
    <div className="relative rounded-lg border border-info bg-info-bg p-3 pr-9">
      <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-info">
        {MAP_COPY.aiEyebrow}
        {result.provider && result.model ? ` · ${result.provider}/${result.model}` : ""}
      </p>
      <p className="text-sm leading-relaxed text-text">{result.payload.summary}</p>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={MAP_COPY.dismiss}
        className="absolute top-2.5 right-2.5 text-text-muted hover:text-text"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

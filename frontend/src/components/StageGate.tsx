import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { FetchResult } from "../api/client";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { LoadingState } from "./LoadingState";

/** The one place every page branches on pending/empty/error/data for a
 * run-scoped analysis endpoint (Part F, Phase 02) -- so a stage that hasn't
 * finished computing renders a skeleton, a stage that finished with
 * genuinely no results renders the empty state, and the two are never
 * conflated (CLAUDE.md: "conflating them is the most common way
 * progressive reveal ends up feeling broken").
 *
 * Session 15, Part D: `skeleton` lets a page supply a placeholder shaped
 * like its OWN eventual content (a table skeleton for a table, a gauge
 * skeleton for a gauge) instead of the generic `LoadingState` fallback --
 * "every skeleton matches the shape of what it becomes, so nothing jumps on
 * load." Purely additive; every pre-session-15 call site (no `skeleton`
 * passed) is unaffected.
 */
export function StageGate<T>({
  query,
  loadingLabel = "Loading…",
  skeleton,
  emptyTitle = "Nothing here yet",
  emptyMessage,
  isEmpty,
  children,
}: {
  query: UseQueryResult<FetchResult<T>, unknown>;
  loadingLabel?: string;
  skeleton?: ReactNode;
  emptyTitle?: string;
  emptyMessage?: string;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) {
    return skeleton ?? <LoadingState label={loadingLabel} />;
  }
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const result = query.data;
  if (result.kind === "pending") {
    return skeleton ?? <LoadingState label={loadingLabel} />;
  }

  if (isEmpty?.(result.data)) {
    return <EmptyState title={emptyTitle} message={emptyMessage} />;
  }

  return <>{children(result.data)}</>;
}

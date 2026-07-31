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
 */
export function StageGate<T>({
  query,
  loadingLabel = "Loading…",
  emptyTitle = "Nothing here yet",
  emptyMessage,
  isEmpty,
  children,
}: {
  query: UseQueryResult<FetchResult<T>, unknown>;
  loadingLabel?: string;
  emptyTitle?: string;
  emptyMessage?: string;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) {
    return <LoadingState label={loadingLabel} />;
  }
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const result = query.data;
  if (result.kind === "pending") {
    return <LoadingState label={loadingLabel} />;
  }

  if (isEmpty?.(result.data)) {
    return <EmptyState title={emptyTitle} message={emptyMessage} />;
  }

  return <>{children(result.data)}</>;
}

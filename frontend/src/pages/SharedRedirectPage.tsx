import { Navigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api/client";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import type { SharedRunOut } from "../api/types";

/** Resolves a share slug (`/shared/:slug`) to a repo, then hands off to the
 * normal repo view. A share link grants access to one run, not the
 * repository (CLAUDE.md) -- for a repo the viewer can already otherwise
 * read (public, or private and they're the owner), this "just works" via
 * the repo's normal current run. Anonymous access to a PRIVATE repo's
 * shared run requires the ``share`` slug to also travel with every
 * subsequent analysis request, which the six per-tab result hooks don't yet
 * thread through (see CLAUDE.md's auth-architecture section) -- a known,
 * documented gap, not silently broken. */
export function SharedRedirectPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["shared", slug],
    queryFn: () => apiGet<SharedRunOut>(`/shared/${slug}`),
    enabled: Boolean(slug),
    retry: false,
  });

  if (isPending) return <LoadingState label="Resolving shared link…" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;

  return <Navigate to={`/repos/${data.repo_id}/overview`} replace />;
}

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiDelete, apiGet, apiGetOrPending, apiPost, onUnauthorized } from "./client";
import type {
  ArchitectureResponse,
  CouplingResponse,
  FindingsResponse,
  HealthResponse,
  HiddenDependencyResponse,
  MyGithubReposResponse,
  MyReposResponse,
  RepoCreateResponse,
  RepoOut,
  RepoStatusResponse,
  RiskResponse,
  ShareLinkOut,
  UserOut,
} from "./types";

const POLL_INTERVAL_MS = 1500;
const REPO_TERMINAL_STATUSES = new Set(["ready", "failed"]);
const RUN_TERMINAL_STATUSES = new Set(["ready", "failed", "superseded"]);

export function useSubmitRepo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => apiPost<RepoCreateResponse>("/repos", { url }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["repo"] });
    },
  });
}

export function useRepo(repoId: string | undefined, share?: string) {
  const qs = share ? `?share=${encodeURIComponent(share)}` : "";

  return useQuery({
    queryKey: ["repo", repoId, share ?? null],
    queryFn: () => apiGet<RepoOut>(`/repos/${repoId}${qs}`),
    enabled: Boolean(repoId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && !REPO_TERMINAL_STATUSES.has(status) ? POLL_INTERVAL_MS : false;
    },
  });
}

/** The single endpoint the frontend polls for progressive reveal (Part E/F,
 * Phase 02): repo status, the latest analysis run, and every stage's
 * status/summary for it. Polls every 1.5s until the LATEST run reaches a
 * terminal status -- not gated on repos.status, since a repo can be
 * "failed" from a bad re-analysis while still showing a previously-ready
 * run's data (see RepoLayout).
 */
export function useRepoStatus(repoId: string | undefined, share?: string) {
  const qs = share ? `?share=${encodeURIComponent(share)}` : "";

  return useQuery({
    queryKey: ["repo-status", repoId, share ?? null],
    queryFn: () => apiGet<RepoStatusResponse>(`/repos/${repoId}/status${qs}`),
    enabled: Boolean(repoId),
    refetchInterval: (query) => {
      const runStatus = query.state.data?.run_status;
      const stillWorking = !runStatus || !RUN_TERMINAL_STATUSES.has(runStatus);
      return stillWorking ? POLL_INTERVAL_MS : false;
    },
  });
}

export function useCoupling(repoId: string | undefined, share?: string) {
  const qs = share ? `?share=${encodeURIComponent(share)}` : "";

  return useQuery({
    queryKey: ["coupling", repoId, share ?? null],
    queryFn: () => apiGetOrPending<CouplingResponse>(`/repos/${repoId}/coupling${qs}`),
    enabled: Boolean(repoId),
  });
}

export function useArchitecture(repoId: string | undefined, share?: string) {
  const qs = share ? `?share=${encodeURIComponent(share)}` : "";

  return useQuery({
    queryKey: ["architecture", repoId, share ?? null],
    queryFn: () => apiGetOrPending<ArchitectureResponse>(`/repos/${repoId}/architecture${qs}`),
    enabled: Boolean(repoId),
  });
}

export function useHiddenDeps(repoId: string | undefined, share?: string) {
  const qs = share ? `?share=${encodeURIComponent(share)}` : "";

  return useQuery({
    queryKey: ["hidden-dependencies", repoId, share ?? null],
    queryFn: () =>
      apiGetOrPending<HiddenDependencyResponse>(`/repos/${repoId}/hidden-dependencies${qs}`),
    enabled: Boolean(repoId),
  });
}

export function useRisk(repoId: string | undefined, share?: string) {
  const qs = share ? `?share=${encodeURIComponent(share)}` : "";

  return useQuery({
    queryKey: ["risk", repoId, share ?? null],
    queryFn: () => apiGetOrPending<RiskResponse>(`/repos/${repoId}/risk${qs}`),
    enabled: Boolean(repoId),
  });
}

export function useHealth(repoId: string | undefined, share?: string) {
  const qs = share ? `?share=${encodeURIComponent(share)}` : "";

  return useQuery({
    queryKey: ["health", repoId, share ?? null],
    queryFn: () => apiGetOrPending<HealthResponse>(`/repos/${repoId}/health${qs}`),
    enabled: Boolean(repoId),
  });
}

export function useFindings(repoId: string | undefined, category?: string, share?: string) {
  return useQuery({
    queryKey: ["findings", repoId, category ?? null, share ?? null],
    queryFn: () => {
      const params = new URLSearchParams();

      if (category) params.set("category", category);
      if (share) params.set("share", share);

      const qs = params.toString() ? `?${params.toString()}` : "";

      return apiGetOrPending<FindingsResponse>(`/repos/${repoId}/findings${qs}`);
    },
    enabled: Boolean(repoId),
  });
}
// --- Session 02: auth, history, sharing ------------------------------------

/** The current session's user, or `null` when logged out -- never throws for
 * a plain 401 (that just means "not logged in"), and clears itself the
 * instant any OTHER request reports 401 (client.ts's onUnauthorized
 * pub-sub), so a session that expires mid-visit doesn't leave a stale
 * avatar showing (Part G). */
export function useMe() {
  const queryClient = useQueryClient();

  useEffect(() => {
    return onUnauthorized(() => {
      queryClient.setQueryData(["me"], null);
    });
  }, [queryClient]);

  return useQuery({
    queryKey: ["me"],
    queryFn: async (): Promise<UserOut | null> => {
      try {
        return await apiGet<UserOut>("/auth/me");
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          return null;
        }
        throw err;
      }
    },
    retry: false,
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<{ status: string }>("/auth/logout", {}),
    onSuccess: () => {
      queryClient.setQueryData(["me"], null);
      void queryClient.invalidateQueries();
    },
  });
}

export function useMyRepos(page = 1, perPage = 20) {
  return useQuery({
    queryKey: ["my-repos", page, perPage],
    queryFn: () => apiGet<MyReposResponse>(`/me/repos?page=${page}&per_page=${perPage}`),
  });
}

export function useMyGithubRepos(enabled: boolean) {
  return useQuery({
    queryKey: ["my-github-repos"],
    queryFn: () => apiGet<MyGithubReposResponse>("/me/github/repos"),
    enabled,
    retry: false,
  });
}

export function useCreateShareLink() {
  return useMutation({
    mutationFn: (runId: string) => apiPost<ShareLinkOut>(`/runs/${runId}/share`, {}),
  });
}

export function useRevokeShareLink() {
  return useMutation({
    mutationFn: (runId: string) => apiDelete<{ status: string }>(`/runs/${runId}/share`),
  });
}

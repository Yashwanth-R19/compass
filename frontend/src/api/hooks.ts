import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiGetOrPending, apiPost } from "./client";
import type {
  ArchitectureResponse,
  CouplingResponse,
  FindingsResponse,
  HealthResponse,
  HiddenDependencyResponse,
  RepoCreateResponse,
  RepoOut,
  RepoStatusResponse,
  RiskResponse,
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

export function useRepo(repoId: string | undefined) {
  return useQuery({
    queryKey: ["repo", repoId],
    queryFn: () => apiGet<RepoOut>(`/repos/${repoId}`),
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
export function useRepoStatus(repoId: string | undefined) {
  return useQuery({
    queryKey: ["repo-status", repoId],
    queryFn: () => apiGet<RepoStatusResponse>(`/repos/${repoId}/status`),
    enabled: Boolean(repoId),
    refetchInterval: (query) => {
      const runStatus = query.state.data?.run_status;
      const stillWorking = !runStatus || !RUN_TERMINAL_STATUSES.has(runStatus);
      return stillWorking ? POLL_INTERVAL_MS : false;
    },
  });
}

export function useCoupling(repoId: string | undefined) {
  return useQuery({
    queryKey: ["coupling", repoId],
    queryFn: () => apiGetOrPending<CouplingResponse>(`/repos/${repoId}/coupling`),
    enabled: Boolean(repoId),
  });
}

export function useArchitecture(repoId: string | undefined) {
  return useQuery({
    queryKey: ["architecture", repoId],
    queryFn: () => apiGetOrPending<ArchitectureResponse>(`/repos/${repoId}/architecture`),
    enabled: Boolean(repoId),
  });
}

export function useHiddenDeps(repoId: string | undefined) {
  return useQuery({
    queryKey: ["hidden-dependencies", repoId],
    queryFn: () =>
      apiGetOrPending<HiddenDependencyResponse>(`/repos/${repoId}/hidden-dependencies`),
    enabled: Boolean(repoId),
  });
}

export function useRisk(repoId: string | undefined) {
  return useQuery({
    queryKey: ["risk", repoId],
    queryFn: () => apiGetOrPending<RiskResponse>(`/repos/${repoId}/risk`),
    enabled: Boolean(repoId),
  });
}

export function useHealth(repoId: string | undefined) {
  return useQuery({
    queryKey: ["health", repoId],
    queryFn: () => apiGetOrPending<HealthResponse>(`/repos/${repoId}/health`),
    enabled: Boolean(repoId),
  });
}

export function useFindings(repoId: string | undefined, category?: string) {
  return useQuery({
    queryKey: ["findings", repoId, category ?? null],
    queryFn: () => {
      const qs = category ? `?category=${encodeURIComponent(category)}` : "";
      return apiGetOrPending<FindingsResponse>(`/repos/${repoId}/findings${qs}`);
    },
    enabled: Boolean(repoId),
  });
}

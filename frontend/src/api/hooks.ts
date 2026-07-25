import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./client";
import type {
  ArchitectureResponse,
  CouplingResponse,
  FindingsResponse,
  HealthResponse,
  HiddenDependencyResponse,
  JobOut,
  RepoCreateResponse,
  RepoOut,
  RiskResponse,
} from "./types";

const ACTIVE_JOB_STATUSES = new Set(["queued", "running"]);
const JOB_POLL_INTERVAL_MS = 1500;

export function useSubmitRepo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => apiPost<RepoCreateResponse>("/repos", { url }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["repo"] });
    },
  });
}

export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => apiGet<JobOut>(`/jobs/${jobId}`),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ACTIVE_JOB_STATUSES.has(status) ? JOB_POLL_INTERVAL_MS : false;
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
      const stillWorking = status === "pending" || status === "mining" || status === "analyzing";
      return stillWorking ? JOB_POLL_INTERVAL_MS : false;
    },
  });
}

export function useCoupling(repoId: string | undefined) {
  return useQuery({
    queryKey: ["coupling", repoId],
    queryFn: () => apiGet<CouplingResponse>(`/repos/${repoId}/coupling`),
    enabled: Boolean(repoId),
  });
}

export function useArchitecture(repoId: string | undefined) {
  return useQuery({
    queryKey: ["architecture", repoId],
    queryFn: () => apiGet<ArchitectureResponse>(`/repos/${repoId}/architecture`),
    enabled: Boolean(repoId),
  });
}

export function useHiddenDeps(repoId: string | undefined) {
  return useQuery({
    queryKey: ["hidden-dependencies", repoId],
    queryFn: () => apiGet<HiddenDependencyResponse>(`/repos/${repoId}/hidden-dependencies`),
    enabled: Boolean(repoId),
  });
}

export function useRisk(repoId: string | undefined) {
  return useQuery({
    queryKey: ["risk", repoId],
    queryFn: () => apiGet<RiskResponse>(`/repos/${repoId}/risk`),
    enabled: Boolean(repoId),
  });
}

export function useHealth(repoId: string | undefined) {
  return useQuery({
    queryKey: ["health", repoId],
    queryFn: () => apiGet<HealthResponse>(`/repos/${repoId}/health`),
    enabled: Boolean(repoId),
    retry: false, // a 404 here means "not computed yet", not a transient failure
  });
}

export function useFindings(repoId: string | undefined, category?: string) {
  return useQuery({
    queryKey: ["findings", repoId, category ?? null],
    queryFn: () => {
      const qs = category ? `?category=${encodeURIComponent(category)}` : "";
      return apiGet<FindingsResponse>(`/repos/${repoId}/findings${qs}`);
    },
    enabled: Boolean(repoId),
  });
}

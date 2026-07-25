// Mirrors backend/app/schemas/{repo,analysis}.py. Keep in sync by hand --
// there's no shared codegen yet, so a backend field rename needs a matching
// edit here.

export type RepoStatus = "pending" | "mining" | "analyzing" | "ready" | "failed";
export type JobStatus = "queued" | "running" | "done" | "failed";
export type Severity = "low" | "med" | "high";

export interface RepoCreateResponse {
  repo_id: string;
  job_id: string;
}

export interface RepoOut {
  id: string;
  url: string;
  owner: string;
  name: string;
  default_branch: string | null;
  status: RepoStatus;
  commit_count: number;
  analyzed_at: string | null;
  created_at: string;
  file_count: number;
}

export interface JobOut {
  id: string;
  repo_id: string | null;
  job_type: string;
  status: JobStatus;
  progress: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface CouplingPairOut {
  file_a_path: string;
  file_b_path: string;
  coupling_degree: number;
  shared_revs: number;
  avg_revs: number;
  confidence: "low" | "medium" | "high";
}

export interface CouplingResponse {
  repo_id: string;
  low_confidence: boolean;
  pairs: CouplingPairOut[];
}

export interface DependencyEdgeOut {
  from_path: string;
  to_path: string;
}

export interface CycleOut {
  files: string[];
  severity: Severity;
}

export interface LayeringViolationOut {
  from_path: string;
  to_path: string;
  kind: "skip" | "inverted";
  severity: Severity;
}

export interface ArchitectureResponse {
  repo_id: string;
  nodes: string[];
  edges: DependencyEdgeOut[];
  cycles: CycleOut[];
  layering_violations: LayeringViolationOut[];
}

export interface HiddenDependencyOut {
  file_a_path: string;
  file_b_path: string;
  coupling_degree: number;
  shared_revs: number;
  severity: Severity;
  confidence: "low" | "medium" | "high";
}

export interface HiddenDependencyResponse {
  repo_id: string;
  pairs: HiddenDependencyOut[];
}

export interface RiskFileOut {
  file_path: string;
  language: string;
  risk_score: number;
  risk_confidence: number;
  hotspot_rank: number;
  churn_total: number;
  complexity: number;
  commit_count: number;
  max_coupling_degree: number;
}

export interface RiskResponse {
  repo_id: string;
  calibration: string;
  files: RiskFileOut[];
}

export interface HealthResponse {
  repo_id: string;
  calibration: string;
  score: number;
  high_risk_ratio: number;
  cycle_count: number;
  hidden_dependency_count: number;
  computed_at: string;
}

export interface FindingOut {
  id: string;
  category: string;
  severity: Severity;
  confidence: number;
  file_path: string | null;
  evidence_sha: string | null;
  title: string;
  detail: string;
  rank: number;
}

export interface FindingsResponse {
  repo_id: string;
  findings: FindingOut[];
}

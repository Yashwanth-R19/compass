// Mirrors backend/app/schemas/{repo,analysis}.py. Keep in sync by hand --
// there's no shared codegen yet, so a backend field rename needs a matching
// edit here.

export type RepoStatus = "pending" | "mining" | "analyzing" | "ready" | "failed";
export type JobStatus = "queued" | "running" | "done" | "failed";
export type Severity = "low" | "med" | "high";

// Phase 02: Facts/Insight split + progressive reveal (CLAUDE.md).
export type AnalysisRunStatus = "running" | "ready" | "failed" | "superseded";
export type StageName =
  | "clone"
  | "mine"
  | "structure"
  | "persist_facts"
  | "coupling"
  | "subsystems"
  | "architecture"
  | "risk"
  | "health"
  | "rank";
export type StageStatus = "pending" | "running" | "done" | "failed" | "skipped";

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
  is_private: boolean;
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

export interface StageOut {
  name: StageName;
  status: StageStatus;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  summary: Record<string, unknown> | null;
}

export interface RepoStatusResponse {
  repo_id: string;
  repo_status: RepoStatus;
  current_run_id: string | null;
  run_id: string | null;
  run_status: AnalysisRunStatus | null;
  run_error: string | null;
  stages: StageOut[];
}

export interface AnalysisRunOut {
  id: string;
  status: AnalysisRunStatus;
  head_sha: string;
  engine_version: number;
  started_at: string;
  finished_at: string | null;
}

export interface AnalysisRunsResponse {
  repo_id: string;
  runs: AnalysisRunOut[];
}

// Session 02: auth, history, and sharing (mirrors backend/app/schemas/{auth,me,share}.py).

export interface UserOut {
  id: string;
  github_login: string;
  name: string | null;
  avatar_url: string | null;
  has_repo_scope: boolean;
}

export interface MyRepoOut {
  id: string;
  url: string;
  owner: string;
  name: string;
  is_private: boolean;
  status: RepoStatus;
  latest_run_status: AnalysisRunStatus | null;
  analyzed_at: string | null;
  health_score: number | null;
}

export interface MyReposResponse {
  repos: MyRepoOut[];
  page: number;
  per_page: number;
  total: number;
}

export interface GithubRepoOut {
  full_name: string;
  private: boolean;
  size: number;
  language: string | null;
  pushed_at: string | null;
}

export interface MyGithubReposResponse {
  repos: GithubRepoOut[];
  truncated: boolean;
}

export interface ShareLinkOut {
  slug: string;
  created_at: string;
}

export interface SharedRunOut {
  repo_id: string;
  run_id: string;
}

// Session 04: subsystem discovery, entry points, module-level coupling
// (mirrors backend/app/schemas/analysis.py's new response models).

export type LabelSource = "path_prefix" | "identifiers" | "fallback";

export interface SubsystemMemberOut {
  file_path: string;
  centrality: number;
}

export interface SubsystemOut {
  label: string;
  label_source: LabelSource;
  file_count: number;
  total_loc: number;
  internal_edges: number;
  external_edges: number;
  cohesion: number;
  rank: number;
  members: SubsystemMemberOut[] | null;
}

export interface SubsystemsResponse {
  repo_id: string;
  modularity: number;
  subsystems: SubsystemOut[];
}

export type EntryPointKind =
  "cli" | "web_server" | "ui_root" | "test_root" | "build" | "graph_inferred";

export interface EntryPointOut {
  file_path: string;
  kind: EntryPointKind;
  evidence: string;
  confidence: number;
  rank: number;
}

export interface EntryPointsResponse {
  repo_id: string;
  entry_points: EntryPointOut[];
}

export type ModuleCouplingGranularity = "directory" | "subsystem";

export interface ModuleCouplingPairOut {
  module_a: string;
  module_b: string;
  granularity: ModuleCouplingGranularity;
  shared_revs: number;
  coupling_degree: number;
  avg_revs: number;
  confidence: "low" | "medium" | "high";
}

export interface ModuleCouplingResponse {
  repo_id: string;
  granularity: ModuleCouplingGranularity;
  low_confidence: boolean;
  pairs: ModuleCouplingPairOut[];
}

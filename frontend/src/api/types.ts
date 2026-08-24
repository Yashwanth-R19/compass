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
  | "knowledge"
  | "onboarding"
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

export interface UnreferencedFileOut {
  file_path: string;
  loc: number;
}

export interface ArchitectureResponse {
  repo_id: string;
  nodes: string[];
  edges: DependencyEdgeOut[];
  cycles: CycleOut[];
  layering_violations: LayeringViolationOut[];
  unreferenced_files: UnreferencedFileOut[];
  unreferenced_files_caveat: string;
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
  // Session 07 (Risk v2): surfaced alongside risk_score as evidence, never
  // folded into it -- the locked formula's weights are unchanged.
  churn_weighted: number;
  instability_score: number | null;
  revert_cycle_count: number | null;
  test_classification: string | null;
  test_cochange_ratio: number | null;
  expert_count: number;
  is_orphaned_knowledge: boolean;
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

// Session 05: contributor identities, DOA-based expertise, knowledge map,
// truck factor (mirrors backend/app/schemas/analysis.py's new response
// models). Display/privacy rules (plan/RULES.md sec 11) apply throughout:
// no full email ever appears here, only the *_masked fields the backend
// already masked server-side; every label reads as knowledge distribution,
// never performance.

export interface ContributorAliasOut {
  name: string;
  email_masked: string;
}

export interface ContributorOut {
  id: number;
  canonical_name: string;
  canonical_email_masked: string;
  aliases: ContributorAliasOut[];
  commit_count: number;
  lines_added: number;
  lines_deleted: number;
  first_commit_at: string;
  last_commit_at: string;
  is_bot: boolean;
  active_days: number;
  is_stale: boolean;
  rank: number;
}

export interface ContributorsResponse {
  repo_id: string;
  contributors: ContributorOut[];
}

export interface ExpertEntryOut {
  contributor_id: number;
  canonical_name: string;
  canonical_email_masked: string;
  doa: number;
  doa_normalized: number;
  is_expert: boolean;
  changes: number;
  last_touched_at: string;
  is_stale: boolean;
}

export interface ExpertiseResponse {
  repo_id: string;
  file_path: string;
  experts: ExpertEntryOut[];
}

export interface KnowledgeMapEntryOut {
  file_path: string;
  principal_expert_contributor_id: number | null;
  doa_normalized: number | null;
  subsystem_id: number | null;
}

export interface KnowledgeMapContributorOut {
  id: number;
  canonical_name: string;
  canonical_email_masked: string;
  is_bot: boolean;
  is_stale: boolean;
}

export interface KnowledgeMapResponse {
  repo_id: string;
  files: KnowledgeMapEntryOut[];
  contributors: KnowledgeMapContributorOut[];
}

export interface TruckFactorRemovalStepOut {
  contributor_id: number;
  name: string;
  files_orphaned: number;
  cumulative_orphan_ratio: number;
}

export interface TruckFactorResponse {
  repo_id: string;
  value: number;
  removal_order: TruckFactorRemovalStepOut[];
  total_files_considered: number;
  orphaned_file_count: number;
  note: string | null;
  interpretation: string;
}

// Session 06: guided reading order, domain glossary, repo passport (mirrors
// backend/app/schemas/analysis.py's TourResponse/GlossaryResponse/
// PassportResponse, and app/engines/passport.py's RepoPassportData, which
// PassportResponse.data embeds directly rather than a separate parallel shape).

export type TourReasonCode =
  | "documentation"
  | "entry_point"
  | "subsystem_anchor"
  | "high_centrality"
  | "widely_depended_on"
  | "hotspot";

export interface TourStopOut {
  position: number;
  file_path: string;
  reason_code: TourReasonCode;
  reason_detail: Record<string, unknown>;
  subsystem_label: string | null;
}

export interface TourResponse {
  repo_id: string;
  stops: TourStopOut[];
  subsystems_covered: number;
  of: number;
}

export interface GlossaryTermOut {
  term: string;
  score: number;
  occurrences: number;
  subsystem_spread: number;
  defining_paths: string[];
  rank: number;
}

export interface GlossaryResponse {
  repo_id: string;
  terms: GlossaryTermOut[];
  limitation: string;
}

export interface PassportIdentity {
  name: string;
  owner: string;
  url: string;
  primary_language: string;
  language_breakdown: Record<string, number>;
  license_spdx: string | null;
  has_readme: boolean;
  readme_lines: number;
}

export interface PassportScale {
  files: number;
  loc: number;
  commits: number;
  contributors: number;
  subsystems: number;
  age_days: number;
  first_commit_at: string | null;
  last_commit_at: string | null;
}

export interface PassportCadence {
  commits_last_30d: number;
  commits_last_90d: number;
  commits_last_365d: number;
  median_commits_per_active_week: number;
  active_days: number;
  longest_gap_days: number;
  is_dormant: boolean;
}

export interface PassportTopContributor {
  name: string;
  share: number;
  is_stale: boolean;
}

export interface PassportTeam {
  active_contributors: number;
  stale_contributors: number;
  bot_commit_ratio: number;
  truck_factor: number;
  top_contributors: PassportTopContributor[];
}

export interface PassportSubsystemSummary {
  label: string;
  file_count: number;
  cohesion: number;
}

export interface PassportEntryPointSummary {
  path: string;
  kind: EntryPointKind;
}

export interface PassportShape {
  subsystems: PassportSubsystemSummary[];
  entry_points: PassportEntryPointSummary[];
  modularity: number;
}

export interface PassportHotspotFile {
  path: string;
  risk_score: number;
  risk_confidence: number;
}

export interface PassportHotspots {
  top_risk_files: PassportHotspotFile[];
  churn_concentration: number;
}

export interface PassportHealth {
  score: number;
  high_risk_ratio: number;
  cycle_count: number;
  hidden_dependency_count: number;
  calibration: string;
}

// A structured orientation fact -- a CODE plus its backing PARAMS, never a
// rendered sentence. Session 08 owns the wording, in lib/copy.ts, with an
// exhaustiveness test there -- never build a sentence from these in a page.
export type FirstPrCode =
  | "HIGH_CHURN_CONCENTRATION"
  | "LOW_TRUCK_FACTOR"
  | "ORPHANED_HOTSPOT"
  | "HIDDEN_DEPENDENCIES"
  | "CIRCULAR_DEPENDENCIES"
  | "DORMANT"
  | "NO_TESTS"
  | "LOW_COHESION_SUBSYSTEM";

export interface PassportFirstPrItem {
  code: FirstPrCode;
  params: Record<string, unknown>;
}

export interface RepoPassportData {
  identity: PassportIdentity;
  scale: PassportScale;
  cadence: PassportCadence;
  team: PassportTeam;
  shape: PassportShape;
  hotspots: PassportHotspots;
  health: PassportHealth;
  first_pr: PassportFirstPrItem[];
}

export interface PassportResponse {
  repo_id: string;
  calibration: string;
  onboarding_difficulty: number;
  difficulty_breakdown: Record<string, { raw: number; normalized: number; weight: number }>;
  data: RepoPassportData;
}

// Session 07: blast radius (mirrors backend/app/analysis/blast_radius.py's
// dataclasses via app/schemas/analysis.py -- pure on-demand computation,
// never persisted), commit hygiene, and test gap / maintenance analysis
// (mirror app/engines/{hygiene,test_gaps}.py). No new StageName value --
// blast radius gates on "coupling"; hygiene and test-gaps both gate on
// "risk" (HygieneEngine/TestGapEngine run inside that stage, after
// RiskEngine -- no standalone stage).

export interface BlastRadiusAffectedFileOut {
  file_path: string;
  hop_distance: number | null;
  coupling_degree: number | null;
  risk_score: number | null;
}

export interface BlastRadiusEvidenceOut {
  affected_path: string;
  shared_commit_count: number;
  shared_commit_percentage: number;
  example_shas: string[];
}

export interface BlastRadiusExpertOut {
  contributor_id: number;
  canonical_name: string;
}

export interface BlastRadiusResponse {
  repo_id: string;
  file_path: string;
  depth: number;
  depth_capped: boolean;
  node_cap_engaged: boolean;
  structural_affected: BlastRadiusAffectedFileOut[];
  historical_affected: BlastRadiusAffectedFileOut[];
  surprising_affected: BlastRadiusAffectedFileOut[];
  total_affected_count: number;
  percentage_of_repo_files: number;
  subsystems_touched: string[];
  experts_to_review: BlastRadiusExpertOut[];
  total_affected_risk_score: number;
  commits_touching_path: number;
  historical_evidence: BlastRadiusEvidenceOut[];
}

export type HygieneEventKind = "oversized" | "fixup_churn" | "risky_commit";

export interface HygieneEventOut {
  kind: HygieneEventKind;
  commit_sha: string;
  occurred_at: string;
  detail: Record<string, unknown>;
  severity_hint: string;
}

export interface HygieneFileOut {
  file_path: string;
  instability_score: number | null;
  revert_cycle_count: number | null;
  oversized_commit_count: number | null;
  fixup_commit_count: number | null;
}

export interface HygieneResponse {
  repo_id: string;
  events_by_kind: Partial<Record<HygieneEventKind, HygieneEventOut[]>>;
  files: HygieneFileOut[];
  insufficient_history_for_oversized: boolean;
}

export type TestGapClassification = "no_test" | "stale_test" | "tracked";

export interface TestGapFileOut {
  file_path: string;
  classification: TestGapClassification;
  test_cochange_ratio: number | null;
  mapped_test_paths: string[];
}

export interface TestGapsResponse {
  repo_id: string;
  files: TestGapFileOut[];
  test_file_ratio: number;
  mean_test_cochange_ratio: number;
  limitation: string;
}

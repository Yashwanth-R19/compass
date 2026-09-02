// Fixture responses for the one Playwright happy-path test (Part H: "one
// test, not a suite" -- RULES.md sec 8). Shaped exactly like the real
// backend responses (frontend/src/api/types.ts) so this exercises the same
// parsing/rendering path a real API response would.
export const REPO_ID = "11111111-1111-1111-1111-111111111111";
export const RUN_ID = "22222222-2222-2222-2222-222222222222";

export const repoOut = {
  id: REPO_ID,
  url: "https://github.com/acme/widgets",
  owner: "acme",
  name: "widgets",
  default_branch: "main",
  status: "ready",
  commit_count: 500,
  analyzed_at: "2026-02-01T00:00:00Z",
  created_at: "2025-01-01T00:00:00Z",
  file_count: 120,
  is_private: false,
  is_showcase: false,
};

export const repoStatus = {
  repo_id: REPO_ID,
  repo_status: "ready",
  current_run_id: RUN_ID,
  facts_archived: false,
  run_id: RUN_ID,
  run_status: "ready",
  run_error: null,
  stages: [
    { name: "onboarding", status: "done", started_at: null, finished_at: null, error: null, summary: { stops: 2 } },
  ],
};

export const passportResponse = {
  repo_id: REPO_ID,
  calibration: "heuristic",
  onboarding_difficulty: 42,
  difficulty_breakdown: {
    subsystem_count: { raw: 5, normalized: 0.5, weight: 0.25 },
    median_file_complexity: { raw: 3.2, normalized: 0.4, weight: 0.2 },
    doc_coverage: { raw: 0.6, normalized: 0.4, weight: 0.2 },
    truck_factor: { raw: 2, normalized: 0.5, weight: 0.2 },
    max_dependency_depth: { raw: 4, normalized: 0.3, weight: 0.15 },
  },
  data: {
    identity: {
      name: "widgets",
      owner: "acme",
      url: "https://github.com/acme/widgets",
      primary_language: "python",
      language_breakdown: { python: 80, typescript: 20 },
      license_spdx: "MIT",
      has_readme: true,
      readme_lines: 30,
    },
    scale: {
      files: 120,
      loc: 15000,
      commits: 500,
      contributors: 8,
      subsystems: 5,
      age_days: 400,
      first_commit_at: "2025-01-01T00:00:00Z",
      last_commit_at: "2026-02-01T00:00:00Z",
    },
    cadence: {
      commits_last_30d: 10,
      commits_last_90d: 40,
      commits_last_365d: 200,
      median_commits_per_active_week: 3.5,
      active_days: 120,
      longest_gap_days: 14,
      is_dormant: false,
    },
    team: {
      active_contributors: 6,
      stale_contributors: 2,
      bot_commit_ratio: 0.05,
      truck_factor: 2,
      top_contributors: [
        { name: "Jane Doe", share: 0.4, is_stale: false },
        { name: "Bob Smith", share: 0.25, is_stale: true },
      ],
    },
    shape: {
      subsystems: [{ label: "billing", file_count: 20, cohesion: 0.7 }],
      entry_points: [{ path: "src/app.py", kind: "web_server" }],
      modularity: 0.55,
    },
    hotspots: {
      top_risk_files: [{ path: "src/billing/invoice.py", risk_score: 0.8, risk_confidence: 0.9 }],
      churn_concentration: 0.6,
    },
    health: { score: 72, high_risk_ratio: 0.12, cycle_count: 1, hidden_dependency_count: 3, calibration: "heuristic" },
    first_pr: [
      { code: "LOW_TRUCK_FACTOR", params: { truck_factor: 2 } },
      { code: "HIDDEN_DEPENDENCIES", params: { count: 3 } },
    ],
  },
};

export const entryPointsResponse = {
  repo_id: REPO_ID,
  entry_points: [
    {
      file_path: "src/app.py",
      kind: "web_server",
      evidence: "Referenced by package.json scripts.start.",
      confidence: 0.95,
      rank: 0,
    },
  ],
};

export const tourResponse = {
  repo_id: REPO_ID,
  stops: [
    {
      position: 1,
      file_path: "README.md",
      reason_code: "documentation",
      reason_detail: {
        in_degree: 0,
        out_degree: 0,
        pagerank: 0.01,
        loc: 30,
        complexity: 0,
        risk_score: null,
        risk_confidence: null,
        subsystem: null,
        top_expert: null,
        last_touched_at: "2026-01-01T00:00:00Z",
        reasons: { documentation: {} },
      },
      subsystem_label: null,
    },
    {
      position: 2,
      file_path: "src/app.py",
      reason_code: "entry_point",
      reason_detail: {
        in_degree: 0,
        out_degree: 5,
        pagerank: 0.08,
        loc: 120,
        complexity: 4,
        risk_score: 0.5,
        risk_confidence: 0.7,
        subsystem: "billing",
        top_expert: "Jane Doe",
        last_touched_at: "2026-02-01T00:00:00Z",
        reasons: { entry_point: { confidence: 0.95 } },
      },
      subsystem_label: "billing",
    },
  ],
  subsystems_covered: 1,
  of: 5,
};

export const knowledgeMapResponse = {
  repo_id: REPO_ID,
  files: [
    { file_path: "src/app.py", principal_expert_contributor_id: 1, doa_normalized: 0.92, subsystem_id: 1 },
    { file_path: "README.md", principal_expert_contributor_id: null, doa_normalized: null, subsystem_id: null },
  ],
  contributors: [
    { id: 1, canonical_name: "Jane Doe", canonical_email_masked: "j***@example.com", is_bot: false, is_stale: false },
  ],
};

export const contributorsResponse = {
  repo_id: REPO_ID,
  contributors: [
    {
      id: 1,
      canonical_name: "Jane Doe",
      canonical_email_masked: "j***@example.com",
      aliases: [{ name: "Jane Doe", email_masked: "j***@example.com" }],
      commit_count: 300,
      lines_added: 5000,
      lines_deleted: 2000,
      first_commit_at: "2025-01-01T00:00:00Z",
      last_commit_at: "2026-02-01T00:00:00Z",
      is_bot: false,
      active_days: 100,
      is_stale: false,
      rank: 0,
    },
    {
      id: 2,
      canonical_name: "Bob Smith",
      canonical_email_masked: "b***@example.com",
      aliases: [{ name: "Bob Smith", email_masked: "b***@example.com" }],
      commit_count: 200,
      lines_added: 3000,
      lines_deleted: 1000,
      first_commit_at: "2025-02-01T00:00:00Z",
      last_commit_at: "2025-11-01T00:00:00Z",
      is_bot: false,
      active_days: 60,
      is_stale: true,
      rank: 1,
    },
  ],
};

export const truckFactorResponse = {
  repo_id: REPO_ID,
  value: 2,
  removal_order: [
    { contributor_id: 1, name: "Jane Doe", files_orphaned: 40, cumulative_orphan_ratio: 0.34 },
    { contributor_id: 2, name: "Bob Smith", files_orphaned: 20, cumulative_orphan_ratio: 0.51 },
  ],
  total_files_considered: 120,
  orphaned_file_count: 5,
  note: null,
  interpretation:
    "This measures the project's knowledge-distribution risk, not any individual's importance.",
};

export const expertiseResponse = {
  repo_id: REPO_ID,
  file_path: "src/app.py",
  experts: [
    {
      contributor_id: 1,
      canonical_name: "Jane Doe",
      canonical_email_masked: "j***@example.com",
      doa: 3.8,
      doa_normalized: 0.92,
      is_expert: true,
      changes: 40,
      last_touched_at: "2026-02-01T00:00:00Z",
      is_stale: false,
    },
  ],
};

// --- Session 09: codebase map + impact explorer fixtures -------------------

export const subsystemsResponse = {
  repo_id: REPO_ID,
  modularity: 0.42,
  subsystems: [
    {
      label: "billing",
      label_source: "path_prefix",
      file_count: 2,
      total_loc: 150,
      internal_edges: 1,
      external_edges: 1,
      cohesion: 0.8,
      rank: 0,
      members: [
        { file_path: "src/app.py", centrality: 0.5 },
        { file_path: "src/billing/invoice.py", centrality: 0.3 },
      ],
    },
    {
      label: "auth",
      label_source: "path_prefix",
      file_count: 1,
      total_loc: 50,
      internal_edges: 0,
      external_edges: 1,
      cohesion: 0.0,
      rank: 1,
      members: [{ file_path: "src/auth/login.py", centrality: 0.2 }],
    },
  ],
};

export const moduleCouplingSubsystemResponse = {
  repo_id: REPO_ID,
  granularity: "subsystem",
  low_confidence: false,
  pairs: [
    {
      module_a: "billing",
      module_b: "auth",
      granularity: "subsystem",
      shared_revs: 6,
      coupling_degree: 0.6,
      avg_revs: 8,
      confidence: "medium",
    },
  ],
};

export const architectureResponse = {
  repo_id: REPO_ID,
  nodes: ["src/app.py", "src/billing/invoice.py", "src/auth/login.py"],
  edges: [{ from_path: "src/app.py", to_path: "src/billing/invoice.py" }],
  cycles: [],
  layering_violations: [],
  unreferenced_files: [],
  unreferenced_files_caveat: "A file can appear here even when it's genuinely used.",
};

export const couplingResponse = {
  repo_id: REPO_ID,
  low_confidence: false,
  pairs: [
    {
      file_a_path: "src/app.py",
      file_b_path: "src/auth/login.py",
      coupling_degree: 0.6,
      shared_revs: 6,
      avg_revs: 8,
      confidence: "medium",
    },
  ],
};

export const hiddenDependenciesResponse = {
  repo_id: REPO_ID,
  pairs: [
    {
      file_a_path: "src/app.py",
      file_b_path: "src/auth/login.py",
      coupling_degree: 0.6,
      shared_revs: 6,
      severity: "med",
      confidence: "medium",
    },
  ],
};

export const cityResponse = {
  repo_id: REPO_ID,
  subsystems: [
    { id: 1, label: "billing", file_count: 2, total_loc: 150 },
    { id: 2, label: "auth", file_count: 1, total_loc: 50 },
  ],
  files: {
    columns: [
      "path",
      "subsystem_id",
      "loc",
      "complexity",
      "risk_score",
      "risk_confidence",
      "principal_expert_id",
      "last_modified_at",
      "commit_count",
      "is_test",
      "churn_weighted",
    ],
    rows: [
      ["src/app.py", 1, 120, 4, 0.5, 0.7, 1, 1750000000, 40, false, 12.5],
      ["src/billing/invoice.py", 1, 30, 2, 0.3, 0.5, null, 1740000000, 10, false, 3.0],
      ["src/auth/login.py", 2, 50, 3, 0.8, 0.6, 1, 1760000000, 20, false, 8.0],
    ],
  },
  contributors: [{ id: 1, name: "Jane Doe" }],
  bounds: {
    loc: { min: 30, max: 120 },
    complexity: { min: 2, max: 4 },
    risk_score: { min: 0.3, max: 0.8 },
    churn_weighted: { min: 3.0, max: 12.5 },
    commit_count: { min: 10, max: 40 },
    last_modified_at: { min: 1740000000, max: 1760000000 },
  },
};

// --- Session 11: Audit mode -- findings deep-link, and a failed optional
// "security" stage rendering one errored section next to a working one. ----

export const findingsResponse = {
  repo_id: REPO_ID,
  findings: [
    {
      id: "f1",
      category: "hidden_dependency",
      severity: "med",
      confidence: 0.7,
      file_path: "src/app.py",
      evidence_sha: null,
      title: "Hidden dependency: src/app.py <-> src/auth/login.py",
      detail:
        "These files change together in 6 commits (coupling_degree=0.60) but neither imports the other.",
      rank: 0,
    },
  ],
};

// A second repo, deliberately separate from REPO_ID, whose "security" stage
// (session 10's `optional=True` stage) has failed while the run itself
// still reached "ready" -- the exact scenario session 10's Part E exists
// for, and this page must render two sections where only one is errored.
export const REPO_ID_2 = "33333333-3333-3333-3333-333333333333";
export const RUN_ID_2 = "44444444-4444-4444-4444-444444444444";

export const repoOutSecurityFail = {
  ...repoOut,
  id: REPO_ID_2,
  url: "https://github.com/acme/leaky",
  owner: "acme",
  name: "leaky",
};

export const repoStatusSecurityFailed = {
  repo_id: REPO_ID_2,
  repo_status: "ready",
  current_run_id: RUN_ID_2,
  run_id: RUN_ID_2,
  run_status: "ready",
  run_error: null,
  stages: [
    {
      name: "secrets",
      status: "done",
      started_at: null,
      finished_at: null,
      error: null,
      summary: { hits_found: 1 },
    },
    {
      name: "security",
      status: "failed",
      started_at: null,
      finished_at: null,
      error: "OSV.dev request failed after 3 attempts",
      summary: null,
    },
  ],
};

export const secretsResponseWithHistoryHit = {
  repo_id: REPO_ID_2,
  hits: [
    {
      rule_id: "aws-access-key-id",
      description: "AWS Access Key ID",
      file_path: "config/old_settings.py",
      commit_sha: "deadbeef1234567890",
      committed_at: "2025-06-01T00:00:00Z",
      line_number: 12,
      redacted_preview: "AKIA****************XZ",
      entropy: null,
      still_in_head: false,
    },
  ],
  still_in_head_count: 0,
  total: 1,
  truncated: false,
  truncation_reason: null,
};

// The "security" stage failed, so this is the honestly-empty 200 the real
// backend's `_pending_response` returns rather than hanging -- the page's
// "errored" treatment comes from `/status`'s stage row, not this response.
export const vulnerabilitiesResponseEmpty = {
  repo_id: REPO_ID_2,
  vulnerabilities: [],
  no_supported_manifest: false,
};

export const blastRadiusResponse = {
  repo_id: REPO_ID,
  file_path: "src/app.py",
  depth: 3,
  depth_capped: false,
  node_cap_engaged: false,
  structural_affected: [
    { file_path: "src/billing/invoice.py", hop_distance: 1, coupling_degree: null, risk_score: 0.3 },
  ],
  historical_affected: [
    { file_path: "src/auth/login.py", hop_distance: null, coupling_degree: 0.6, risk_score: 0.8 },
  ],
  surprising_affected: [
    { file_path: "src/auth/login.py", hop_distance: null, coupling_degree: 0.6, risk_score: 0.8 },
  ],
  total_affected_count: 2,
  percentage_of_repo_files: 0.02,
  subsystems_touched: ["billing", "auth"],
  experts_to_review: [{ contributor_id: 1, canonical_name: "Jane Doe" }],
  total_affected_risk_score: 1.1,
  commits_touching_path: 47,
  historical_evidence: [
    {
      affected_path: "src/auth/login.py",
      shared_commit_count: 31,
      shared_commit_percentage: 0.6595744680851063,
      example_shas: ["abc1234def5678"],
    },
  ],
};

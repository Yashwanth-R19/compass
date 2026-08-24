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
};

export const repoStatus = {
  repo_id: REPO_ID,
  repo_status: "ready",
  current_run_id: RUN_ID,
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

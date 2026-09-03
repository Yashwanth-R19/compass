// The single home for every user-facing sentence derived from a backend
// enum (RULES.md sec 13 / CLAUDE.md's frontend conventions). No page
// component may construct such a sentence inline -- add or extend an entry
// here instead. Every map is total over its enum's TypeScript union, so
// dropping a member is a compile error, not a silent blank render; the
// companion exhaustiveness test (lib/copy.test.ts) additionally walks a
// literal list of every value the backend can currently emit (kept in sync
// by hand with the backend engines, same discipline as api/types.ts) so a
// backend enum member that was never added to the frontend's own union type
// still gets caught at test time, not just at the type-checker's mercy.
import type {
  ContributorChangeKind,
  CouplingChangeKind,
  EntryPointKind,
  FindingCategory,
  FirstPrCode,
  HygieneEventKind,
  LabelSource,
  SubsystemChangeKind,
  TestGapClassification,
  TourReasonCode,
} from "../api/types";
import { formatPercent, formatScore } from "./format";

// --- Tour reason codes -----------------------------------------------------

// The fixed universal field set every tour_stops.reason_detail carries
// (app/engines/tour.py::TourEngine, CLAUDE.md's "Guided reading order").
export interface TourReasonDetail {
  in_degree?: number;
  out_degree?: number;
  pagerank?: number;
  loc?: number;
  complexity?: number;
  risk_score?: number | null;
  risk_confidence?: number | null;
  subsystem?: string | null;
  top_expert?: string | null;
  last_touched_at?: string | null;
  reasons?: Record<string, Record<string, unknown>>;
}

function pct(value: number | null | undefined): string {
  return typeof value === "number" ? formatPercent(value) : "unknown";
}

function dec(value: number | null | undefined): string {
  return typeof value === "number" ? formatScore(value, 3) : "unknown";
}

export const TOUR_REASON_COPY: Record<TourReasonCode, (detail: TourReasonDetail) => string> = {
  documentation: () =>
    "The repository's README — the conventional starting point for anyone new here.",
  entry_point: (d) =>
    `A detected entry point — where execution starts, with ${d.out_degree ?? 0} outgoing imports into the rest of the codebase.`,
  subsystem_anchor: (d) =>
    `The most central file in ${d.subsystem ? `"${d.subsystem}"` : "its subsystem"} — reading it first orients you to that subsystem.`,
  high_centrality: (d) =>
    `Broadly relied on across the whole codebase (PageRank ${dec(d.pagerank)}) — many other files trace back to this one.`,
  widely_depended_on: (d) =>
    `${d.in_degree ?? 0} other files import this one directly, making it a load-bearing dependency.`,
  hotspot: (d) =>
    `A risk hotspot (score ${pct(d.risk_score)}) — frequently changed and complex, worth understanding early.`,
};

// --- Repo passport "three things to know" ----------------------------------

export const FIRST_PR_COPY: Record<FirstPrCode, (params: Record<string, unknown>) => string> = {
  HIGH_CHURN_CONCENTRATION: (p) =>
    `${pct(p.churn_concentration as number)} of all code changes are concentrated in the busiest 10% of files — expect a handful of files to dominate the history.`,
  LOW_TRUCK_FACTOR: (p) => {
    const n = Number(p.truck_factor ?? 0);
    return `Only ${n} ${n === 1 ? "person" : "people"} would need to leave before more than half the codebase loses its expert.`;
  },
  ORPHANED_HOTSPOT: (p) =>
    p.path
      ? `${String(p.path)} is a top-risk file whose only expert has gone quiet.`
      : "A top-risk file's only expert has gone quiet.",
  HIDDEN_DEPENDENCIES: (p) => {
    const n = Number(p.count ?? 0);
    return `${n} pair${n === 1 ? "" : "s"} of files change together constantly but share no import — see Coupling.`;
  },
  CIRCULAR_DEPENDENCIES: (p) => {
    const n = Number(p.count ?? 0);
    return `${n} circular import ${n === 1 ? "chain exists" : "chains exist"} in the dependency graph.`;
  },
  DORMANT: (p) =>
    `No commits in the last ${Math.round(Number(p.days_since_last_commit ?? 0))} days — this repository looks dormant.`,
  NO_TESTS: () =>
    "No test-root directory was detected — this repository may have little or no automated testing.",
  LOW_COHESION_SUBSYSTEM: (p) =>
    p.label
      ? `The "${String(p.label)}" subsystem has low internal cohesion (${pct(p.cohesion as number)}) — its files may not really belong together.`
      : "One subsystem has low internal cohesion.",
};

// Where "read more" for each first_pr code should point -- a route
// fragment relative to /repos/:repoId/, joined by the caller. UI rebuild
// session 3: repointed from the outgoing onboard/*|audit/* dual-mode paths
// onto the eight consolidated surfaces (plan/UI_REBUILD_SESSIONS.md section
// 4.1) -- lib/copy.test.ts only asserts each entry is a non-empty string,
// never the literal path, so this rename doesn't touch that test.
export const FIRST_PR_LINK: Record<FirstPrCode, string> = {
  HIGH_CHURN_CONCENTRATION: "risk?tab=hotspots",
  LOW_TRUCK_FACTOR: "people",
  ORPHANED_HOTSPOT: "people",
  HIDDEN_DEPENDENCIES: "structure?view=coupling",
  CIRCULAR_DEPENDENCIES: "structure?view=architecture",
  DORMANT: "overview",
  NO_TESTS: "risk?tab=hotspots",
  LOW_COHESION_SUBSYSTEM: "overview",
};

// --- Finding categories ------------------------------------------------

export const FINDING_CATEGORY_COPY: Record<FindingCategory, () => string> = {
  risk: () => "Risk",
  architecture: () => "Architecture",
  hidden_dependency: () => "Hidden dependency",
  knowledge: () => "Knowledge",
  hygiene: () => "Hygiene",
  test_gap: () => "Test gap",
  // Session 11: app/engines/security.py::SecurityEngine.
  secret: () => "Secret",
  vulnerability: () => "Vulnerability",
};

// --- Commit hygiene ----------------------------------------------------

// Mirrors hygiene_events.detail's per-kind shape (app/engines/hygiene.py).
// NEVER read detail.author_email here, even though the backend's JSONB blob
// carries it raw for fixup_churn -- plan/RULES.md sec 11.2 forbids
// rendering a full email address anywhere, and this detail blob is not run
// through mask_email() server-side (see CLAUDE.md's frontend section for
// the flagged backend gap). author_name alone is used instead.
export const HYGIENE_KIND_COPY: Record<
  HygieneEventKind,
  (detail: Record<string, unknown>) => string
> = {
  oversized: (d) =>
    `Changed ${d.files_changed ?? "?"} files and ${d.churn ?? "?"} lines — both above this repository's own 95th percentile commit size.`,
  fixup_churn: (d) =>
    `${d.author_name ?? "A contributor"} made ${d.cluster_size ?? "several"} consecutive fixup-style commits to overlapping files in a short window.`,
  risky_commit: (d) =>
    `Met ${d.score ?? "several"} of 4 risky-commit conditions — wide subsystem spread, top-quintile churn, no test files touched, and/or a very short message.`,
};

export const HYGIENE_KIND_LABEL: Record<HygieneEventKind, () => string> = {
  oversized: () => "Oversized commit",
  fixup_churn: () => "Fixup churn",
  risky_commit: () => "Risky commit",
};

// --- Entry points --------------------------------------------------------

export const ENTRY_POINT_KIND_COPY: Record<EntryPointKind, () => string> = {
  cli: () => "Command-line entry point",
  web_server: () => "Web server entry point",
  ui_root: () => "UI root",
  test_root: () => "Test suite root",
  build: () => "Build entry point",
  graph_inferred: () =>
    "Inferred from the dependency graph (nothing imports it, and it imports several others)",
};

// --- Test maintenance classification --------------------------------------

export const TEST_CLASSIFICATION_COPY: Record<TestGapClassification, () => string> = {
  no_test: () => "No mapped test was found for this file.",
  stale_test: () => "A mapped test exists but rarely changes alongside this file.",
  tracked: () => "A mapped test changes alongside this file.",
};

// --- Subsystem naming provenance -------------------------------------------

export const LABEL_SOURCE_COPY: Record<LabelSource, () => string> = {
  path_prefix: () => "Named from a shared directory prefix",
  identifiers: () => "Named from its most common identifier",
  fallback: () => "No confident name could be derived",
};

// --- Session 13: run-vs-run compare -----------------------------------------

export const SUBSYSTEM_CHANGE_COPY: Record<SubsystemChangeKind, () => string> = {
  appeared: () => "New subsystem",
  disappeared: () => "Subsystem gone",
  merged: () => "Merged from",
  split: () => "Split into",
};

export const CONTRIBUTOR_CHANGE_COPY: Record<ContributorChangeKind, () => string> = {
  joined: () => "Joined",
  left: () => "Left",
  went_stale: () => "Went quiet",
};

export const COUPLING_CHANGE_COPY: Record<CouplingChangeKind, () => string> = {
  appeared: () => "New pairing",
  strengthened: () => "Strengthened",
  weakened: () => "Weakened",
  vanished: () => "No longer coupled",
};

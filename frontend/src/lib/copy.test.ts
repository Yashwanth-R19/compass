import { describe, expect, it } from "vitest";
import {
  CONTRIBUTOR_CHANGE_COPY,
  COUPLING_CHANGE_COPY,
  ENTRY_POINT_KIND_COPY,
  FINDING_CATEGORY_COPY,
  FIRST_PR_COPY,
  FIRST_PR_LINK,
  HYGIENE_KIND_COPY,
  HYGIENE_KIND_LABEL,
  LABEL_SOURCE_COPY,
  SUBSYSTEM_CHANGE_COPY,
  TEST_CLASSIFICATION_COPY,
  TOUR_REASON_COPY,
} from "./copy";

// Every value each backend enum can currently emit, kept in sync by hand
// with the backend (same discipline as api/types.ts's own hand-mirroring) --
// see each engine cited below for where the value actually originates.
// This is deliberately a literal list, not derived from the copy maps
// themselves: the whole point is to catch a map that's missing an entry,
// which a list built FROM that same map could never do.
const TOUR_REASON_CODES = [
  "documentation",
  "entry_point",
  "subsystem_anchor",
  "high_centrality",
  "widely_depended_on",
  "hotspot",
] as const;

const FIRST_PR_CODES = [
  "HIGH_CHURN_CONCENTRATION",
  "LOW_TRUCK_FACTOR",
  "ORPHANED_HOTSPOT",
  "HIDDEN_DEPENDENCIES",
  "CIRCULAR_DEPENDENCIES",
  "DORMANT",
  "NO_TESTS",
  "LOW_COHESION_SUBSYSTEM",
] as const;

// grep for `"category":` under backend/app/engines/ to reproduce this list.
// Session 11 added "secret"/"vulnerability" (app/engines/security.py).
const FINDING_CATEGORIES = [
  "risk",
  "architecture",
  "hidden_dependency",
  "knowledge",
  "hygiene",
  "test_gap",
  "secret",
  "vulnerability",
] as const;

const HYGIENE_EVENT_KINDS = ["oversized", "fixup_churn", "risky_commit"] as const;

const ENTRY_POINT_KINDS = [
  "cli",
  "web_server",
  "ui_root",
  "test_root",
  "build",
  "graph_inferred",
] as const;

const TEST_GAP_CLASSIFICATIONS = ["no_test", "stale_test", "tracked"] as const;

const LABEL_SOURCES = ["path_prefix", "identifiers", "fallback"] as const;

// Session 13, app/analysis/compare.py -- these three are frontend-only
// literal unions layered over the backend's plain `str` fields (same
// pattern as EntryPointKind/TourReasonCode), reproduced here by hand from
// that module's own `kind=`/SecurityDiffOut docstrings.
const SUBSYSTEM_CHANGE_KINDS = ["appeared", "disappeared", "merged", "split"] as const;
const CONTRIBUTOR_CHANGE_KINDS = ["joined", "left", "went_stale"] as const;
const COUPLING_CHANGE_KINDS = ["appeared", "strengthened", "weakened", "vanished"] as const;

// A representative, non-empty params object for each params-taking map --
// enough for every branch to have something to interpolate, so a function
// that only produces a non-empty string when a field happens to be present
// doesn't silently pass.
const SAMPLE_TOUR_DETAIL = {
  in_degree: 3,
  out_degree: 2,
  pagerank: 0.042,
  loc: 120,
  complexity: 4.5,
  risk_score: 0.6,
  risk_confidence: 0.8,
  subsystem: "billing",
  top_expert: "Jane Doe",
  last_touched_at: "2026-01-01T00:00:00Z",
  reasons: {},
};

const SAMPLE_FIRST_PR_PARAMS: Record<string, Record<string, unknown>> = {
  HIGH_CHURN_CONCENTRATION: { churn_concentration: 0.6 },
  LOW_TRUCK_FACTOR: { truck_factor: 1 },
  ORPHANED_HOTSPOT: { path: "src/billing/invoice.py" },
  HIDDEN_DEPENDENCIES: { count: 3 },
  CIRCULAR_DEPENDENCIES: { count: 2 },
  DORMANT: { days_since_last_commit: 400 },
  NO_TESTS: {},
  LOW_COHESION_SUBSYSTEM: { label: "billing", cohesion: 0.2 },
};

const SAMPLE_HYGIENE_DETAIL: Record<string, Record<string, unknown>> = {
  oversized: { files_changed: 42, churn: 900, files_changed_p95: 20, churn_p95: 400 },
  fixup_churn: { author_name: "Jane Doe", cluster_size: 4 },
  risky_commit: { score: 3, files_changed: 5, churn: 200, message_length: 4 },
};

describe("copy.ts exhaustiveness", () => {
  it("TOUR_REASON_COPY covers every tour reason code and never renders blank", () => {
    for (const code of TOUR_REASON_CODES) {
      expect(TOUR_REASON_COPY[code], `missing TOUR_REASON_COPY entry for "${code}"`).toBeTypeOf(
        "function",
      );
      expect(TOUR_REASON_COPY[code](SAMPLE_TOUR_DETAIL).trim().length).toBeGreaterThan(0);
    }
  });

  it("FIRST_PR_COPY and FIRST_PR_LINK cover every first_pr code", () => {
    for (const code of FIRST_PR_CODES) {
      expect(FIRST_PR_COPY[code], `missing FIRST_PR_COPY entry for "${code}"`).toBeTypeOf(
        "function",
      );
      expect(FIRST_PR_COPY[code](SAMPLE_FIRST_PR_PARAMS[code]).trim().length).toBeGreaterThan(0);
      expect(FIRST_PR_LINK[code], `missing FIRST_PR_LINK entry for "${code}"`).toBeTypeOf("string");
      expect(FIRST_PR_LINK[code].length).toBeGreaterThan(0);
    }
  });

  it("FINDING_CATEGORY_COPY covers every finding category", () => {
    for (const category of FINDING_CATEGORIES) {
      expect(
        FINDING_CATEGORY_COPY[category],
        `missing FINDING_CATEGORY_COPY entry for "${category}"`,
      ).toBeTypeOf("function");
      expect(FINDING_CATEGORY_COPY[category]().trim().length).toBeGreaterThan(0);
    }
  });

  it("HYGIENE_KIND_COPY and HYGIENE_KIND_LABEL cover every hygiene event kind", () => {
    for (const kind of HYGIENE_EVENT_KINDS) {
      expect(HYGIENE_KIND_COPY[kind], `missing HYGIENE_KIND_COPY entry for "${kind}"`).toBeTypeOf(
        "function",
      );
      expect(HYGIENE_KIND_COPY[kind](SAMPLE_HYGIENE_DETAIL[kind]).trim().length).toBeGreaterThan(0);
      expect(HYGIENE_KIND_LABEL[kind]().trim().length).toBeGreaterThan(0);
      // The backend's fixup_churn detail carries a raw author_email
      // alongside author_name (never masked -- see CLAUDE.md's flagged
      // backend gap); the copy MUST NOT surface it even if it's present.
      expect(
        HYGIENE_KIND_COPY[kind]({
          ...SAMPLE_HYGIENE_DETAIL[kind],
          author_email: "jane@example.com",
        }),
      ).not.toContain("jane@example.com");
    }
  });

  it("ENTRY_POINT_KIND_COPY covers every entry point kind", () => {
    for (const kind of ENTRY_POINT_KINDS) {
      expect(
        ENTRY_POINT_KIND_COPY[kind],
        `missing ENTRY_POINT_KIND_COPY entry for "${kind}"`,
      ).toBeTypeOf("function");
      expect(ENTRY_POINT_KIND_COPY[kind]().trim().length).toBeGreaterThan(0);
    }
  });

  it("TEST_CLASSIFICATION_COPY covers every test gap classification", () => {
    for (const classification of TEST_GAP_CLASSIFICATIONS) {
      expect(
        TEST_CLASSIFICATION_COPY[classification],
        `missing TEST_CLASSIFICATION_COPY entry for "${classification}"`,
      ).toBeTypeOf("function");
      expect(TEST_CLASSIFICATION_COPY[classification]().trim().length).toBeGreaterThan(0);
    }
  });

  it("LABEL_SOURCE_COPY covers every subsystem label source", () => {
    for (const source of LABEL_SOURCES) {
      expect(
        LABEL_SOURCE_COPY[source],
        `missing LABEL_SOURCE_COPY entry for "${source}"`,
      ).toBeTypeOf("function");
      expect(LABEL_SOURCE_COPY[source]().trim().length).toBeGreaterThan(0);
    }
  });

  it("SUBSYSTEM_CHANGE_COPY covers every subsystem change kind", () => {
    for (const kind of SUBSYSTEM_CHANGE_KINDS) {
      expect(
        SUBSYSTEM_CHANGE_COPY[kind],
        `missing SUBSYSTEM_CHANGE_COPY entry for "${kind}"`,
      ).toBeTypeOf("function");
      expect(SUBSYSTEM_CHANGE_COPY[kind]().trim().length).toBeGreaterThan(0);
    }
  });

  it("CONTRIBUTOR_CHANGE_COPY covers every contributor change kind", () => {
    for (const kind of CONTRIBUTOR_CHANGE_KINDS) {
      expect(
        CONTRIBUTOR_CHANGE_COPY[kind],
        `missing CONTRIBUTOR_CHANGE_COPY entry for "${kind}"`,
      ).toBeTypeOf("function");
      expect(CONTRIBUTOR_CHANGE_COPY[kind]().trim().length).toBeGreaterThan(0);
    }
  });

  it("COUPLING_CHANGE_COPY covers every coupling change kind", () => {
    for (const kind of COUPLING_CHANGE_KINDS) {
      expect(
        COUPLING_CHANGE_COPY[kind],
        `missing COUPLING_CHANGE_COPY entry for "${kind}"`,
      ).toBeTypeOf("function");
      expect(COUPLING_CHANGE_COPY[kind]().trim().length).toBeGreaterThan(0);
    }
  });
});

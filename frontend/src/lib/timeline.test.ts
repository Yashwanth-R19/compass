import { describe, expect, it } from "vitest";
import type { TimelineBounds, TimelineSnapshotOut } from "../api/types";
import { contributorBandData, fixedDomain, hotspotBarDomain, snapshotDelta } from "./timeline";

const BOUNDS: TimelineBounds = {
  file_count: { min: 0, max: 100 },
  churn_to_date: { min: 0, max: 5000 },
  commits_to_date: { min: 0, max: 500 },
  active_contributors: { min: 0, max: 10 },
  coupling_pairs_count: { min: 0, max: 20 },
  hotspot_churn: { min: 0, max: 9000 },
};

function snapshot(overrides: Partial<TimelineSnapshotOut>): TimelineSnapshotOut {
  return {
    position: 0,
    commit_sha: "sha",
    at_date: "2024-01-01T00:00:00Z",
    commit_index: 0,
    file_count: 10,
    churn_to_date: 100,
    commits_to_date: 5,
    active_contributors: 2,
    contributor_shares: [],
    coupling_pairs_count: 0,
    top_coupling_pairs: [],
    churn_ranked_hotspots: [],
    ...overrides,
  };
}

describe("fixed-scale contract (Known Hazard #4)", () => {
  it("the hotspot bar domain comes from bounds, not from either frame's own data", () => {
    // Two wildly different "frames" of actual data -- the domain must be
    // identical regardless of which one is currently displayed, because it
    // is computed from the server's global bounds, never from either frame.
    const frameWithSmallValues = [10, 20, 5];
    const frameWithHugeValues = [8000, 100, 50];

    const domainForFrameA = hotspotBarDomain(BOUNDS);
    const domainForFrameB = hotspotBarDomain(BOUNDS);

    expect(domainForFrameA).toEqual(domainForFrameB);
    expect(domainForFrameA).toEqual([0, 9000]);
    expect(domainForFrameA[1]).not.toEqual(Math.max(...frameWithSmallValues));
    expect(domainForFrameA[1]).not.toEqual(Math.max(...frameWithHugeValues));
  });

  it("fixedDomain never collapses to [0, 0] for an all-zero series", () => {
    expect(fixedDomain({ min: 0, max: 0 })).toEqual([0, 1]);
  });

  it("fixedDomain always starts at zero", () => {
    expect(fixedDomain({ min: 5, max: 200 })).toEqual([0, 200]);
  });
});

describe("contributorBandData", () => {
  it("fills 0 for a contributor absent from a given snapshot instead of dropping the row", () => {
    const snapshots = [
      snapshot({ position: 0, contributor_shares: [{ name: "Alice", commits: 10, share: 1 }] }),
      snapshot({
        position: 1,
        contributor_shares: [
          { name: "Alice", commits: 5, share: 0.5 },
          { name: "Bob", commits: 5, share: 0.5 },
        ],
      }),
    ];
    const { rows, names } = contributorBandData(snapshots);
    expect(names).toEqual(["Alice", "Bob"]);
    expect(rows[0]).toEqual({ position: 0, Alice: 1, Bob: 0 });
    expect(rows[1]).toEqual({ position: 1, Alice: 0.5, Bob: 0.5 });
  });
});

describe("snapshotDelta", () => {
  it("returns null for the first snapshot", () => {
    expect(snapshotDelta(undefined, snapshot({}))).toBeNull();
  });

  it("computes file/churn/commit/contributor deltas and joins/leaves", () => {
    const previous = snapshot({
      file_count: 10,
      churn_to_date: 100,
      commits_to_date: 5,
      active_contributors: 2,
      contributor_shares: [
        { name: "Alice", commits: 5, share: 1 },
        { name: "Carol", commits: 3, share: 0.5 },
      ],
      churn_ranked_hotspots: [{ path: "a.py", churn_to_date: 40 }],
    });
    const current = snapshot({
      file_count: 12,
      churn_to_date: 250,
      commits_to_date: 9,
      active_contributors: 2,
      contributor_shares: [
        { name: "Alice", commits: 5, share: 0.5 },
        { name: "Dave", commits: 5, share: 0.5 },
      ],
      churn_ranked_hotspots: [{ path: "a.py", churn_to_date: 90 }],
    });

    const delta = snapshotDelta(previous, current);
    expect(delta).not.toBeNull();
    expect(delta!.filesDelta).toBe(2);
    expect(delta!.churnDelta).toBe(150);
    expect(delta!.commitsDelta).toBe(4);
    expect(delta!.contributorsAppeared).toEqual(["Dave"]);
    expect(delta!.contributorsLeft).toEqual(["Carol"]);
    expect(delta!.topChurnMovers).toEqual([{ path: "a.py", churnDelta: 50 }]);
  });
});

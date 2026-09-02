// Pure helpers for the evolution scrubber (session 13, Part F) -- kept out
// of the page component so the fixed-scale contract (Known Hazard #4) is
// independently testable without rendering a real chart.
import type { TimelineBounds, TimelineSnapshotOut } from "../api/types";

/** THE fixed-scale contract: every chart's domain comes from the server-
 * computed `bounds`, NEVER from the currently-displayed snapshot's own
 * data. If a chart derived its domain from the current frame, the axis
 * would rescale every time the scrubber moves and nothing would appear to
 * grow or shrink (Known Hazard #4) -- calling this with the SAME `bounds`
 * on every frame is what guarantees that can't happen. Always starts at 0
 * (every metric here is a non-negative count/total), with a floor of 1 so a
 * flat, all-zero series never collapses a chart's Y axis to [0, 0].
 */
export function fixedDomain(bounds: { min: number; max: number }): [number, number] {
  return [0, Math.max(bounds.max, 1)];
}

export function hotspotBarDomain(bounds: TimelineBounds): [number, number] {
  return fixedDomain(bounds.hotspot_churn);
}

export interface ContributorBandRow {
  position: number;
  [contributorName: string]: number;
}

/** Builds one row per snapshot for a stacked-area "contributor band" chart.
 * The set of contributor names varies across snapshots (people join/leave
 * the trailing 90-day window), so this first takes the UNION of every name
 * that ever appears, then fills 0 for any snapshot where that person wasn't
 * active -- otherwise a stacked area chart would drop a person's whole band
 * to a gap instead of a visible dip to zero. */
export function contributorBandData(snapshots: TimelineSnapshotOut[]): {
  rows: ContributorBandRow[];
  names: string[];
} {
  const nameSet = new Set<string>();
  for (const s of snapshots) {
    for (const c of s.contributor_shares) nameSet.add(c.name);
  }
  const names = Array.from(nameSet).sort((a, b) =>
    a === "Other" ? 1 : b === "Other" ? -1 : a.localeCompare(b),
  );

  const rows = snapshots.map((s) => {
    const row: ContributorBandRow = { position: s.position };
    for (const name of names) row[name] = 0;
    for (const c of s.contributor_shares) row[c.name] = c.share;
    return row;
  });

  return { rows, names };
}

export interface ChurnMover {
  path: string;
  churnDelta: number;
}

export interface SnapshotDelta {
  filesDelta: number;
  churnDelta: number;
  commitsDelta: number;
  contributorsDelta: number;
  topChurnMovers: ChurnMover[];
  contributorsAppeared: string[];
  contributorsLeft: string[];
}

const MAX_CHURN_MOVERS = 5;

/** The "what changed here" panel's data, purely computed from two already-
 * fetched snapshots -- no prose, no re-fetch. Best-effort by construction:
 * both snapshots only carry their own top-N churn-ranked files and top-N
 * active contributors (the backend's own storage caps), so a mover/joiner
 * outside those top-N lists on EITHER side can't be detected -- this is the
 * same "a missed edge is fine, a fabricated one is not" discipline the rest
 * of this product follows, not a bug to fix here. Returns `null` for the
 * first snapshot (nothing to diff against). */
export function snapshotDelta(
  previous: TimelineSnapshotOut | undefined,
  current: TimelineSnapshotOut,
): SnapshotDelta | null {
  if (!previous) return null;

  const previousChurnByPath = new Map(
    previous.churn_ranked_hotspots.map((h) => [h.path, h.churn_to_date]),
  );
  const topChurnMovers = current.churn_ranked_hotspots
    .filter((h) => previousChurnByPath.has(h.path))
    .map((h) => ({
      path: h.path,
      churnDelta: h.churn_to_date - (previousChurnByPath.get(h.path) ?? 0),
    }))
    .filter((m) => m.churnDelta > 0)
    .sort((a, b) => b.churnDelta - a.churnDelta)
    .slice(0, MAX_CHURN_MOVERS);

  const previousNames = new Set(
    previous.contributor_shares.map((c) => c.name).filter((n) => n !== "Other"),
  );
  const currentNames = new Set(
    current.contributor_shares.map((c) => c.name).filter((n) => n !== "Other"),
  );
  const contributorsAppeared = [...currentNames].filter((n) => !previousNames.has(n)).sort();
  const contributorsLeft = [...previousNames].filter((n) => !currentNames.has(n)).sort();

  return {
    filesDelta: current.file_count - previous.file_count,
    churnDelta: current.churn_to_date - previous.churn_to_date,
    commitsDelta: current.commits_to_date - previous.commits_to_date,
    contributorsDelta: current.active_contributors - previous.active_contributors,
    topChurnMovers,
    contributorsAppeared,
    contributorsLeft,
  };
}

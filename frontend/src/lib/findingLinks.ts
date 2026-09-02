import type { FindingCategory, FindingOut } from "../api/types";

export interface FindingDeepLink {
  /** Absolute path (starting with `/repos/<repoId>/...`), ready for
   * react-router's `<Link to>` -- built absolute rather than relative
   * because FindingItem is rendered from `audit/findings`, and a relative
   * `audit/risk?...` there would resolve UNDER `audit/findings`, not as a
   * sibling tab (the same reasoning RepoLayout's own LegacyRedirect
   * documents for why it builds absolute targets). */
  to: string;
  label: string;
}

/** `Hidden dependency: a/b.py <-> c/d.py` -- OverlayEngine's own literal
 * title format (app/engines/overlay.py). Parsed defensively: a title that
 * doesn't match this exact shape just means no pair can be highlighted, not
 * a crash. */
export function parseHiddenDependencyPair(title: string): [string, string] | null {
  const match = /^Hidden dependency: (.+) <-> (.+)$/.exec(title);
  if (!match) return null;
  return [match[1], match[2]];
}

/** `<osv_id>: <package>@<version>` -- SecurityEngine's own literal title
 * format for a vulnerability finding (app/engines/security.py). OSV ids
 * (GHSA-, CVE-, PYSEC- style identifiers) never contain a colon, so
 * splitting on the first one is safe. */
export function parseOsvId(title: string): string | null {
  const idx = title.indexOf(":");
  if (idx <= 0) return null;
  return title.slice(0, idx);
}

/** Resolves a finding to the one page/entity it's "about", per Part A's own
 * examples (a risk finding to that file's risk detail, a hidden-dependency
 * finding to the coupling graph focused on that pair, ...). Every category
 * a finding can carry (FindingCategory) must resolve to something, or
 * `null` when there's genuinely nothing more specific to focus on than the
 * tab itself. Judgement call (RULES.md sec 2.5): the session prompt names
 * three example destinations for three categories: this table extends that
 * same one-category-one-destination shape to the other five categories by
 * the same reasoning (send the viewer to the page that already visualizes
 * that category's evidence), documented per-case below. */
export function findingDeepLink(finding: FindingOut, repoId: string): FindingDeepLink | null {
  const base = `/repos/${repoId}`;
  const path = finding.file_path;
  const category = finding.category as FindingCategory;

  switch (category) {
    case "risk":
      // "a risk finding to that file's risk detail" (Part A, verbatim).
      return path
        ? { to: `${base}/audit/risk?file=${encodeURIComponent(path)}`, label: "View in Risk" }
        : null;

    case "hidden_dependency": {
      // "a coupling finding links to the coupling graph focused on that
      // pair" -- hidden_dependency IS the coupling-derived category (there
      // is no separate "coupling" FindingCategory), so this is that example.
      const params = new URLSearchParams({ hiddenOnly: "1" });
      const pair = parseHiddenDependencyPair(finding.title);
      if (pair) params.set("pair", pair.join("|"));
      return { to: `${base}/audit/coupling?${params.toString()}`, label: "View in Coupling" };
    }

    case "architecture":
      return {
        to: path
          ? `${base}/audit/architecture?file=${encodeURIComponent(path)}`
          : `${base}/audit/architecture`,
        label: "View in Architecture",
      };

    case "knowledge":
      // Knowledge-distribution findings are about who knows a file --
      // People is where that's answered (same cross-page pattern
      // TourPage/GlossaryPage already use for `onboard/people?path=`).
      return path
        ? { to: `${base}/onboard/people?path=${encodeURIComponent(path)}`, label: "View in People" }
        : null;

    case "hygiene":
      return {
        to: path
          ? `${base}/audit/hygiene?file=${encodeURIComponent(path)}`
          : `${base}/audit/hygiene`,
        label: "View in Hygiene",
      };

    case "test_gap": {
      const params = new URLSearchParams({ tab: "tests" });
      if (path) params.set("file", path);
      return { to: `${base}/audit/hygiene?${params.toString()}`, label: "View in Hygiene" };
    }

    case "secret": {
      const params = new URLSearchParams();
      if (finding.evidence_sha) params.set("sha", finding.evidence_sha);
      if (path) params.set("file", path);
      const qs = params.toString();
      return { to: `${base}/audit/security${qs ? `?${qs}` : ""}`, label: "View in Security" };
    }

    case "vulnerability": {
      const osvId = parseOsvId(finding.title);
      return {
        to: osvId
          ? `${base}/audit/security?osv=${encodeURIComponent(osvId)}`
          : `${base}/audit/security`,
        label: "View in Security",
      };
    }

    default:
      return null;
  }
}

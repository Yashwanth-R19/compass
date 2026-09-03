import type { FindingCategory, FindingOut } from "../api/types";

export interface FindingDeepLink {
  /** Absolute path (starting with `/repos/<repoId>/...`), ready for
   * react-router's `<Link to>` -- built absolute rather than relative
   * because FindingItem is rendered from `findings`, and a relative
   * `risk?...` there would resolve UNDER `findings`, not as a sibling
   * surface (the same reasoning RepoLayout's own LegacyRedirect documents
   * for why it builds absolute targets). */
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
 * surface itself. Judgement call (RULES.md sec 2.5), unchanged since this
 * table was first built: extend the "send the viewer to the page that
 * already visualizes that category's evidence" reasoning uniformly across
 * every category.
 *
 * UI rebuild session 4: retargeted for the 8-surface route map (section
 * 4.1). `hygiene`/`test_gap`/`secret`/`vulnerability` used to point at
 * standalone `audit/hygiene`/`audit/security` pages; those pages no longer
 * exist -- their evidence sections now live INSIDE this same `findings`
 * surface (Part A), so those four categories link to
 * `findings?category=<category>&...`, a same-surface deep link that
 * filters the ranked list to that category and scrolls/highlights the
 * matching evidence row, rather than navigating to a different surface. */
export function findingDeepLink(finding: FindingOut, repoId: string): FindingDeepLink | null {
  const base = `/repos/${repoId}`;
  const path = finding.file_path;
  const category = finding.category as FindingCategory;

  switch (category) {
    case "risk":
      // "a risk finding to that file's risk detail" (Part A, verbatim).
      return path
        ? {
            to: `${base}/risk?tab=hotspots&file=${encodeURIComponent(path)}`,
            label: "View in Risk",
          }
        : null;

    case "hidden_dependency": {
      // "a coupling finding links to the coupling graph focused on that
      // pair" -- hidden_dependency IS the coupling-derived category (there
      // is no separate "coupling" FindingCategory), so this is that example.
      const params = new URLSearchParams({ view: "coupling", hiddenOnly: "1" });
      const pair = parseHiddenDependencyPair(finding.title);
      if (pair) params.set("pair", pair.join("|"));
      return { to: `${base}/structure?${params.toString()}`, label: "View in Coupling" };
    }

    case "architecture":
      return {
        to: path
          ? `${base}/structure?view=architecture&file=${encodeURIComponent(path)}`
          : `${base}/structure?view=architecture`,
        label: "View in Architecture",
      };

    case "knowledge":
      // Knowledge-distribution findings are about who knows a file --
      // People is where that's answered (same cross-page pattern
      // Tour/Glossary already use for `people?path=`).
      return path
        ? { to: `${base}/people?path=${encodeURIComponent(path)}`, label: "View in People" }
        : null;

    case "hygiene": {
      const params = new URLSearchParams({ category: "hygiene" });
      if (path) params.set("file", path);
      return { to: `${base}/findings?${params.toString()}`, label: "View in Findings" };
    }

    case "test_gap": {
      const params = new URLSearchParams({ category: "test_gap" });
      if (path) params.set("file", path);
      return { to: `${base}/findings?${params.toString()}`, label: "View in Findings" };
    }

    case "secret": {
      const params = new URLSearchParams({ category: "secret" });
      if (finding.evidence_sha) params.set("sha", finding.evidence_sha);
      if (path) params.set("file", path);
      return { to: `${base}/findings?${params.toString()}`, label: "View in Findings" };
    }

    case "vulnerability": {
      const params = new URLSearchParams({ category: "vulnerability" });
      const osvId = parseOsvId(finding.title);
      if (osvId) params.set("osv", osvId);
      return { to: `${base}/findings?${params.toString()}`, label: "View in Findings" };
    }

    default:
      return null;
  }
}

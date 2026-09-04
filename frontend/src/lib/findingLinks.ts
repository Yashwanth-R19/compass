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
 * title format (app/engines/overlay.py). `ModuleCouplingEngine`'s own
 * subsystem-grain hidden-dependency findings (app/engines/module_coupling.py)
 * use the identical shape with a trailing " (subsystems)" marker, which this
 * strips -- so callers get the same clean `[a, b]` pair either way. Parsed
 * defensively: a title that doesn't match this exact shape just means no
 * pair can be highlighted, not a crash. */
export function parseHiddenDependencyPair(title: string): [string, string] | null {
  const match = /^Hidden dependency: (.+) <-> (.+?)(?: \(subsystems\))?$/.exec(title);
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

/** Resolves a finding to the one page/entity it's "about", per section
 * 4.4's own examples (a risk finding to that file's risk detail, a
 * hidden-dependency finding to the coupling list focused on that pair,
 * ...). Every category a finding can carry (FindingCategory) must resolve
 * to something, or `null` when there's genuinely nothing more specific to
 * focus on than the surface itself. Judgement call (RULES.md sec 2.5),
 * unchanged since this table was first built: extend the "send the viewer
 * to the page that already visualizes that category's evidence" reasoning
 * uniformly across every category.
 *
 * Rebuild (section 4.6): retargeted for the five-surface route map. `risk`
 * findings now live at `findings?view=risk` (Risk is no longer its own
 * surface); `hidden_dependency`/`architecture` now live at
 * `explore?view=structure` (Structure is no longer its own surface, folded
 * into Explore); `knowledge` now lives at `guide?view=people` (People is no
 * longer its own surface, folded into Guide). `test_gap` no longer exists
 * as a category at all -- test-gap analysis was cut entirely (D7). */
export function findingDeepLink(finding: FindingOut, repoId: string): FindingDeepLink | null {
  const base = `/repos/${repoId}`;
  const path = finding.file_path;
  const category = finding.category as FindingCategory;

  switch (category) {
    case "risk":
      // "a risk finding to that file's risk detail" -- Risk is a view
      // inside Findings now, not its own surface.
      return path
        ? {
            to: `${base}/findings?view=risk&file=${encodeURIComponent(path)}`,
            label: "View in Risk",
          }
        : null;

    case "hidden_dependency": {
      // "a coupling finding links to the coupling list focused on that
      // pair" -- hidden_dependency IS the coupling-derived category (there
      // is no separate "coupling" FindingCategory), so this is that example.
      const params = new URLSearchParams({ view: "structure", panel: "coupling", hiddenOnly: "1" });
      const pair = parseHiddenDependencyPair(finding.title);
      if (pair) params.set("pair", pair.join("|"));
      return { to: `${base}/explore?${params.toString()}`, label: "View in Coupling" };
    }

    case "architecture":
      return {
        to: path
          ? `${base}/explore?view=structure&panel=architecture&file=${encodeURIComponent(path)}`
          : `${base}/explore?view=structure&panel=architecture`,
        label: "View in Structure",
      };

    case "knowledge":
      // Knowledge-distribution findings are about who knows a file --
      // Guide's People view is where that's answered (same cross-page
      // pattern the Tour/Glossary views already use for `guide?view=people`).
      return path
        ? {
            to: `${base}/guide?view=people&path=${encodeURIComponent(path)}`,
            label: "View in People",
          }
        : null;

    case "hygiene": {
      const params = new URLSearchParams({ category: "hygiene" });
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

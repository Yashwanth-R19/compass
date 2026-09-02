import { useOutletContext } from "react-router-dom";
import { useNarrative } from "../api/hooks";
import { useNarrativeEnabled } from "../lib/narrativePref";
import type { NarrativeSurface } from "../api/types";
import type { RepoOutletContext } from "../pages/RepoLayout";

/** Session 12, Part E: the ONE narrative component, used on exactly three
 * surfaces (the passport, a risk file's detail, and the security summary --
 * Known Hazard #8: never add a fourth). Renders directly beneath the
 * metrics it describes -- callers place it at the end of that section's
 * markup, never above it and never on its own page.
 *
 * Controlled by the single global header toggle (`lib/narrativePref.ts`):
 * while off, this renders nothing and makes no request at all (rule 3 --
 * every page must be fully usable, and cost nothing in quota, with
 * narrative off). While on, it fetches lazily and renders one of three
 * states: collapsed (still loading -- Known Hazard #6, no layout jump for
 * a spinner), the quiet unavailable line, or the labelled, visually
 * distinct generated-content box.
 */
export function NarrativeBlock({
  surface,
  subject,
}: {
  surface: NarrativeSurface;
  subject?: string;
}) {
  const enabled = useNarrativeEnabled();
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const query = useNarrative(repo.id, surface, subject, share);

  if (!enabled) return null;

  // Known Hazard #6: collapse to nothing while in flight rather than
  // reserving a guessed height or showing a spinner that pops the layout
  // once real content (or the unavailable line) arrives.
  if (query.isPending || query.isFetching) return null;

  if (query.isError || !query.data?.available) {
    return (
      <p className="mt-2 text-xs text-ink-faint">
        Narrative unavailable — the computed data above is unaffected.
      </p>
    );
  }

  const { content, provider, model } = query.data;

  return (
    <div className="mt-2 rounded-lg border border-violet-100 bg-violet-50/70 px-3 py-2.5 dark:border-violet-500/20 dark:bg-violet-500/10">
      <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-violet-500 dark:text-violet-400">
        Generated phrasing of the metrics above — the numbers are computed
        {provider && model ? ` · ${provider}/${model}` : ""}
      </p>
      <p className="text-sm text-violet-950 dark:text-violet-100">{content}</p>
    </div>
  );
}

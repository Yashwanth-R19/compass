/** The non-graph counterpart to GraphCapNotice -- "showing N of M" for any
 * capped list (findings, blast-radius affected files, tour stops), so a cap
 * is never silently applied (CLAUDE.md's anti-alert-fatigue rule: an honest
 * total must always be shown alongside a cap). Renders nothing if the cap
 * never actually engaged. */
export function PartialResultNotice({
  shown,
  total,
  itemLabel = "items",
  capped = false,
}: {
  shown: number;
  total: number;
  itemLabel?: string;
  /** True when the underlying computation stopped at an internal safety
   * limit (a traversal depth or node-count cap, e.g. blast radius's
   * `depth_capped`/`node_cap_engaged`) rather than because a real, larger
   * total is known -- in that case the true total isn't knowable, so the
   * notice says the result may be incomplete instead of claiming an exact
   * "showing N of M" against a total that was never computed. */
  capped?: boolean;
}) {
  if (!capped && shown >= total) return null;

  return (
    <p className="mb-2 rounded-md bg-amber-50 px-3 py-1.5 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
      {capped
        ? `Showing the first ${shown} ${itemLabel} — this may not be the complete result (an internal search limit was reached).`
        : `Showing ${shown} of ${total} ${itemLabel}.`}
    </p>
  );
}

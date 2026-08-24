/** The non-graph counterpart to GraphCapNotice -- "showing N of M" for any
 * capped list (findings, blast-radius affected files, tour stops), so a cap
 * is never silently applied (CLAUDE.md's anti-alert-fatigue rule: an honest
 * total must always be shown alongside a cap). Renders nothing if the cap
 * never actually engaged. */
export function PartialResultNotice({
  shown,
  total,
  itemLabel = "items",
}: {
  shown: number;
  total: number;
  itemLabel?: string;
}) {
  if (shown >= total) return null;

  return (
    <p className="mb-2 rounded-md bg-amber-50 px-3 py-1.5 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
      Showing {shown} of {total} {itemLabel}.
    </p>
  );
}

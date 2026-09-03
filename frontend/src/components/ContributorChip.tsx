/** A contributor identity, rendered as neutral text -- never a leaderboard
 * position, medal, or trophy (knowledge-distribution framing only, never
 * performance). Only ever takes a name and a couple of boolean flags --
 * never an email, masked or otherwise; there is no prop to accidentally
 * render one through. */
export function ContributorChip({
  name,
  isStale,
  isBot,
}: {
  name: string;
  isStale?: boolean;
  isBot?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-xs border border-border bg-bg-inset px-2.5 py-1 text-xs font-medium text-text">
      {name}
      {isBot ? <span className="text-text-muted">bot</span> : null}
      {isStale ? (
        <span
          className="text-warning"
          title="No recent activity relative to this repository's own history"
        >
          stale
        </span>
      ) : null}
    </span>
  );
}

/** A contributor identity, rendered as neutral text -- never a leaderboard
 * position, medal, or trophy (plan/RULES.md sec 11.3: knowledge
 * distribution framing only, never performance). Only ever takes a name and
 * a couple of boolean flags -- never an email, masked or otherwise; a
 * contributor's email is not this component's concern at all, so there is
 * no prop to accidentally render one through. */
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
    <span className="inline-flex items-center gap-1.5 border border-border bg-surface-2 px-2.5 py-1 text-xs font-medium text-ink">
      {name}
      {isBot ? <span className="text-ink-faint">bot</span> : null}
      {isStale ? (
        <span
          className="text-conf-low"
          title="No recent activity relative to this repository's own history"
        >
          stale
        </span>
      ) : null}
    </span>
  );
}

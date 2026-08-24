/** A small pill naming a subsystem -- used anywhere a file or finding is
 * tagged with the subsystem it belongs to (tour stops, blast radius,
 * passport shape). Renders nothing for a file with no subsystem (a real,
 * expected case -- e.g. the "subsystems" stage hasn't finished yet, or the
 * file landed in no community), rather than showing an empty badge. */
export function SubsystemBadge({ label }: { label: string | null | undefined }) {
  if (!label) return null;

  return (
    <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400">
      {label}
    </span>
  );
}

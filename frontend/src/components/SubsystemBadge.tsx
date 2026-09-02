import { colorForSubsystem } from "../lib/subsystemColors";

/** A small pill naming a subsystem -- used anywhere a file or finding is
 * tagged with the subsystem it belongs to (tour stops, blast radius,
 * passport shape). Renders nothing for a file with no subsystem (a real,
 * expected case -- e.g. the "subsystems" stage hasn't finished yet, or the
 * file landed in no community), rather than showing an empty badge.
 *
 * Session 15: coloured via the SAME categorical palette
 * (lib/subsystemColors.ts) the graph/treemap/city use, via a small dot
 * rather than a full-strength fill (Chip's own `dot` mode) -- previously
 * every subsystem badge was a fixed indigo regardless of which subsystem,
 * which meant this was the one place in the app where "billing" and "core"
 * looked identical while every other view coloured them apart. */
export function SubsystemBadge({ label }: { label: string | null | undefined }) {
  if (!label) return null;

  return (
    <span className="inline-flex items-center gap-1.5 border border-border px-2 py-0.5 text-xs font-medium text-ink">
      <span
        aria-hidden="true"
        className="h-2 w-2 shrink-0"
        style={{ backgroundColor: colorForSubsystem(label) }}
      />
      {label}
    </span>
  );
}

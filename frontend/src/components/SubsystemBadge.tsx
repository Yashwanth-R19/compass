import { colorForKey } from "../lib/palette";

/** A small pill naming a subsystem -- used anywhere a file or finding is
 * tagged with the subsystem it belongs to. Renders nothing for a file with
 * no subsystem (a real, expected case), rather than showing an empty
 * badge. Coloured via the SAME categorical palette (lib/palette.ts) every
 * other subsystem-coloured view uses, via a small dot rather than a
 * full-strength fill. */
export function SubsystemBadge({ label }: { label: string | null | undefined }) {
  if (!label) return null;

  return (
    <span className="inline-flex items-center gap-1.5 rounded-xs border border-border px-2 py-0.5 text-xs font-medium text-text">
      <span
        aria-hidden="true"
        className="h-2 w-2 shrink-0"
        style={{ backgroundColor: colorForKey(label) }}
      />
      {label}
    </span>
  );
}

/** A filled, coloured tag -- unlike Badge (an outline label for static
 * metadata), Chip carries a solid background and is used where the colour
 * itself IS the primary signal (a subsystem name, a contributor identity).
 * `dot`, when given, renders a small square swatch before the label instead
 * of tinting the whole chip -- useful when the colour comes from the
 * high-cardinality categorical palette (subsystemColors.ts) and a
 * full-strength fill across 12 hues would compete with everything else on
 * the page; a solid `color` fill (no `dot`) is for the small, fixed set of
 * semantic tones (severity, confidence). */
export function Chip({
  label,
  color,
  dot,
  className = "",
}: {
  label: string;
  color: string;
  dot?: boolean;
  className?: string;
}) {
  if (dot) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 border border-border px-1.5 py-0.5 text-xs font-medium text-ink ${className}`}
      >
        <span aria-hidden="true" className="h-2 w-2 shrink-0" style={{ backgroundColor: color }} />
        {label}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-xs font-medium text-white ${className}`}
      style={{ backgroundColor: color }}
    >
      {label}
    </span>
  );
}

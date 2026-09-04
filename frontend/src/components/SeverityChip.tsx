import type { Severity } from "../api/types";
import { SEVERITY_CLASSES, SEVERITY_LABEL } from "../lib/format";

/** The one severity pill, used anywhere a `Severity` needs a chip --
 * findings, cycles, layering violations. Reads only from
 * `SEVERITY_CLASSES` (`lib/format.ts`) — a soft-tinted fill plus solid
 * text, mapping high/med/low onto danger/warning/success. Always paired
 * with the text label so a colour-deficient viewer never depends on hue
 * alone. */
export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center rounded-xs px-1.5 py-0.5 text-xs font-medium ${SEVERITY_CLASSES[severity]}`}
    >
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

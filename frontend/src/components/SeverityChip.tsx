import type { Severity } from "../api/types";
import { SEVERITY_CLASSES, SEVERITY_LABEL } from "../lib/format";

/** The one severity pill, used anywhere a `Severity` needs a chip -- findings,
 * cycles, layering violations. Extracted from FindingItem (session 11, Part
 * G) so pages outside the findings list (Architecture's cycle list already
 * had its own copy) can share exactly one rendering instead of each hand-
 * rolling the same ring/background classes. */
export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${SEVERITY_CLASSES[severity]}`}
    >
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

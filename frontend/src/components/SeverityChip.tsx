import type { Severity } from "../api/types";
import { SEVERITY_CLASSES, SEVERITY_LABEL } from "../lib/format";

/** The one severity pill, used anywhere a `Severity` needs a chip -- findings,
 * cycles, layering violations. Extracted from FindingItem (session 11, Part
 * G) so pages outside the findings list (Architecture's cycle list already
 * had its own copy) can share exactly one rendering instead of each hand-
 * rolling the same classes. Session 15: a hairline-bordered chip (Badge's
 * shape), not a filled pill -- severity is the one place colour matters
 * most, so it gets a border strong enough to read even for a
 * colour-deficient viewer, backed by the text label either way. */
export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center border px-1.5 py-0.5 text-xs font-medium ${SEVERITY_CLASSES[severity]}`}
    >
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

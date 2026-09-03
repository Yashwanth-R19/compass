const DEFAULT_HEURISTIC_MESSAGE =
  "Heuristic score — not yet corpus-calibrated. Weights are documented, literature-informed defaults, not a statistically fitted model.";

const CORPUS_MESSAGE =
  "Calibrated against a curated corpus of real repositories (see the Benchmark tab) — percentile calibration, not a trained model.";

/** The one "how was this score calibrated" label, used on every
 * heuristic/calibrated score in the app (risk, health, onboarding
 * difficulty, glossary scoring, hygiene instability). Centralized so a
 * calibration change flips the wording in one place.
 *
 * `calibration` mirrors the API response's own `calibration` field
 * ("heuristic" | "corpus"). A hairline left border in the matching
 * semantic tone -- warning for heuristic (not yet calibrated), success for
 * corpus (the positive, "calibrated against real data" state) -- instead
 * of a filled tinted box, consistent with the token system's "border
 * carries the signal, fill stays neutral" convention. */
export function HeuristicNote({
  message = DEFAULT_HEURISTIC_MESSAGE,
  calibration,
  className = "",
}: {
  message?: string;
  calibration?: string;
  className?: string;
}) {
  const isCorpus = calibration === "corpus";
  return (
    <p
      className={`border-l-2 py-1.5 pl-3 text-xs text-text-muted ${
        isCorpus ? "border-success" : "border-warning"
      } ${className}`}
    >
      {isCorpus ? CORPUS_MESSAGE : message}
    </p>
  );
}

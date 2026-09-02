const DEFAULT_HEURISTIC_MESSAGE =
  "Heuristic score — not yet corpus-calibrated. Weights are documented, literature-informed defaults, not a statistically fitted model.";

const CORPUS_MESSAGE =
  "Calibrated against a curated corpus of real repositories (see the Benchmark tab) — percentile calibration, not a trained model.";

/** The one "how was this score calibrated" label, used on every
 * heuristic/calibrated score in the app (risk, health, onboarding
 * difficulty, glossary scoring, hygiene instability). Centralized so a
 * calibration change flips the wording in one place instead of hunting
 * down every inline paragraph that used to say this (RULES.md sec 3 /
 * CLAUDE.md's calibration-labeling convention).
 *
 * Session 14, Part C.5: `calibration` mirrors the API response's own
 * `calibration` field ("heuristic" | "corpus"). Session 15: a hairline
 * left border in the matching semantic colour (amber-family for
 * heuristic, the "positive" green-family for corpus) instead of a filled
 * tinted box -- consistent with the rest of the token system's "border
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
      className={`border-l-2 py-1.5 pl-3 text-xs text-ink-muted ${
        isCorpus ? "border-conf-high" : "border-conf-low"
      } ${className}`}
    >
      {isCorpus ? CORPUS_MESSAGE : message}
    </p>
  );
}

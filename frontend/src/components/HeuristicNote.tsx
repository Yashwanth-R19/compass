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
 * `calibration` field ("heuristic" | "corpus", derived server-side from
 * `COMPASS_BASELINE_PROVIDER` at runtime -- never guessed at client-side).
 * When it's "corpus", the corpus-calibrated message wins regardless of a
 * caller-supplied `message` -- a caller's custom `message` is for
 * elaborating on the HEURISTIC case (e.g. RiskPage's formula explainer),
 * not for overriding an honestly-corpus-calibrated score into looking
 * uncalibrated. Omitting `calibration` entirely keeps every pre-session-14
 * call site's behavior unchanged. */
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
      className={`rounded-md px-3 py-2 text-xs ${
        isCorpus
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400"
          : "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400"
      } ${className}`}
    >
      {isCorpus ? CORPUS_MESSAGE : message}
    </p>
  );
}

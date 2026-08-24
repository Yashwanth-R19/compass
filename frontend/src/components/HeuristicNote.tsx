const DEFAULT_MESSAGE =
  "Heuristic score — not yet corpus-calibrated. Weights are documented, literature-informed defaults, not a statistically fitted model.";

/** The one "this number is heuristic, not corpus-calibrated" label, used on
 * every heuristic score in the app (risk, health, onboarding difficulty,
 * glossary scoring, hygiene instability). Centralized so session 14's
 * corpus-calibration work can flip the wording in one place instead of
 * hunting down every inline paragraph that used to say this (RULES.md sec 3
 * / CLAUDE.md's calibration-labeling convention). */
export function HeuristicNote({
  message = DEFAULT_MESSAGE,
  className = "",
}: {
  message?: string;
  className?: string;
}) {
  return (
    <p
      className={`rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-400 ${className}`}
    >
      {message}
    </p>
  );
}

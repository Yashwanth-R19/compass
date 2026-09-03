/**
 * Structured content for /methods (UI rebuild session 2, Part E) — section
 * prose, the limitations list, the "what Compass deliberately does not do"
 * list, and the corpus description. Every NUMBER on that page comes from
 * `GET /meta/formulas` or `GET /repos/{id}/benchmark`'s `corpus_note` at
 * request time — never from this file, which holds only prose.
 */

export const METHODS_INTRO =
  'This page is Compass\'s answer to "does this actually work?" — every formula it computes, whether that formula is a fixed product decision, a documented guess, or lifted from a published paper, how its normalization is calibrated, and where it honestly falls short.';

export interface MethodsSection {
  id: string;
  eyebrow: string;
  title: string;
  body: string;
}

export const METHODS_SECTIONS: MethodsSection[] = [
  {
    id: "scores",
    eyebrow: "Section 1",
    title: "How each score is defined",
    body: "Every score Compass computes carries one of three honesty labels. Locked means the formula and its weights are a fixed product decision, identical on every repository, never tuned to make a particular result look better. Heuristic means Compass chose the inputs and a documented starting set of weights, and says so plainly rather than presenting a guess as a proven model. Cited means the formula is taken directly from published research and implemented as specified, not adjusted.",
  },
  {
    id: "calibration",
    eyebrow: "Section 2",
    title: "How normalisation is calibrated",
    body: 'A raw value like "640 lines of weighted churn" means nothing on its own — every heuristic score normalizes its inputs before weighting them. Two providers exist. The heuristic provider scales each value against this repository\'s own minimum and maximum, so it can only ever say "high relative to this codebase". The corpus provider instead scales against percentile breakpoints computed from a small, curated set of real repositories in the same language and size bucket, so it can say "high relative to similar projects" — a materially stronger claim, made only where the corpus has enough repositories behind it to back it up.',
  },
  {
    id: "also-measured",
    eyebrow: "Section 3",
    title: "What is measured but deliberately not scored",
    body: "Several signals Compass computes and displays never feed a locked or heuristic formula at all — they're shown as supporting evidence next to a score, not folded into it. Keeping them separate is deliberate: collapsing everything into one number would hide exactly the kind of nuance (a file that's risky but low-confidence, a coupling pair with unusually few shared revisions) a reader needs to judge how much to trust the headline figure.",
  },
  {
    id: "limitations",
    eyebrow: "Section 4",
    title: "Limitations",
    body: "Including the ones that look bad. A limitations list with nothing inconvenient in it is not a limitations list.",
  },
  {
    id: "reproducibility",
    eyebrow: "Section 5",
    title: "Reproducibility",
    body: "The same repository at the same commit, analysed twice, produces byte-identical output — this is a core product claim, not an incidental property. Here is what that guarantee covers, and what legitimately changes the numbers.",
  },
];

export const CORPUS_DESCRIPTION =
  "The corpus baseline is percentile breakpoints — p10/p25/p50/p75/p90 — per (metric, language, size bucket), computed from roughly thirty curated, real repositories. It is not a trained classifier, not defect labelling, and not cross-project transfer learning; those were the original plan and were cut in favor of the useful fraction, at a fraction of the cost. The repository list is hand-curated and checked into the repository so a reader can see exactly which projects a percentile is derived from, along with the selection checklist applied to each one (a minimum commit and contributor count, a real test directory, a permissive license, a recent last commit, and a file-count ceiling to keep build time bounded).";

export const CORPUS_REPO_LIST_PATH = "backend/app/baseline/corpus_repos.yaml";

/** The project's own real repository (verified via `git remote -v`, not
 * guessed) -- linked from the Methods page so a reader can see the exact
 * curated repository list and its selection checklist. */
export const CORPUS_REPO_LIST_URL =
  "https://github.com/Yashwanth-R19/compass/blob/main/backend/app/baseline/corpus_repos.yaml";

export const CELL_SIZE_GATE_NOTE =
  "A (metric, language, size bucket) cell backed by fewer than five contributing corpus repositories is not trusted as-is — the lookup widens first to any size bucket in the same language, then to any language at all, and only falls back to the purely per-repository heuristic when even the widest cell is still under-powered. Every benchmark percentile shows the repository count actually behind it, and a visible badge when the comparison had to widen.";

export const LIMITATIONS: string[] = [
  "File renames are not tracked as continuity — a rename is recorded as the old path being deleted and the new path being added, which can make a moved file's history look shorter than it really is.",
  "Java same-package references are not inferred — only explicit `import` statements are modeled. Two classes in the same package that reference each other without an import are invisible to change-coupling's structural half (though genuine change-coupling, which doesn't depend on imports at all, would still catch them).",
  "Complexity is measured on the current checked-out tree only, never at a historical revision — this is why the evolution timeline's file ranking is explicitly called churn-ranked hotspots, never risk over time: applying the risk formula historically would need a complexity measurement Compass never took.",
  "The hard clone timeout is enforced on this project's actual Linux deployment targets, not on Windows, where the underlying library raises instead of enforcing it — a documented gap, not a silent one.",
  "The domain glossary extracts a repository's own vocabulary, not definitions — Compass shows that a word is one the codebase revolves around, and the handful of files that would tell a reader what it means, not what the word itself means.",
  "Test-gap analysis measures test maintenance — whether a mapped test keeps changing alongside its source file — never test coverage or test quality.",
  "Unreferenced-file detection is not dead-code detection — a file with no detected structural edge can still be reached through a dynamic import, reflection, framework auto-discovery, or a build-config reference Compass doesn't parse.",
  "The heuristic scores (health, onboarding difficulty, commit-hygiene instability, glossary term score) are documented, adjustable starting points, not statistically fitted models — treat their exact weights as a considered opinion, not a proven constant.",
  "The corpus baseline currently covers roughly thirty repositories. A percentile computed from an under-represented cell widens to a coarser comparison rather than being trusted as-is, and is labelled as such wherever it appears.",
  'A commit\'s author is modeled as a single identity in this schema — co-authorship is not represented, so "who authored the first commit touching this file" is always well-defined but never reflects more than one person.',
];

export interface ReproducibilityChange {
  cause: string;
  effect: string;
}

export const REPRODUCIBILITY_GUARANTEE =
  "Re-analysing the same repository at the same commit sha, with the same engine version and the same baseline provider, produces byte-identical Insight output — the same coupling pairs, the same risk scores, the same subsystem partition, down to the same tie-break order.";

export const REPRODUCIBILITY_CHANGES: ReproducibilityChange[] = [
  {
    cause: "A new commit lands on the repository",
    effect:
      "The next analysis re-mines the full Facts layer from scratch and every Insight computation runs fresh against it — numbers legitimately move.",
  },
  {
    cause: "A formula's engine version is bumped",
    effect:
      "Only when a measurement genuinely changes, for example switching from raw churn to recency-weighted churn — comparing runs across that boundary is legitimate, but is flagged, since some movement may reflect the measurement change rather than the code.",
  },
  {
    cause: "The configured baseline provider changes",
    effect:
      "Switching between the heuristic and corpus normalizers changes every heuristic score's calibration, not the underlying raw values it was computed from.",
  },
];

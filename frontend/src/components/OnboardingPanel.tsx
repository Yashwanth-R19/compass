import { X } from "lucide-react";
import { dismissOnboardingPanel } from "../lib/onboardingPanelPref";

/**
 * The landing page's "how Compass works" copy (Part I) — kept as ONE
 * exported constant specifically so session 2's move into
 * `src/content/explainability.ts` is mechanical (a straight relocation,
 * not a rewrite). Written fresh for Compass's own domain; nothing here is
 * paraphrased from any reference product's copy.
 */
export const ONBOARDING_PANEL_CONTENT = {
  intro:
    "Compass turns a repository's own commit history into evidence — every number below is computed from real git data, the same way every time, never inferred by a model skimming the current tree.",
  steps: [
    {
      title: "Mine the history",
      body: "Compass clones the repository and streams its full commit log — every changeset, every author, every file touched — without guessing at anything a language model would have to hallucinate from a snapshot.",
    },
    {
      title: "Compute the facts",
      body: "Commits, files, and structural imports are parsed into a plain, deterministic dataset: who touched what, when, and what depends on what.",
    },
    {
      title: "Derive the insight",
      body: "Locked formulas run over those facts — change-coupling, calibrated risk, subsystem structure, knowledge distribution — and the exact formula behind every score is one click away.",
    },
  ],
  footnote:
    "Everything on the page you're about to see — the showcase cards, and any repository you submit — is the output of exactly this pipeline, not a summary written after the fact.",
} as const;

/** Dismissible, shown on first visit only, reopenable from the header
 * (`AppShell`'s "How Compass works" button, via
 * `lib/onboardingPanelPref.ts`). Rendered by `HomePage` when
 * `useOnboardingPanelOpen()` is true. */
export function OnboardingPanel() {
  const { intro, steps, footnote } = ONBOARDING_PANEL_CONTENT;

  return (
    <section
      aria-label="How Compass works"
      className="relative rounded-lg border border-border bg-bg-elevated p-6"
    >
      <button
        type="button"
        onClick={dismissOnboardingPanel}
        aria-label="Dismiss"
        className="absolute right-4 top-4 text-text-muted hover:text-text"
      >
        <X size={16} aria-hidden="true" />
      </button>

      <p className="max-w-2xl pr-8 text-sm text-text-muted">{intro}</p>

      <ol className="mt-5 flex flex-col gap-4 sm:flex-row sm:gap-6">
        {steps.map((step, index) => (
          <li key={step.title} className="flex flex-1 gap-3">
            <span className="font-display text-2xl leading-none text-accent">{index + 1}</span>
            <span>
              <strong className="block font-display text-base text-text-heading">
                {step.title}
              </strong>
              <span className="mt-1 block text-sm text-text-muted">{step.body}</span>
            </span>
          </li>
        ))}
      </ol>

      <p className="mt-5 border-t border-border pt-4 text-xs text-text-muted">{footnote}</p>
    </section>
  );
}

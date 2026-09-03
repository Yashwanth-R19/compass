import { X } from "lucide-react";
import { dismissOnboardingPanel } from "../lib/onboardingPanelPref";
import { ONBOARDING_FOOTNOTE, ONBOARDING_INTRO, ONBOARDING_STEPS } from "../content/explainability";

/** Dismissible, shown on first visit only, reopenable from the header
 * (`AppShell`'s "How Compass works" button, via
 * `lib/onboardingPanelPref.ts`). Rendered by `HomePage` when
 * `useOnboardingPanelOpen()` is true.
 *
 * Content lives in `src/content/explainability.ts` (session 2, Part C4) --
 * this component was session 1's original home for it, kept as one
 * exported constant specifically so this move would be mechanical; it now
 * just renders. */
export function OnboardingPanel() {
  const intro = ONBOARDING_INTRO;
  const steps = ONBOARDING_STEPS;
  const footnote = ONBOARDING_FOOTNOTE;

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

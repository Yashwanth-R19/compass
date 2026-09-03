import { HelpCircle } from "lucide-react";
import { Tooltip } from "./Tooltip";

/**
 * A small `HelpCircle` icon button opening a Radix tooltip — the single
 * mechanism by which section 5's tooltip copy reaches the screen. Every
 * metric name in the app uses this from session 2 onward (once
 * `src/content/explainability.ts` exists to source `text` from); this
 * session just builds the primitive.
 *
 * `label` is the accessible name (announced by a screen reader on focus,
 * e.g. "What is risk_score?"); `text` is the explanation itself, rendered
 * inside the tooltip. Keyboard-focusable (a real `<button>`, tabbable) and
 * dismissible with Escape — both come from Radix's `Tooltip` underneath,
 * not hand-rolled.
 */
export function InfoTooltip({ label, text }: { label: string; text: string }) {
  return (
    <Tooltip content={text}>
      <button
        type="button"
        aria-label={label}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full text-text-muted transition-colors hover:text-accent"
      >
        <HelpCircle size={13} aria-hidden="true" />
      </button>
    </Tooltip>
  );
}

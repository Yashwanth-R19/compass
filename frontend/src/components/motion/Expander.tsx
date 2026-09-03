import { useId, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/**
 * An accessible open/close disclosure using the pure-CSS
 * `grid-template-rows: 0fr -> 1fr` technique (rule M4) -- no JS height
 * measurement, so it never fights layout thrash and respects
 * `prefers-reduced-motion` for free via index.css's global transition
 * override. session 2's `ScoreExplainer` is built directly on this.
 *
 * Works controlled (`open`/`onOpenChange` both given) or uncontrolled (an
 * internal `useState`, initialised from `defaultOpen`) -- a caller that
 * only wants "click to expand" behaviour never needs to manage state
 * itself.
 */
export function Expander({
  trigger,
  children,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  className = "",
}: {
  trigger: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : uncontrolledOpen;
  const panelId = useId();

  function toggle() {
    const next = !open;
    if (!isControlled) setUncontrolledOpen(next);
    onOpenChange?.(next);
  }

  return (
    <div className={className}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={panelId}
        className="inline-flex items-center gap-1.5 text-left text-sm font-medium text-text transition-colors hover:text-accent"
      >
        <ChevronDown
          size={14}
          aria-hidden="true"
          className={`shrink-0 transition-transform duration-[var(--dur-fast)] ${open ? "rotate-180" : ""}`}
        />
        {trigger}
      </button>
      <div
        id={panelId}
        aria-hidden={!open}
        // `inert` (not just `aria-hidden`) when collapsed -- content here
        // never unmounts (the 0fr/1fr grid technique keeps it in the DOM so
        // the height transition has something to animate), so a collapsed
        // panel can still contain a real focusable element (an InfoTooltip
        // button inside a collapsed ScoreExplainer, in practice). Found via
        // this session's own accessibility sweep (`aria-hidden-focus`,
        // axe-core): `aria-hidden="true"` alone marks a subtree hidden from
        // assistive tech WITHOUT removing it from the tab order, which is
        // exactly the violation. `inert` does both atomically and is the
        // correct primitive for "not just hidden, genuinely inactive."
        inert={!open}
        className="grid transition-[grid-template-rows] duration-[var(--dur-base)] ease-[var(--ease-out)]"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">{children}</div>
      </div>
    </div>
  );
}

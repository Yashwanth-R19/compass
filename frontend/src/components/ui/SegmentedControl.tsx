import { Tabs as RadixTabs } from "radix-ui";

/**
 * The in-page view/tab switcher used by every merged surface's `?view=`/
 * `?tab=` query-param switch (Part J's interim scaffolding, and every
 * rebuilt surface from session 3 onward) — e.g. Structure's
 * architecture/coupling/impact views, Risk's hotspots/benchmark tabs.
 * Radix `Tabs` underneath for keyboard navigation (arrow keys move focus
 * between segments) and correct ARIA roles, with the active segment marked
 * by the accent underline (rule V4: "selected" chrome is one of the few
 * places the accent is allowed).
 *
 * This is for SAME-PAGE view switching only, never a substitute for the
 * repository tab bar (`RepoLayout`'s Overview/Map/Tour/... nav), which is
 * real routes and stays `NavLink`s — converting that to Radix tab panels
 * would break deep linking, the back button, and every existing share
 * link.
 */
export function SegmentedControl({
  value,
  onValueChange,
  options,
  "aria-label": ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: string }[];
  "aria-label": string;
}) {
  return (
    <RadixTabs.Root value={value} onValueChange={onValueChange}>
      <RadixTabs.List
        aria-label={ariaLabel}
        className="inline-flex items-center gap-1 rounded-md border border-border bg-bg-inset p-1"
      >
        {options.map((opt) => (
          <RadixTabs.Trigger
            key={opt.value}
            value={opt.value}
            className="cp-label rounded-sm px-2.5 py-1 transition-colors data-[state=active]:bg-bg-elevated data-[state=active]:text-accent data-[state=inactive]:hover:text-text"
          >
            {opt.label}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {/* Radix's own Tabs.Trigger always sets aria-controls pointing at a
          same-value Tabs.Content -- this component is a pure view SWITCH
          (the actual content it switches lives elsewhere in the caller's
          tree, not inside a Tabs.Content), so without this, every trigger's
          aria-controls referenced an id that never existed anywhere in the
          DOM (an invalid ARIA attribute value, caught by this session's own
          accessibility sweep). A real, empty Content per option gives the
          active trigger's aria-controls a genuine target; Radix itself
          keeps only the active one mounted. */}
      {options.map((opt) => (
        <RadixTabs.Content key={opt.value} value={opt.value} />
      ))}
    </RadixTabs.Root>
  );
}

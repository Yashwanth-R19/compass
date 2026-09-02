import { Tabs as RadixTabs } from "radix-ui";
import type { ReactNode } from "react";

/** A same-page, panel-switching tab set (Radix `Tabs`, full keyboard
 * support -- arrow keys move focus between triggers, the active panel is
 * announced correctly).
 *
 * NOT what RepoLayout's Onboard/Audit tab bar uses -- those are real ROUTES
 * (`NavLink`s under react-router, each with its own deep-linkable URL), and
 * converting route navigation into this component would silently break
 * every existing bookmark/share-link/back-button expectation (a structural
 * change this session's refit constraint forbids). Reach for this only when
 * switching a "tab" does NOT change the URL -- e.g. a same-page granularity
 * or view switch that has no reason to be its own route. */
export function Tabs({
  value,
  onValueChange,
  tabs,
  children,
}: {
  value: string;
  onValueChange: (v: string) => void;
  tabs: { value: string; label: string }[];
  children: ReactNode;
}) {
  return (
    <RadixTabs.Root value={value} onValueChange={onValueChange}>
      <RadixTabs.List className="flex gap-4 border-b border-border">
        {tabs.map((tab) => (
          <RadixTabs.Trigger
            key={tab.value}
            value={tab.value}
            className="cp-label -mb-px border-b-2 border-transparent px-0.5 py-2 data-[state=active]:border-signal data-[state=active]:text-ink"
          >
            {tab.label}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {children}
    </RadixTabs.Root>
  );
}

export const TabPanel = RadixTabs.Content;

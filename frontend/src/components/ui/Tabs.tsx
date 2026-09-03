import { Tabs as RadixTabs } from "radix-ui";
import type { ReactNode } from "react";

/** A same-page, panel-switching tab set (Radix `Tabs`, full keyboard
 * support).
 *
 * NOT what RepoLayout's repository section nav uses -- those are real
 * ROUTES (`NavLink`s under react-router, each with its own deep-linkable
 * URL), and converting route navigation into this component would
 * silently break every existing bookmark/share-link/back-button
 * expectation. Reach for this only when switching a "tab" does NOT change
 * the URL. `components/ui/SegmentedControl.tsx` is the more common choice
 * for exactly that same-page case going forward (?view=/?tab= query-param
 * switches); this lower-level `Tabs` remains for a page that genuinely
 * wants Radix tab PANELS (content unmounted/remounted per tab), which
 * `SegmentedControl` does not manage on its own. */
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
      <RadixTabs.List className="flex gap-5 border-b border-border">
        {tabs.map((tab) => (
          <RadixTabs.Trigger
            key={tab.value}
            value={tab.value}
            className="cp-label -mb-px border-b-2 border-transparent px-0.5 py-2.5 data-[state=active]:border-accent data-[state=active]:text-text"
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

import { Tooltip as RadixTooltip } from "radix-ui";
import type { ReactNode } from "react";

/** One `Provider` per app (mounted once in AppShell), then `Tooltip` at
 * each call site. Radix handles hover delay, keyboard focus, and `Escape`
 * to dismiss -- a native `title` attribute gets none of that and is
 * invisible to touch/keyboard users entirely. */
export const TooltipProvider = RadixTooltip.Provider;

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-sm border border-border bg-bg-elevated px-2.5 py-1.5 text-xs text-text shadow-md"
        >
          {content}
          <RadixTooltip.Arrow className="fill-border" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

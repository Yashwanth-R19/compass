import { Popover as RadixPopover } from "radix-ui";
import type { ReactNode } from "react";

/** Thin Radix Popover wrapper styled like `Select`'s content panel. The
 * trigger must be a single focusable element (passed via `asChild`). */
export function Popover({
  trigger,
  children,
  open,
  onOpenChange,
  align = "start",
}: {
  trigger: ReactNode;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  align?: "start" | "center" | "end";
}) {
  return (
    <RadixPopover.Root open={open} onOpenChange={onOpenChange}>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          align={align}
          sideOffset={6}
          className="z-50 w-80 max-w-[calc(100vw-2rem)] rounded-sm border border-border bg-bg-elevated p-3 text-sm text-text shadow-md"
        >
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}

import { Dialog as RadixDialog } from "radix-ui";
import type { ReactNode } from "react";

/** A right-edge slide-in panel (Radix `Dialog` underneath, so focus is
 * trapped inside while open, `Escape` closes it, and focus returns to
 * whatever triggered it on close -- all for free). Used for a detail view
 * that shouldn't navigate away from the page it was opened from (e.g.
 * FileDetailPanel's file inspector on the codebase map / 3D city). */
export function Drawer({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-overlay data-[state=open]:animate-none" />
        <RadixDialog.Content className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <RadixDialog.Title className="text-sm font-semibold text-ink">
              {title}
            </RadixDialog.Title>
            <RadixDialog.Close className="text-ink-faint hover:text-ink" aria-label="Close">
              ✕
            </RadixDialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-4">{children}</div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

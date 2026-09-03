import { Dialog as RadixDialog } from "radix-ui";
import { X } from "lucide-react";
import type { ReactNode } from "react";

/** A right-edge slide-in panel (Radix `Dialog` underneath, so focus is
 * trapped inside while open, `Escape` closes it, and focus returns to
 * whatever triggered it on close). Used for a detail view that shouldn't
 * navigate away from the page it was opened from. */
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
        <RadixDialog.Content className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-bg-elevated shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <RadixDialog.Title className="font-display text-lg text-text-heading">
              {title}
            </RadixDialog.Title>
            <RadixDialog.Close className="text-text-muted hover:text-text" aria-label="Close">
              <X size={16} aria-hidden="true" />
            </RadixDialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-4">{children}</div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

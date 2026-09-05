import { AlertDialog } from "radix-ui";
import type { ReactNode } from "react";
import { Button } from "./Button";

/** A modal confirmation gate for a destructive or hard-to-reverse action
 * (logging out, disconnecting GitHub, deleting an account) -- Radix
 * `AlertDialog` underneath, so focus is trapped, `Escape` cancels, and (per
 * Radix's own alertdialog semantics, distinct from `Dialog`) a screen
 * reader announces the description as soon as it opens rather than waiting
 * for an explicit focus move. `Drawer.tsx` is the equivalent primitive for
 * a non-destructive detail view -- this one is for "are you sure," never
 * for browsing content. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  onConfirm,
  variant = "danger",
  pending = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  variant?: "danger" | "primary";
  pending?: boolean;
}) {
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-overlay data-[state=open]:animate-none" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(24rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-bg-elevated p-5 shadow-lg data-[state=open]:animate-none">
          <AlertDialog.Title className="font-display text-lg text-text-heading">
            {title}
          </AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm leading-normal text-text-muted">
            {description}
          </AlertDialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <Button type="button" variant="ghost" size="sm">
                {cancelLabel}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button
                type="button"
                variant={variant}
                size="sm"
                disabled={pending}
                onClick={(e) => {
                  // Radix's Action normally closes the dialog on click --
                  // for an async mutation we want the dialog to stay open
                  // (and disabled) until the caller's own onSuccess/onError
                  // decides to close it, so the pending state is visible.
                  e.preventDefault();
                  onConfirm();
                }}
              >
                {pending ? "Working…" : confirmLabel}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

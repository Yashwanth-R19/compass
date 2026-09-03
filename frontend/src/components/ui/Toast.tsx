import { Toast as RadixToast } from "radix-ui";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface ToastItem {
  id: number;
  message: string;
}

const ToastCtx = createContext<((message: string) => void) | null>(null);

/** Mounted once in AppShell. `useToast()` gives any component a
 * `showToast(message)` function -- used for short, non-blocking
 * confirmations, never for anything the user must acknowledge (that's a
 * Drawer/Dialog's job). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const showToast = useCallback((message: string) => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, message }]);
  }, []);

  return (
    <ToastCtx.Provider value={showToast}>
      <RadixToast.Provider swipeDirection="right" duration={3000}>
        {children}
        {items.map((item) => (
          <RadixToast.Root
            key={item.id}
            onOpenChange={(open) => {
              if (!open) setItems((prev) => prev.filter((i) => i.id !== item.id));
            }}
            className="rounded-sm border border-border bg-bg-elevated px-3.5 py-2.5 text-sm text-text shadow-md data-[state=open]:animate-none"
          >
            <RadixToast.Description>{item.message}</RadixToast.Description>
          </RadixToast.Root>
        ))}
        <RadixToast.Viewport className="fixed bottom-4 right-4 z-50 flex w-72 flex-col gap-2 outline-none" />
      </RadixToast.Provider>
    </ToastCtx.Provider>
  );
}

export function useToast(): (message: string) => void {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

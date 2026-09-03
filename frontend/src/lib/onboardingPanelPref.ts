import { useSyncExternalStore } from "react";

/**
 * The landing page's "how Compass works" onboarding panel (Part I):
 * dismissible, shown on first visit only, reopenable from the header
 * (Part H) from ANY page — not just the landing page itself. That last
 * part is why this lives in its own small pub-sub module rather than as
 * local `useState` inside `HomePage`: `AppShell`'s header button needs to
 * be able to force the panel open again even when the visitor is on
 * `/dashboard` or a repo page, before `HomePage` has even mounted.
 *
 * Persistence follows the same discipline as `lib/narrativePref.ts`: every
 * localStorage read/write is wrapped in try/catch, and a blocked/private
 * store degrades to "not remembered" rather than crashing.
 */
const STORAGE_KEY = "compass-onboarding-dismissed";

const listeners = new Set<() => void>();

let dismissed = readDismissed();
// Session-only "force open" flag, set by the header's reopen button —
// deliberately NOT persisted, so it only affects the very next time the
// panel's visibility is computed, not future visits.
let forcedOpen = false;

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function notify(): void {
  for (const listener of listeners) listener();
}

/** Called by the landing page's dismiss ("×") control. */
export function dismissOnboardingPanel(): void {
  dismissed = true;
  forcedOpen = false;
  try {
    window.localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // Still dismissed for this visit -- just not remembered next time.
  }
  notify();
}

/** Called by the header's "How Compass works" button (Part H) -- forces
 * the panel visible again regardless of any prior dismissal, for this
 * visit only. The caller is responsible for navigating to `/` if the
 * visitor isn't already there; this only controls visibility once they
 * arrive. */
export function reopenOnboardingPanel(): void {
  forcedOpen = true;
  notify();
}

function isOpen(): boolean {
  return forcedOpen || !dismissed;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Read by `HomePage` to decide whether to render the panel at all. */
export function useOnboardingPanelOpen(): boolean {
  return useSyncExternalStore(subscribe, isOpen);
}

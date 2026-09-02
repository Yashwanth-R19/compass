import { useSyncExternalStore } from "react";

/** The single global "narrative phrasing" toggle (session 12, Part E) --
 * lives in the app header (`AppShell.tsx`), persisted to `localStorage`, and
 * read by every `NarrativeBlock` on the page regardless of which repo/tab
 * it's rendered on. Every read/write is wrapped in try/catch and DEFAULTS TO
 * OFF (Known Hazard #5: a private window/blocked site data must never crash
 * the page, and the safe default when persistence is unavailable at all is
 * "no narrative", not "always on"). */
const STORAGE_KEY = "compass:narrative-enabled";

const listeners = new Set<() => void>();
let cached = readFromStorage();

function readFromStorage(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function isNarrativeEnabled(): boolean {
  return cached;
}

export function setNarrativeEnabled(enabled: boolean): void {
  cached = enabled;
  try {
    if (enabled) {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // The toggle still works in memory for this visit -- just isn't
    // remembered next time (Known Hazard #5).
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The one hook every `NarrativeBlock` and the header toggle itself use --
 * `useSyncExternalStore` is what makes flipping the toggle in the header
 * immediately re-render every mounted `NarrativeBlock` on the current page,
 * not just the next one that happens to mount. */
export function useNarrativeEnabled(): boolean {
  return useSyncExternalStore(subscribe, isNarrativeEnabled);
}

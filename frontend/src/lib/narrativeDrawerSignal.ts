/**
 * A tiny pub-sub bridge so the ⌘K command palette (rebuild spec section
 * 8.1: "also reachable from ⌘K") can open `NarrativeDrawer` from anywhere,
 * even though the drawer's own open/closed state lives as local
 * `useState` inside the `NarrativeDrawer` instance mounted in
 * `RepoLayout`'s header -- the same "signal, not shared state" pattern
 * `lib/onboardingPanelPref.ts` already established for the header's
 * "How Compass works" reopen button. Session-only, deliberately not
 * persisted: each call just means "open right now."
 */
const listeners = new Set<() => void>();

export function requestNarrativeDrawerOpen(): void {
  for (const listener of listeners) listener();
}

export function onNarrativeDrawerOpenRequested(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

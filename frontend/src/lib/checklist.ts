import { useSyncExternalStore } from "react";

/**
 * The persistent checklist's (rebuild spec section 7.3) own local-state
 * flags -- for the two items real server state can't answer directly:
 * "open a finding" and "see who to ask about a file" have no server-side
 * trace of having been VIEWED (only of the underlying data existing), and
 * "ask for an AI explanation"/"share a run" would need a new bulk
 * "does any of my repos have X" endpoint neither of which exists today
 * (out of scope for a frontend-only session) -- a locally-remembered "you
 * did this at least once" flag is the honest, low-cost substitute. The
 * fifth item, "analyse a repository", is checked from real server state
 * directly (`useMyRepos`) and needs no flag here.
 *
 * Same discipline as every other localStorage-backed preference in this
 * app: every read/write wrapped in try/catch, degrading to "not done yet"
 * rather than crashing.
 */
export type ChecklistFlag =
  "opened_finding" | "asked_who_to_ask" | "asked_narrative" | "shared_run";

const FLAGS_KEY = "compass:checklist-flags";
const DISMISSED_KEY = "compass:checklist-dismissed";

const listeners = new Set<() => void>();

function notify(): void {
  for (const l of listeners) l();
}

// `useSyncExternalStore` requires `getSnapshot` to return a REFERENCE-STABLE
// value when nothing has changed -- `new Set(...)` on every call fails that
// contract (every render sees "a different object", so React concludes the
// store changed on every single render), which is a real, confirmed
// infinite-render loop this session's own end-to-end verification caught
// (`Maximum update depth exceeded` on /dashboard). Cache the snapshot and
// only recompute it when the underlying flags actually change.
let flagsSnapshot: Set<ChecklistFlag> | null = null;

function computeFlags(): Set<ChecklistFlag> {
  try {
    const raw = window.localStorage.getItem(FLAGS_KEY);
    return new Set(raw ? (JSON.parse(raw) as ChecklistFlag[]) : []);
  } catch {
    return new Set();
  }
}

function readFlags(): Set<ChecklistFlag> {
  flagsSnapshot ??= computeFlags();
  return flagsSnapshot;
}

export function markChecklistFlag(flag: ChecklistFlag): void {
  const flags = readFlags();
  if (flags.has(flag)) return;
  const next = new Set(flags);
  next.add(flag);
  try {
    window.localStorage.setItem(FLAGS_KEY, JSON.stringify([...next]));
  } catch {
    // Still marked for this visit -- just not remembered next time.
  }
  flagsSnapshot = next;
  notify();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useChecklistFlags(): Set<ChecklistFlag> {
  return useSyncExternalStore(subscribe, readFlags);
}

export function dismissChecklistForever(): void {
  try {
    window.localStorage.setItem(DISMISSED_KEY, "1");
  } catch {
    // Best-effort -- may show again next visit.
  }
  notify();
}

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

export function useChecklistDismissed(): boolean {
  return useSyncExternalStore(subscribe, readDismissed);
}

// Tour progress checkboxes (session 08, Part D) -- persisted per-file, keyed
// literally `repoId:runId:path` as the Part D spec states, so progress
// survives across visits but is scoped to the exact run the tour was
// computed for (a re-analysis gets a fresh run id, hence a fresh, empty
// checklist -- the tour's own file set can change between runs). Every read
// and write is wrapped in try/catch: a private window, blocked site data, or
// a storage quota error must never crash the page, only silently fail to
// persist (Known Hazard #3).
const PREFIX = "compass:tour";

function storageKey(repoId: string, runId: string, path: string): string {
  return `${PREFIX}:${repoId}:${runId}:${path}`;
}

export function isTourStopDone(repoId: string, runId: string, path: string): boolean {
  try {
    return window.localStorage.getItem(storageKey(repoId, runId, path)) === "1";
  } catch {
    return false;
  }
}

export function setTourStopDone(repoId: string, runId: string, path: string, done: boolean): void {
  try {
    if (done) {
      window.localStorage.setItem(storageKey(repoId, runId, path), "1");
    } else {
      window.localStorage.removeItem(storageKey(repoId, runId, path));
    }
  } catch {
    // Nothing to do -- the checkbox still toggles in memory for this visit.
  }
}

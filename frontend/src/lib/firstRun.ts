/**
 * The post-OAuth first-run flow's (`/welcome`, rebuild spec section 7.2)
 * once-per-user completion flag -- `compass:firstrun:<userId>`, wrapped in
 * try/catch throughout (a private window or blocked site data must degrade
 * to "not shown again automatically", never crash). Marked done the moment
 * any step is either finished or explicitly skipped -- both count as "seen
 * it," and neither ever shows the flow again uninvited.
 */
function storageKey(userId: string): string {
  return `compass:firstrun:${userId}`;
}

export function hasCompletedFirstRun(userId: string): boolean {
  try {
    return window.localStorage.getItem(storageKey(userId)) === "1";
  } catch {
    return true;
  }
}

export function markFirstRunDone(userId: string): void {
  try {
    window.localStorage.setItem(storageKey(userId), "1");
  } catch {
    // Nothing to persist -- the flow simply may show again next visit.
  }
}

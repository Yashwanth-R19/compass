import { useEffect, useState } from "react";

/** `components/CodeCity.tsx` (session 09) has its own local copy of this
 * same small hook; that file is outside this session's scope to touch, so
 * this is a second, independent copy for `pages/onboard/EvolutionPage.tsx`
 * (session 13) rather than a shared-then-refactored one -- same "small,
 * deliberate local copy" precedent already used elsewhere in this codebase
 * (e.g. app/engines/hygiene.py's `_nearest_rank_percentile` next to
 * app/engines/expertise.py's `_percentile`). */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = () => setReduced(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  return reduced;
}

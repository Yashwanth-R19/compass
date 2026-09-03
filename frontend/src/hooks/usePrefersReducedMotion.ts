import { useEffect, useState } from "react";

/** `components/CodeCity.tsx` (session 09) has its own local copy of this
 * same small hook; that file was outside session 13's scope to touch, so
 * this became a second, independent copy for the evolution scrubber
 * (session 13's `pages/onboard/EvolutionPage.tsx`, now
 * `pages/repo/EvolutionSurfacePage.tsx` since UI rebuild session 4 merged
 * it with the compare view) rather than a shared-then-refactored one --
 * same "small, deliberate local copy" precedent already used elsewhere in
 * this codebase (e.g. app/engines/hygiene.py's `_nearest_rank_percentile`
 * next to app/engines/expertise.py's `_percentile`). */
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

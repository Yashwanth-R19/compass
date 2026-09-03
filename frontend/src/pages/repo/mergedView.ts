import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * SCAFFOLDING (Part J): the shared state hook behind every interim merged
 * surface (`?view=`/`?tab=`/`?category=`/`?panel=`) in `pages/repo/`.
 * Sessions 3/4 replace these wrapper pages with real rebuilt surfaces;
 * this hook exists only to make the interim mounting genuinely navigable
 * in the meantime.
 *
 * Reads the URL param as the initial value, then keeps local state loosely
 * synced with it -- but ONLY adopts a new value FROM the URL when the
 * param is actually present and different, never resets to `defaultValue`
 * just because the param disappeared. That asymmetry is deliberate: some
 * of the un-rebuilt pages mounted inside these wrappers (`ImpactPage` in
 * particular) call `setSearchParams({...})` with a plain object rather
 * than a merge function, which wipes any OTHER param -- including this
 * one -- as a side effect of writing their own. If this hook reset to
 * `defaultValue` whenever the param vanished, selecting a file inside
 * Impact would visibly snap the whole Structure surface back to
 * Architecture. Landing here via a REDIRECT (a genuinely new, different
 * param value) still works correctly, since that case sets a present,
 * different value, which the effect below does adopt.
 */
export function useMergedViewParam(
  paramName: string,
  defaultValue: string,
): [string, (v: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlValue = searchParams.get(paramName);
  const [value, setValue] = useState(() => urlValue ?? defaultValue);

  useEffect(() => {
    if (urlValue && urlValue !== value) {
      setValue(urlValue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlValue]);

  function set(next: string) {
    setValue(next);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set(paramName, next);
        return merged;
      },
      { replace: true },
    );
  }

  return [value, set];
}

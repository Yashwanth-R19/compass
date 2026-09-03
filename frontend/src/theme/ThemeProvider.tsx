import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Theme = "dark" | "light";

const STORAGE_KEY = "compass-theme";

/**
 * Dark is the app's UNCONDITIONAL default (rebuild spec decision #9) --
 * this returns "light" ONLY when the stored preference explicitly says so.
 * There is deliberately no `prefers-color-scheme` fallback anywhere in this
 * function: the OS colour scheme never decides the initial theme, only a
 * prior explicit toggle does. Every localStorage read is wrapped in
 * try/catch -- a private window or blocked site data must mean "the
 * preference is not remembered", never a crash, and the safe fallback for
 * that case is the same unconditional default, dark.
 *
 * `index.html`'s inline pre-paint script duplicates this EXACT rule (read
 * the same key, same "only 'light' opts out of dark" logic) so the correct
 * theme applies before the first paint, with no flash. If you change the
 * rule here, change it there too -- the two must agree exactly.
 */
function readInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function persistTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The theme still applies for this visit -- it just won't be
    // remembered next time.
  }
}

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/** Mounted once, above QueryClientProvider (main.tsx). Stamps `data-theme`
 * on `<html>` on every change -- ALWAYS an explicit "dark" or "light"
 * value, never left absent, since `index.css`'s `@custom-variant dark`
 * (which repoints every un-rebuilt page's `dark:` utility at this same
 * attribute, for the transitional slate/indigo remap) needs something
 * concrete to match at all times, not just when the theme happens to be
 * non-default. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    persistTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => setThemeState(next), []);
  const toggleTheme = useCallback(
    () => setThemeState((prev) => (prev === "dark" ? "light" : "dark")),
    [],
  );

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}

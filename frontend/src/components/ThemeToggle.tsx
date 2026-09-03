import { Moon, Sun } from "lucide-react";
import { useTheme } from "../theme/ThemeProvider";

/** Icon-only header control (Part D). The icon shows the theme you'd
 * switch TO, not the current one -- a moon means "go dark", a sun means
 * "go light" -- and the accessible label states the action in words for
 * anyone not reading the glyph. */
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-pressed={!isDark}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="inline-flex h-7 w-7 items-center justify-center border border-border text-text-muted transition-colors hover:border-border-strong hover:text-text"
    >
      {isDark ? <Sun size={14} aria-hidden="true" /> : <Moon size={14} aria-hidden="true" />}
    </button>
  );
}

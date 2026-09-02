import { Link, Outlet } from "react-router-dom";
import { githubLoginUrl } from "../api/client";
import { useLogout, useMe } from "../api/hooks";
import { setNarrativeEnabled, useNarrativeEnabled } from "../lib/narrativePref";
import { TooltipProvider } from "./ui/Tooltip";
import { ToastProvider } from "./ui/Toast";

/** Session 12, Part E: the single global "narrative phrasing" toggle,
 * always visible in the header regardless of route or repo. Defaults to
 * off (Known Hazard #5) and every page remains fully usable either way --
 * this control only decides whether `NarrativeBlock` instances fetch and
 * render anything at all. */
function NarrativeToggle() {
  const enabled = useNarrativeEnabled();

  return (
    <label className="flex cursor-pointer items-center gap-1.5">
      <span className="cp-label hidden sm:inline">Narrative</span>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Toggle generated narrative phrasing"
        onClick={() => setNarrativeEnabled(!enabled)}
        className={`relative h-4 w-7 shrink-0 border transition-colors ${
          enabled ? "border-signal bg-signal" : "border-border-strong bg-surface-2"
        }`}
      >
        <span
          className={`absolute top-0.5 h-2.5 w-2.5 bg-surface transition-transform motion-reduce:transition-none ${
            enabled ? "translate-x-3.5" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}

export function AppShell() {
  const me = useMe();
  const logout = useLogout();

  return (
    <TooltipProvider>
      <ToastProvider>
        <div className="min-h-full">
          <header className="border-b border-border bg-surface">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
              <Link to="/" className="flex items-center gap-2 text-ink">
                <span className="flex h-6 w-6 items-center justify-center border border-ink bg-ink font-mono text-sm font-bold text-bg">
                  C
                </span>
                <span className="font-mono text-sm font-semibold tracking-tight">COMPASS</span>
              </Link>

              <nav aria-label="Primary" className="flex items-center gap-3 text-xs">
                <NarrativeToggle />
                <Link to="/" className="cp-label hover:text-ink">
                  Analyze
                </Link>

                {me.data ? (
                  <>
                    <Link to="/dashboard" className="cp-label hover:text-ink">
                      Dashboard
                    </Link>
                    <Link to="/portfolio" className="cp-label hover:text-ink">
                      Portfolio
                    </Link>
                    <div className="flex items-center gap-2 border-l border-border pl-3">
                      {me.data.avatar_url ? (
                        <img
                          src={me.data.avatar_url}
                          alt=""
                          className="h-6 w-6"
                          referrerPolicy="no-referrer"
                        />
                      ) : null}
                      <span className="text-ink-muted">{me.data.github_login}</span>
                      <button
                        type="button"
                        onClick={() => logout.mutate()}
                        className="text-ink-faint hover:text-ink hover:underline"
                      >
                        Log out
                      </button>
                    </div>
                  </>
                ) : (
                  <a
                    href={githubLoginUrl("basic")}
                    className="ml-1 border border-signal bg-signal px-3 py-1.5 text-xs font-medium text-signal-ink hover:opacity-90"
                  >
                    Log in with GitHub
                  </a>
                )}
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
            <Outlet />
          </main>
        </div>
      </ToastProvider>
    </TooltipProvider>
  );
}

import { Link, Outlet } from "react-router-dom";
import { githubLoginUrl } from "../api/client";
import { useLogout, useMe } from "../api/hooks";
import { setNarrativeEnabled, useNarrativeEnabled } from "../lib/narrativePref";

/** Session 12, Part E: the single global "narrative phrasing" toggle,
 * always visible in the header regardless of route or repo. Defaults to
 * off (Known Hazard #5) and every page remains fully usable either way --
 * this control only decides whether `NarrativeBlock` instances fetch and
 * render anything at all. */
function NarrativeToggle() {
  const enabled = useNarrativeEnabled();

  return (
    <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
      <span className="hidden sm:inline">Narrative</span>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Toggle generated narrative phrasing"
        onClick={() => setNarrativeEnabled(!enabled)}
        className={`relative h-4 w-7 shrink-0 rounded-full transition-colors ${
          enabled ? "bg-violet-500" : "bg-slate-300 dark:bg-slate-700"
        }`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform ${
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
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <Link to="/" className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-indigo-600 text-sm font-bold text-white">
              C
            </span>
            <span className="text-sm font-semibold tracking-tight">Compass</span>
          </Link>

          <div className="flex items-center gap-3">
            <NarrativeToggle />
            <Link
              to="/"
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Analyze a repo
            </Link>

            {me.data ? (
              <>
                <Link
                  to="/dashboard"
                  className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  Dashboard
                </Link>
                <div className="flex items-center gap-2 pl-1">
                  {me.data.avatar_url ? (
                    <img
                      src={me.data.avatar_url}
                      alt=""
                      className="h-6 w-6 rounded-full"
                      referrerPolicy="no-referrer"
                    />
                  ) : null}
                  <span className="text-xs text-slate-600 dark:text-slate-300">
                    {me.data.github_login}
                  </span>
                  <button
                    type="button"
                    onClick={() => logout.mutate()}
                    className="text-xs text-slate-500 hover:underline dark:text-slate-400"
                  >
                    Log out
                  </button>
                </div>
              </>
            ) : (
              <a
                href={githubLoginUrl("basic")}
                className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
              >
                Log in with GitHub
              </a>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}

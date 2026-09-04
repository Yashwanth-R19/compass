import { Compass, LogOut } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Link, NavLink, useLocation, useNavigate, useOutlet } from "react-router-dom";
import { githubLoginUrl } from "../api/client";
import { useLogout, useMe } from "../api/hooks";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { reopenOnboardingPanel } from "../lib/onboardingPanelPref";
import { TooltipProvider } from "./ui/Tooltip";
import { ToastProvider } from "./ui/Toast";
import { ThemeToggle } from "./ThemeToggle";
import { GlossaryDialog } from "./GlossaryDialog";
import { CommandPalette } from "./CommandPalette";

/** The route branch a pathname belongs to, for `RouteTransition`'s key --
 * every `/repos/:repoId/...` path collapses to `/repos/:repoId` regardless
 * of which surface or `?view=` it's on, so switching tabs inside ONE repo
 * never remounts `RepoLayout`. A first, broken version of this keyed on
 * the raw pathname directly: since `/repos/<id>/overview` and
 * `/repos/<id>/guide` are different strings, every single surface-tab click
 * force-remounted RepoLayout (and every query it owns -- `useMe`, `useRepo`,
 * `useRepoStatus`, `useRuns` all refired), which is both the exact
 * "feel immediate" regression the comment below warns against AND was
 * caught only by this session's own end-to-end pass, not by typecheck/lint/
 * build. Navigating to a genuinely different repo (a different `:repoId`)
 * still gets a fresh key, correctly. */
function routeBranch(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] === "repos" && segments[1]) return `/repos/${segments[1]}`;
  return pathname;
}

/** The one route-change transition in the app (rebuild spec section 6.2's
 * table, added session 4): a brief opacity + 8px settle, never a slide --
 * keyed on the route branch (see `routeBranch` above), never the full
 * location, so neither a query-param-only change (a surface's own
 * `?view=`) nor a surface-to-surface tab switch within the same repo
 * retriggers it. Scoped to this top-level Outlet only: RepoLayout's OWN
 * nested Outlet does not get a second, independent instance of this --
 * tab-to-tab switching inside a repo should feel immediate, not gain a
 * fade on every click. */
function RouteTransition() {
  const location = useLocation();
  const reducedMotion = usePrefersReducedMotion();
  // `useOutlet()` resolves to a concrete element AT THIS RENDER, unlike a
  // bare `<Outlet/>` (which re-reads the router's current match live) --
  // capturing it here is what lets AnimatePresence keep rendering the
  // OUTGOING page's real content while it exits, instead of the new page
  // flashing into both the entering AND "exiting" copies at once.
  const element = useOutlet();

  if (reducedMotion) return element;

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={routeBranch(location.pathname)}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.18, ease: [0.22, 0.61, 0.36, 1] }}
      >
        {element}
      </motion.div>
    </AnimatePresence>
  );
}

const PRIMARY_NAV = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/how-it-works", label: "How it works" },
];

/** Reopens the landing page's onboarding panel from anywhere in the app --
 * navigates to `/` first (a no-op if already there) so the panel has
 * somewhere to render, then forces it visible regardless of any prior
 * dismissal (`lib/onboardingPanelPref.ts`). */
function ReopenOnboardingButton() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => {
        reopenOnboardingPanel();
        navigate("/");
      }}
      className="cp-label hidden hover:text-text md:inline"
    >
      How Compass works
    </button>
  );
}

export function AppShell() {
  const me = useMe();
  const logout = useLogout();

  return (
    <TooltipProvider>
      <ToastProvider>
        <div className="flex min-h-full flex-col">
          <header className="border-b border-border bg-bg-elevated">
            <div className="mx-auto flex max-w-[var(--layout-max-width)] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
              <div className="flex items-center gap-6">
                <Link to="/" className="flex items-center gap-2 text-text-heading">
                  <Compass
                    size={20}
                    className="text-accent"
                    aria-hidden="true"
                    strokeWidth={1.75}
                  />
                  <span className="font-display text-lg font-medium tracking-tight">Compass</span>
                </Link>

                <nav aria-label="Primary" className="hidden items-center gap-4 sm:flex">
                  {PRIMARY_NAV.map((item) => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      className={({ isActive }) =>
                        `cp-label transition-colors ${isActive ? "text-accent" : "hover:text-text"}`
                      }
                    >
                      {item.label}
                    </NavLink>
                  ))}
                </nav>
              </div>

              <div className="flex items-center gap-3 text-xs">
                <ReopenOnboardingButton />
                <CommandPalette />
                <GlossaryDialog />
                <ThemeToggle />

                {me.data ? (
                  <div className="flex items-center gap-2 border-l border-border pl-3">
                    {me.data.avatar_url ? (
                      <img
                        src={me.data.avatar_url}
                        alt=""
                        className="h-6 w-6 rounded-full"
                        referrerPolicy="no-referrer"
                      />
                    ) : null}
                    <span className="hidden text-text-muted sm:inline">{me.data.github_login}</span>
                    <button
                      type="button"
                      onClick={() => logout.mutate()}
                      aria-label="Log out"
                      title="Log out"
                      className="text-text-muted hover:text-text"
                    >
                      <LogOut size={14} aria-hidden="true" />
                    </button>
                  </div>
                ) : (
                  <a
                    href={githubLoginUrl("basic")}
                    className="ml-1 rounded-sm border border-accent bg-accent px-3 py-1.5 text-xs font-medium text-accent-contrast hover:border-accent-strong hover:bg-accent-strong"
                  >
                    Log in with GitHub
                  </a>
                )}
              </div>
            </div>

            <nav
              aria-label="Primary (small screens)"
              className="flex gap-4 border-t border-border px-4 py-2 sm:hidden"
            >
              {PRIMARY_NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `cp-label transition-colors ${isActive ? "text-accent" : "hover:text-text"}`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </header>

          <main className="mx-auto w-full min-w-0 max-w-[var(--layout-max-width)] flex-1 px-4 py-6 sm:px-6">
            <RouteTransition />
          </main>
        </div>
      </ToastProvider>
    </TooltipProvider>
  );
}

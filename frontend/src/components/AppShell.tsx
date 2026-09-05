import { useState } from "react";
import { Compass, LogOut } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Link, useLocation, useNavigate, useOutlet } from "react-router-dom";
import { githubLoginUrl } from "../api/client";
import { useLogout, useMe } from "../api/hooks";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { reopenOnboardingPanel } from "../lib/onboardingPanelPref";
import { TooltipProvider } from "./ui/Tooltip";
import { ToastProvider } from "./ui/Toast";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { ThemeToggle } from "./ThemeToggle";
import { GlossaryDialog } from "./GlossaryDialog";
import { CommandPalette } from "./CommandPalette";
import { CapsuleNav } from "./CapsuleNav";
import { Magnet } from "../reactbits/Magnet";
import { GlareHover } from "../reactbits/GlareHover";

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
  const navigate = useNavigate();
  const [logoutOpen, setLogoutOpen] = useState(false);

  return (
    <TooltipProvider>
      <ToastProvider>
        <div className="flex min-h-full flex-col">
          <header className="sticky top-0 z-30 border-b border-border bg-bg-elevated/90 backdrop-blur-sm">
            <div className="mx-auto flex max-w-[var(--layout-max-width)] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
              <div className="flex items-center gap-6">
                <Link
                  to="/"
                  className="group flex items-center gap-2 text-text-heading transition-transform duration-150 hover:-translate-y-px"
                >
                  <Compass
                    size={20}
                    className="text-accent transition-transform duration-300 group-hover:rotate-45"
                    aria-hidden="true"
                    strokeWidth={1.75}
                  />
                  <span className="font-display text-lg font-medium tracking-tight">Compass</span>
                </Link>

                <CapsuleNav items={PRIMARY_NAV} groupId="app" className="hidden sm:flex" />
              </div>

              <div className="flex items-center gap-3 text-xs">
                <ReopenOnboardingButton />
                <CommandPalette />
                <GlossaryDialog />
                <ThemeToggle />

                {me.data ? (
                  <div className="flex items-center gap-1.5 border-l border-border pl-3">
                    <Link
                      to="/profile"
                      className="flex items-center gap-2 rounded-full py-1 pr-2.5 pl-1 transition-colors hover:bg-bg-inset"
                      title="Your profile"
                    >
                      {me.data.avatar_url ? (
                        <img
                          src={me.data.avatar_url}
                          alt=""
                          className="h-7 w-7 rounded-full border border-border"
                          referrerPolicy="no-referrer"
                        />
                      ) : (
                        <span className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-bg-inset font-display text-[13px] text-text-heading">
                          {me.data.github_login.slice(0, 1).toUpperCase()}
                        </span>
                      )}
                      <span className="hidden text-text-muted sm:inline">
                        {me.data.github_login}
                      </span>
                    </Link>
                    <button
                      type="button"
                      onClick={() => setLogoutOpen(true)}
                      aria-label="Log out"
                      title="Log out"
                      className="rounded-full p-1.5 text-text-muted transition-colors hover:bg-bg-inset hover:text-text"
                    >
                      <LogOut size={14} aria-hidden="true" />
                    </button>
                  </div>
                ) : (
                  <Magnet padding={40} magnetStrength={8} wrapperClassName="ml-1">
                    <GlareHover className="rounded-full">
                      <a
                        href={githubLoginUrl("basic")}
                        className="inline-block rounded-full border border-accent bg-accent px-4 py-1.5 text-xs font-medium text-accent-contrast shadow-sm transition-colors hover:border-accent-strong hover:bg-accent-strong"
                      >
                        Log in with GitHub
                      </a>
                    </GlareHover>
                  </Magnet>
                )}
              </div>
            </div>

            <div className="px-4 pb-2 sm:hidden">
              <CapsuleNav
                items={PRIMARY_NAV}
                groupId="app-mobile"
                className="flex w-full"
                itemClassName="flex-1 text-center"
              />
            </div>
          </header>

          <main className="mx-auto w-full min-w-0 max-w-[var(--layout-max-width)] flex-1 px-4 py-6 sm:px-6">
            <RouteTransition />
          </main>
        </div>

        <ConfirmDialog
          open={logoutOpen}
          onOpenChange={setLogoutOpen}
          title="Log out?"
          description="You'll need to sign in with GitHub again to access your repositories and history."
          confirmLabel="Log out"
          variant="primary"
          pending={logout.isPending}
          onConfirm={() => {
            logout.mutate(undefined, {
              onSuccess: () => {
                setLogoutOpen(false);
                navigate("/");
              },
            });
          }}
        />
      </ToastProvider>
    </TooltipProvider>
  );
}

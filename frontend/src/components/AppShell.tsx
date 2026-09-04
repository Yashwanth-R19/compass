import { Compass, LogOut } from "lucide-react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { githubLoginUrl } from "../api/client";
import { useLogout, useMe } from "../api/hooks";
import { reopenOnboardingPanel } from "../lib/onboardingPanelPref";
import { TooltipProvider } from "./ui/Tooltip";
import { ToastProvider } from "./ui/Toast";
import { ThemeToggle } from "./ThemeToggle";
import { GlossaryDialog } from "./GlossaryDialog";
import { CommandPalette } from "./CommandPalette";

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
            <Outlet />
          </main>
        </div>
      </ToastProvider>
    </TooltipProvider>
  );
}

import { Compass, LogOut } from "lucide-react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { githubLoginUrl } from "../api/client";
import { useLogout, useMe } from "../api/hooks";
import { setNarrativeEnabled, useNarrativeEnabled } from "../lib/narrativePref";
import { reopenOnboardingPanel } from "../lib/onboardingPanelPref";
import { TooltipProvider } from "./ui/Tooltip";
import { ToastProvider } from "./ui/Toast";
import { ThemeToggle } from "./ThemeToggle";

const PRIMARY_NAV = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/how-it-works", label: "How it works" },
  { to: "/methods", label: "Methods" },
];

/** The single global "narrative phrasing" toggle -- always visible in the
 * header regardless of route or repo. Defaults to off and every page
 * remains fully usable either way; this control only decides whether
 * `NarrativeBlock` instances fetch and render anything at all. */
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
        className={`relative h-4 w-7 shrink-0 rounded-full border transition-colors ${
          enabled ? "border-accent bg-accent" : "border-border-strong bg-bg-inset"
        }`}
      >
        <span
          className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-bg-elevated transition-transform motion-reduce:transition-none ${
            enabled ? "translate-x-3.5" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}

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
      className="cp-label hover:text-text"
    >
      How Compass works
    </button>
  );
}

/** Stub for session 2's real glossary dialog -- the trigger exists from
 * this session so the header's right cluster is complete, but it has no
 * content to open yet (out of scope, Part I of this session's "do not do
 * these" list). */
function GlossaryTriggerStub() {
  return (
    <button
      type="button"
      disabled
      title="Glossary — coming in a future session"
      className="cp-label cursor-not-allowed text-text-muted/60"
    >
      Glossary
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
            <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
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

              <div className="flex items-center gap-4 text-xs">
                <ReopenOnboardingButton />
                <GlossaryTriggerStub />
                <NarrativeToggle />
                <ThemeToggle />

                {me.data ? (
                  <div className="flex items-center gap-2 border-l border-border pl-4">
                    {me.data.avatar_url ? (
                      <img
                        src={me.data.avatar_url}
                        alt=""
                        className="h-6 w-6 rounded-full"
                        referrerPolicy="no-referrer"
                      />
                    ) : null}
                    <span className="text-text-muted">{me.data.github_login}</span>
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
                    className="ml-1 rounded-sm border border-accent bg-accent px-3 py-1.5 text-xs font-medium text-accent-contrast hover:bg-accent-strong hover:border-accent-strong"
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

          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
            <Outlet />
          </main>
        </div>
      </ToastProvider>
    </TooltipProvider>
  );
}

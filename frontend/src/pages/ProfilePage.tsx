import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ExternalLink, ShieldCheck, ShieldOff } from "lucide-react";
import { useDeleteAccount, useDisconnectGithub, useLogout, useMe, useMyRepos } from "../api/hooks";
import { githubLoginUrl } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { ThemeToggle } from "../components/ThemeToggle";
import { LoadingState } from "../components/LoadingState";
import { CountUp } from "../components/motion/CountUp";
import { Reveal } from "../components/motion/Reveal";

/** `/profile` -- the account's own page: who Compass thinks you are, what
 * it has stored about you, and the two data-control actions
 * (disconnect vs. full delete) plan/RULES.md's privacy posture implies but
 * never previously had a home in the UI. Everything here reads from
 * `GET /auth/me`/`GET /me/repos` -- nothing new to compute, only to
 * surface and act on. */
export function ProfilePage() {
  const me = useMe();
  const myRepos = useMyRepos(1, 1); // just the `total` count; one row is enough
  const navigate = useNavigate();
  const logout = useLogout();
  const disconnect = useDisconnectGithub();
  const deleteAccount = useDeleteAccount();

  const [logoutOpen, setLogoutOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  if (me.isPending) return <LoadingState label="Loading your profile…" />;
  if (!me.data) return <Navigate to="/" replace />;

  const user = me.data;
  const memberSince = new Date(user.created_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 py-6">
      <Reveal>
        <div className="flex items-center gap-4">
          {user.avatar_url ? (
            <img
              src={user.avatar_url}
              alt=""
              referrerPolicy="no-referrer"
              className="h-16 w-16 rounded-full border border-border"
            />
          ) : (
            <div className="flex h-16 w-16 items-center justify-center rounded-full border border-border bg-bg-inset font-display text-2xl text-text-heading">
              {user.github_login.slice(0, 1).toUpperCase()}
            </div>
          )}
          <div className="min-w-0">
            <h1 className="truncate font-display text-2xl text-text-heading">
              {user.name || user.github_login}
            </h1>
            <a
              href={`https://github.com/${user.github_login}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-sm text-text-muted hover:text-accent hover:underline"
            >
              @{user.github_login}
              <ExternalLink size={12} aria-hidden="true" />
            </a>
          </div>
        </div>
      </Reveal>

      <Reveal delay={0.05}>
        <Card eyebrow="Account" title="Overview">
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div>
              <dt className="cp-label">Member since</dt>
              <dd className="mt-1 text-sm text-text">{memberSince}</dd>
            </div>
            <div>
              <dt className="cp-label">Repositories analyzed</dt>
              <dd className="mt-1 text-sm font-medium tabular-nums text-text">
                <CountUp to={myRepos.data?.total ?? 0} />
              </dd>
            </div>
            <div>
              <dt className="cp-label">Appearance</dt>
              <dd className="mt-1">
                <ThemeToggle />
              </dd>
            </div>
          </dl>
        </Card>
      </Reveal>

      <Reveal delay={0.1}>
        <Card eyebrow="GitHub connection" title="What Compass can access">
          <div className="flex items-start gap-3">
            {user.has_repo_scope ? (
              <ShieldCheck size={18} className="mt-0.5 shrink-0 text-success" aria-hidden="true" />
            ) : (
              <ShieldOff size={18} className="mt-0.5 shrink-0 text-text-muted" aria-hidden="true" />
            )}
            <div className="min-w-0">
              <p className="text-sm text-text">
                {user.has_repo_scope ? (
                  <>
                    <Badge tone="low">Private repo access granted</Badge> Compass can clone and
                    analyze private repositories you own or can see.
                  </>
                ) : (
                  <>
                    <Badge tone="neutral">Public repos only</Badge> Compass can only read data
                    you've explicitly submitted for public repositories.
                  </>
                )}
              </p>
              {!user.has_repo_scope ? (
                <a
                  href={githubLoginUrl("repo", "/profile")}
                  className="mt-2 inline-block text-sm font-medium text-accent hover:underline"
                >
                  Connect private repositories
                </a>
              ) : null}
            </div>
          </div>

          <div className="mt-4 border-t border-border pt-4">
            <p className="text-sm text-text-muted">
              Disconnecting removes Compass's stored GitHub token. Your account and analysis history
              stay intact, and you can reconnect at any time.
            </p>
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              disabled={disconnect.isPending}
              onClick={() => setDisconnectOpen(true)}
            >
              Disconnect GitHub
            </Button>
            {disconnect.isError ? (
              <Alert variant="danger" className="mt-2">
                Couldn't disconnect. Try again in a moment.
              </Alert>
            ) : null}
          </div>
        </Card>
      </Reveal>

      <Reveal delay={0.15}>
        <Card eyebrow="Session" title="This device">
          <p className="text-sm text-text-muted">
            Logging out ends this browser's session. You'll need to sign in with GitHub again to
            come back.
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={() => setLogoutOpen(true)}
          >
            Log out
          </Button>
        </Card>
      </Reveal>

      <Reveal delay={0.2}>
        <Card className="border-danger/40" eyebrow="Danger zone" title="Delete account & data">
          <p className="text-sm text-text-muted">
            Revokes Compass's GitHub authorization entirely — a future login shows the consent
            screen again, from scratch — and permanently deletes every repository, analysis run, and
            finding you own. This cannot be undone.
          </p>
          <Button variant="danger" size="sm" className="mt-3" onClick={() => setDeleteOpen(true)}>
            Delete my account &amp; data
          </Button>
          {deleteAccount.isError ? (
            <Alert variant="danger" className="mt-2">
              Couldn't delete your account. Try again in a moment.
            </Alert>
          ) : null}
        </Card>
      </Reveal>

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

      <ConfirmDialog
        open={disconnectOpen}
        onOpenChange={setDisconnectOpen}
        title="Disconnect GitHub?"
        description="Compass will stop being able to clone or view private repositories. Your account and existing analysis history are kept, and you can reconnect any time."
        confirmLabel="Disconnect"
        pending={disconnect.isPending}
        onConfirm={() => {
          disconnect.mutate(undefined, {
            onSuccess: () => setDisconnectOpen(false),
          });
        }}
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete your account and all data?"
        description={
          <>
            This revokes Compass's GitHub authorization, permanently deletes every repository and
            analysis you own, and logs you out. This action cannot be undone.
          </>
        }
        confirmLabel="Delete everything"
        pending={deleteAccount.isPending}
        onConfirm={() => {
          deleteAccount.mutate(undefined, {
            onSuccess: () => {
              setDeleteOpen(false);
              navigate("/");
            },
          });
        }}
      />
    </div>
  );
}

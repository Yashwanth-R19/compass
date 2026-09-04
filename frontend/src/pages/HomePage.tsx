import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { useMe, useMyGithubRepos, useShowcaseRepos, useSubmitRepo } from "../api/hooks";
import { ApiError, RateLimitedError, githubLoginUrl } from "../api/client";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { Alert } from "../components/ui/Alert";
import { Reveal } from "../components/motion/Reveal";
import { CountUp } from "../components/motion/CountUp";
import { PipelineSequence } from "../components/PipelineSequence";
import { OnboardingPanel } from "../components/OnboardingPanel";
import { GetStartedChecklist } from "../components/GetStartedChecklist";
import { BlurText } from "../reactbits/BlurText";
import { AnimatedList } from "../reactbits/AnimatedList";
import { useOnboardingPanelOpen } from "../lib/onboardingPanelPref";
import { hasCompletedFirstRun } from "../lib/firstRun";
import type { ShowcaseRepoOut } from "../api/types";

export function HomePage() {
  const [url, setUrl] = useState("");
  const [submittedRepoId, setSubmittedRepoId] = useState<string | null>(null);
  const navigate = useNavigate();

  const me = useMe();
  const submitRepo = useSubmitRepo();
  const showcase = useShowcaseRepos();
  const onboardingOpen = useOnboardingPanelOpen();
  const hasRepoScope = Boolean(me.data?.has_repo_scope);
  const githubRepos = useMyGithubRepos(hasRepoScope);

  // A freshly-logged-in user who hasn't been through /welcome yet lands
  // there automatically the first time they arrive here (rebuild spec
  // section 7.2) -- there's no "first login ever" signal from the backend
  // to key off directly, so "logged in, on the home page, no completion
  // flag set" is this app's own proxy for it.
  useEffect(() => {
    if (me.data && !hasCompletedFirstRun(me.data.id)) {
      navigate("/welcome");
    }
  }, [me.data, navigate]);

  function submitUrl(targetUrl: string) {
    if (!targetUrl.trim()) return;
    // Rendered inline via PipelineSequence below rather than navigating
    // away to a spinner (rebuild spec Part D) -- the submission itself is
    // the moment the showpiece exists for.
    submitRepo.mutate(targetUrl.trim(), {
      onSuccess: (res) => setSubmittedRepoId(res.repo_id),
    });
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submitUrl(url);
  }

  const submitError = submitRepo.error;
  const showcaseRepos = [...(showcase.data?.repos ?? [])].sort(
    (a, b) => (a.showcase_rank ?? Infinity) - (b.showcase_rank ?? Infinity),
  );

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-16 py-10">
      {/* Hero */}
      <section className="flex flex-col items-start gap-4">
        <BlurText
          text="Compass"
          tag="h1"
          className="font-display text-5xl font-medium tracking-tight text-text-heading"
        />
        <Reveal delay={0.35}>
          <p className="max-w-xl text-lg leading-normal text-text-muted">
            Compass mines a Git repository&apos;s full commit history and computes deterministic,
            reproducible intelligence about it — hidden change-coupling, calibrated bug risk,
            architecture, and security findings, the same way every time, never guessed by a model
            reading the current tree.
          </p>
        </Reveal>
      </section>

      {/* Persistent checklist -- logged-in visitors only, beneath the hero
          (rebuild spec section 7.3). Renders nothing of its own once
          dismissed or for an anonymous visitor. */}
      {me.data ? (
        <Reveal delay={0.1}>
          <GetStartedChecklist />
        </Reveal>
      ) : null}

      {/* Onboarding panel */}
      {onboardingOpen ? (
        <Reveal>
          <OnboardingPanel />
        </Reveal>
      ) : null}

      {/* Showcase -- promoted above the submit form (D11): a visitor should
          be inside real data in one click, not after an analysis wait. */}
      {showcaseRepos.length > 0 ? (
        <Reveal as="div" delay={0.05}>
          <section aria-label="Showcase repositories">
            <p className="cp-label mb-1">Showcase</p>
            <h2 className="font-display text-2xl text-text-heading">
              Real repositories, already analysed
            </h2>
            <p className="mt-1 text-sm text-text-muted">
              Pre-computed — click straight into a full result, no submission and no waiting.
            </p>
            <AnimatedList
              items={showcaseRepos}
              keyFor={(repo) => repo.id}
              className="mt-5 grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3"
              renderItem={(repo) => <ShowcaseCard repo={repo} />}
            />
          </section>
        </Reveal>
      ) : null}

      {/* Submit */}
      <Reveal delay={0.05}>
        <section aria-label="Analyze a repository">
          <p className="cp-label mb-1">Analyze</p>
          <h2 className="font-display text-2xl text-text-heading">Point Compass at a repository</h2>

          {submittedRepoId ? (
            <div className="mt-4">
              <PipelineSequence
                repoId={submittedRepoId}
                onDone={() => navigate(`/repos/${submittedRepoId}/overview`)}
              />
            </div>
          ) : (
            <>
              <Alert variant="info" className="mt-4">
                This deployment&apos;s live analysis runs on a free-tier host — cloning and mining a
                large repository can take a few minutes, and submissions are rate-limited. The
                showcase repositories above are pre-computed and load instantly.
              </Alert>

              <form onSubmit={handleSubmit} className="mt-4 flex w-full flex-col gap-2 sm:flex-row">
                <Input
                  type="text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo"
                  disabled={submitRepo.isPending}
                  className="flex-1 font-mono"
                />
                <Button type="submit" variant="primary" disabled={submitRepo.isPending}>
                  {submitRepo.isPending ? "Submitting…" : "Analyze"}
                </Button>
              </form>

              {submitError ? <SubmitErrorNotice error={submitError} /> : null}

              {me.data && !hasRepoScope ? (
                <p className="mt-3 text-xs text-text-muted">
                  Want to analyze a private repository?{" "}
                  <a
                    href={githubLoginUrl("repo", "/")}
                    className="font-medium text-accent hover:underline"
                  >
                    Connect private repositories
                  </a>
                  .
                </p>
              ) : null}

              {hasRepoScope ? (
                <div className="mt-6">
                  <p className="cp-label mb-2">Or pick from your GitHub repositories</p>
                  {githubRepos.isPending ? (
                    <p className="text-xs text-text-muted">Loading…</p>
                  ) : githubRepos.isError ? (
                    <p className="text-xs text-danger">
                      {githubRepos.error instanceof ApiError
                        ? githubRepos.error.message
                        : "Couldn't load your GitHub repositories."}
                    </p>
                  ) : (
                    <div className="max-h-56 overflow-y-auto rounded-sm border border-border">
                      {githubRepos.data.repos.length === 0 ? (
                        <p className="px-3 py-2 text-xs text-text-muted">
                          No repositories found on your GitHub account.
                        </p>
                      ) : (
                        githubRepos.data.repos.map((repo) => (
                          <button
                            key={repo.full_name}
                            type="button"
                            disabled={submitRepo.isPending}
                            onClick={() => submitUrl(`https://github.com/${repo.full_name}`)}
                            className="flex w-full items-center justify-between gap-2 border-b border-border px-3 py-2 text-left text-xs last:border-b-0 hover:bg-bg-inset disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <span className="truncate font-mono text-text-muted">
                              {repo.full_name}
                            </span>
                            {repo.private ? <Badge tone="neutral">Private</Badge> : null}
                          </button>
                        ))
                      )}
                      {githubRepos.data.truncated ? (
                        <p className="px-3 py-2 text-[10px] text-text-muted">
                          Showing your first 300 repositories, sorted by most recently pushed.
                        </p>
                      ) : null}
                    </div>
                  )}
                </div>
              ) : null}
            </>
          )}
        </section>
      </Reveal>

      {/* Teaser strip */}
      <Reveal delay={0.05}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TeaserCard
            to="/how-it-works"
            title="How it works"
            description="A stage-by-stage walk through the mining pipeline, with one real repository's numbers threaded through every step."
          />
          <TeaserCard
            to="/how-it-works#methods"
            title="Methods"
            description="Every formula Compass computes, which are locked and which are heuristic, and the calibration corpus behind the benchmark."
          />
        </div>
      </Reveal>
    </div>
  );
}

function ShowcaseCard({ repo }: { repo: ShowcaseRepoOut }) {
  return (
    <Link
      to={`/repos/${repo.id}/overview`}
      className="flex min-h-40 flex-col justify-between bg-bg-elevated p-4 transition-colors hover:bg-bg-inset"
    >
      <div>
        <p className="truncate font-mono text-sm font-medium text-text-heading">
          {repo.owner}/{repo.name}
        </p>
        <p className="mt-1 text-xs text-text-muted">{repo.hook}</p>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5">
        <ShowcaseStat label="Commits" value={repo.commit_count} />
        <ShowcaseStat label="Subsystems" value={repo.subsystem_count} />
        {repo.truck_factor != null ? (
          <ShowcaseStat label="Truck factor" value={repo.truck_factor} />
        ) : null}
        {repo.health_score != null ? (
          <ShowcaseStat label="Health" value={Math.round(repo.health_score)} suffix=" / 100" />
        ) : null}
      </dl>
    </Link>
  );
}

function ShowcaseStat({
  label,
  value,
  suffix = "",
}: {
  label: string;
  value: number;
  suffix?: string;
}) {
  return (
    <div>
      <dt className="cp-label">{label}</dt>
      <dd className="cp-stat text-sm font-medium text-text-heading">
        <CountUp to={value} suffix={suffix} />
      </dd>
    </div>
  );
}

function TeaserCard({
  to,
  title,
  description,
}: {
  to: string;
  title: string;
  description: string;
}) {
  return (
    <Link to={to} className="block h-full">
      <Card className="h-full transition-colors hover:bg-bg-inset">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-display text-lg text-text-heading">{title}</h3>
          <ArrowRight size={16} className="mt-1 shrink-0 text-text-muted" aria-hidden="true" />
        </div>
        <p className="mt-2 text-sm text-text-muted">{description}</p>
      </Card>
    </Link>
  );
}

function SubmitErrorNotice({ error }: { error: unknown }) {
  if (error instanceof RateLimitedError) {
    const resetLabel =
      error.retryAfterSeconds >= 60
        ? `${Math.ceil(error.retryAfterSeconds / 60)} minute${error.retryAfterSeconds >= 120 ? "s" : ""}`
        : `${error.retryAfterSeconds} second${error.retryAfterSeconds === 1 ? "" : "s"}`;
    return (
      <p className="mt-2 text-sm text-warning">
        You&apos;ve hit the analysis limit for now. Try again in about {resetLabel}.
      </p>
    );
  }

  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return <p className="mt-2 text-sm text-danger">{message}</p>;
}

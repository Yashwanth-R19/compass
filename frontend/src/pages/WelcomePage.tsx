import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import {
  useMe,
  useMyGithubRepos,
  useShowcaseRepos,
  useSubmitRepo,
  useWorkedExample,
} from "../api/hooks";
import { ApiError, RateLimitedError, githubLoginUrl } from "../api/client";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { Reveal } from "../components/motion/Reveal";
import { PipelineSequence } from "../components/PipelineSequence";
import { EMPTY_MESSAGES } from "../content/explainability";
import { markFirstRunDone } from "../lib/firstRun";

type Step = 1 | 2 | 3;

/**
 * The post-OAuth first-run flow (rebuild spec section 7.2, D10) -- three
 * steps, each its own view, skippable at every one, shown once per user
 * (`lib/firstRun.ts`). Reached directly at `/welcome`, or (see
 * `HomePage.tsx`) automatically the first time a freshly-logged-in user
 * lands on the home page with no completion flag set yet.
 */
export function WelcomePage() {
  const me = useMe();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(1);
  const [repoId, setRepoId] = useState<string | null>(null);

  function finish(destination: string) {
    if (me.data) markFirstRunDone(me.data.id);
    navigate(destination);
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8 py-10">
      <div className="flex items-center justify-between gap-3">
        <p className="cp-label">
          Welcome{me.data ? `, ${me.data.github_login}` : ""} — step {step} of 3
        </p>
        <button
          type="button"
          onClick={() => finish("/dashboard")}
          className="text-xs text-text-muted hover:text-text"
        >
          Skip
        </button>
      </div>

      {step === 1 ? (
        <StepOne onNext={() => setStep(2)} onSkip={finish} />
      ) : step === 2 ? (
        <StepTwo
          onSubmitted={(id) => {
            setRepoId(id);
            setStep(3);
          }}
        />
      ) : repoId ? (
        <StepThree repoId={repoId} onDone={() => finish(`/repos/${repoId}/overview`)} />
      ) : null}
    </div>
  );
}

function StepOne({ onNext, onSkip }: { onNext: () => void; onSkip: (dest: string) => void }) {
  const workedExample = useWorkedExample();
  const showcase = useShowcaseRepos();
  const example = workedExample.data;

  const firstShowcase = [...(showcase.data?.repos ?? [])].sort(
    (a, b) => (a.showcase_rank ?? Infinity) - (b.showcase_rank ?? Infinity),
  )[0];

  return (
    <Reveal>
      <section className="flex flex-col gap-5">
        <div>
          <h1 className="font-display text-3xl font-medium tracking-tight text-text-heading">
            What Compass does
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-text-muted">
            Three claims, each backed by a real number from one real analysis — not invented for
            this page.
          </p>
        </div>

        <ul className="flex flex-col gap-3">
          <ClaimCard
            claim="Compass mines a repository's full commit history, deterministically."
            figure={
              example?.commit_count != null
                ? `${example.commit_count.toLocaleString()} commits streamed`
                : null
            }
          />
          <ClaimCard
            claim="It finds hidden change-coupling and calibrated risk hotspots."
            figure={
              example?.coupling_pair_count != null && example?.hotspot_count != null
                ? `${example.coupling_pair_count.toLocaleString()} coupling pairs · ${example.hotspot_count} hotspots`
                : null
            }
          />
          <ClaimCard
            claim="It surfaces knowledge distribution, secrets, and dependency vulnerabilities."
            figure={
              example?.truck_factor != null
                ? `truck factor ${example.truck_factor}`
                : example?.finding_count != null
                  ? `${example.finding_count} findings ranked`
                  : null
            }
          />
        </ul>

        {!workedExample.isPending && !example ? (
          <p className="text-xs text-text-muted">{EMPTY_MESSAGES.workedExampleUnavailable}</p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="primary" onClick={onNext}>
            Analyse a repository
            <ArrowRight size={14} aria-hidden="true" />
          </Button>
          {firstShowcase ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => onSkip(`/repos/${firstShowcase.id}/overview`)}
            >
              Explore an example instead
            </Button>
          ) : null}
        </div>
      </section>
    </Reveal>
  );
}

function ClaimCard({ claim, figure }: { claim: string; figure: string | null }) {
  return (
    <li>
      <Card>
        <p className="text-sm text-text">{claim}</p>
        {figure ? <p className="cp-stat mt-1.5 text-xs text-accent">{figure}</p> : null}
      </Card>
    </li>
  );
}

function StepTwo({ onSubmitted }: { onSubmitted: (repoId: string) => void }) {
  const me = useMe();
  const [url, setUrl] = useState("");
  const submitRepo = useSubmitRepo();
  const hasRepoScope = Boolean(me.data?.has_repo_scope);
  const githubRepos = useMyGithubRepos(hasRepoScope);

  function submitUrl(targetUrl: string) {
    if (!targetUrl.trim()) return;
    submitRepo.mutate(targetUrl.trim(), {
      onSuccess: (res) => onSubmitted(res.repo_id),
    });
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submitUrl(url);
  }

  return (
    <Reveal>
      <section className="flex flex-col gap-5">
        <div>
          <h1 className="font-display text-3xl font-medium tracking-tight text-text-heading">
            Pick a repository
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-text-muted">
            Any public GitHub or GitLab repository, or one of your own.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex w-full flex-col gap-2 sm:flex-row">
          <Input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            disabled={submitRepo.isPending}
            className="flex-1 font-mono"
          />
          <Button type="submit" variant="primary" disabled={submitRepo.isPending}>
            {submitRepo.isPending ? "Submitting…" : "Analyse"}
          </Button>
        </form>

        {submitRepo.error ? <StepTwoError error={submitRepo.error} /> : null}

        {me.data && !hasRepoScope ? (
          <p className="text-xs text-text-muted">
            Want to analyse a private repository?{" "}
            <a
              href={githubLoginUrl("repo", "/welcome")}
              className="font-medium text-accent hover:underline"
            >
              Connect private repositories
            </a>
            .
          </p>
        ) : null}

        {hasRepoScope ? (
          <div>
            <p className="cp-label mb-2">Or pick from your GitHub repositories</p>
            {githubRepos.isPending ? (
              <p className="text-xs text-text-muted">Loading…</p>
            ) : githubRepos.isError ? (
              <p className="text-xs text-danger">Couldn't load your GitHub repositories.</p>
            ) : githubRepos.data.repos.length === 0 ? (
              <p className="text-xs text-text-muted">No repositories found on your account.</p>
            ) : (
              <div className="max-h-56 overflow-y-auto rounded-sm border border-border">
                {githubRepos.data.repos.map((repo) => (
                  <button
                    key={repo.full_name}
                    type="button"
                    disabled={submitRepo.isPending}
                    onClick={() => submitUrl(`https://github.com/${repo.full_name}`)}
                    className="flex w-full items-center justify-between gap-2 border-b border-border px-3 py-2 text-left text-xs last:border-b-0 hover:bg-bg-inset disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span className="truncate font-mono text-text-muted">{repo.full_name}</span>
                    {repo.private ? <Badge tone="neutral">Private</Badge> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </section>
    </Reveal>
  );
}

function StepTwoError({ error }: { error: unknown }) {
  if (error instanceof RateLimitedError) {
    return (
      <p className="text-sm text-warning">
        You&apos;ve hit the analysis limit for now. Try again in a little while.
      </p>
    );
  }
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return <p className="text-sm text-danger">{message}</p>;
}

function StepThree({ repoId, onDone }: { repoId: string; onDone: () => void }) {
  return (
    <Reveal>
      <section className="flex flex-col gap-5">
        <div>
          <h1 className="font-display text-3xl font-medium tracking-tight text-text-heading">
            Watch it run
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-text-muted">
            Every stage below is real — the actual mining and analysis pipeline, running right now.
          </p>
        </div>
        {/* PipelineSequence's own onDone only fires once per genuine
            pending -> terminal transition (its effect's dependency array
            settles once the run reaches "ready"/"failed"), so this never
            double-navigates. */}
        <PipelineSequence repoId={repoId} onDone={onDone} />
      </section>
    </Reveal>
  );
}

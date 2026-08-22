# DEPLOY.md — runbook for a human

Ordered checklist to take Compass from "runs on my machine" to a public URL.
Follow it top to bottom the first time; the later sections are for
maintenance and troubleshooting after that.

---

## 1. Create the Neon project

1. Go to [neon.tech](https://neon.tech) and create a free project (any
   region close to your Render region choice in step 4).
2. In the Neon console, open **Connection Details** and select the
   **pooled** connection string (the one with `-pooler` in the hostname) —
   Render's free tier and the GitHub Actions worker both open short-lived
   connections, and the pooled endpoint is what survives that pattern
   without exhausting Postgres's connection limit.
3. Copy the connection string. It looks like:
   ```
   postgresql://<user>:<password>@<host>-pooler.<region>.aws.neon.tech/<db>?sslmode=require
   ```
4. Compass's SQLAlchemy setup needs the `postgresql+psycopg://` scheme, not
   bare `postgresql://` — rewrite the string's scheme accordingly. This is
   the value for `DATABASE_URL` everywhere below.

---

## 2. Make the workflow repository public

`.github/workflows/mine.yml` and `.github/workflows/reaper.yml` only run on
`repository_dispatch`/`schedule` events fired against **this** repository,
and GitHub Actions minutes are free and unlimited on **public** repositories
(private repos get a limited monthly minutes budget on free plans). Making
this repo public is what makes the Actions worker free to run at any volume.

**The explicit warning:** a public repository's Actions logs are public too.
Anyone with the URL can read every line either workflow prints. This is why
`app/jobs/log_redaction.py` exists and why `app/jobs/worker.py` installs it
before anything else runs — but the discipline only holds if nobody adds a
new `print()`/`echo`/`run:` step that bypasses it. Review any future change
to `.github/workflows/*.yml` with that in mind.

To make the repo public: GitHub repo → **Settings** → **General** → scroll
to **Danger Zone** → **Change visibility** → **Make public**.

---

## 3. Create the fine-grained PAT

1. GitHub → your avatar → **Settings** → **Developer settings** →
   **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. **Repository access:** "Only select repositories" → select this one
   repository only. Never "All repositories."
3. **Permissions:** under **Repository permissions**, set **Actions** to
   **Read and write**. Leave every other permission at "No access."
4. Set an expiration (90 days is reasonable; you'll need to rotate it and
   update the Render env var when it expires).
5. Generate the token and copy it immediately — GitHub shows it once.
6. **Where it's stored:** as the Render environment variable
   `COMPASS_WORKER_PAT` (step 5 below). Never commit it, never put it in a
   GitHub Actions secret on this repo (the worker doesn't need it — it's the
   *caller*, in Render, that needs it to dispatch *to* this repo).

---

## 4. GitHub repository secrets (on this repo, for the workflows)

Repo → **Settings** → **Secrets and variables** → **Actions** → **New
repository secret**:

| Secret name | Value | Used by |
|---|---|---|
| `DATABASE_URL` | The same Neon pooled connection string from step 1, with `postgresql+psycopg://` scheme | `mine.yml`, `reaper.yml` |

That's the only one. The worker never needs a GitHub token of its own — it
only talks to Postgres.

---

## 5. Render environment variables (the web service)

Deploy `render.yaml` as a Render **Blueprint** (dashboard → **New +** →
**Blueprint**, point it at this repo). It declares every variable; the ones
marked `sync: false` need a value pasted into the Render dashboard after the
blueprint is created (**Environment** tab on the `compass-api` service):

| Variable | Value |
|---|---|
| `DATABASE_URL` | The Neon pooled connection string (step 1), `postgresql+psycopg://` scheme |
| `FRONTEND_ORIGIN` | Your Vercel deployment URL, e.g. `https://compass.vercel.app` |
| `COMPASS_CORS_ORIGINS` | Comma-separated extra allowed origins (Vercel preview URLs), or leave empty |
| `COMPASS_WORKER_REPO` | `{your-github-username}/{this-repo-name}`, e.g. `acme/compass` |
| `COMPASS_WORKER_PAT` | The fine-grained PAT from step 3 |
| `COMPASS_VERSION` | Any string you want `/health` to report, e.g. a git short SHA |

`ENV`, `COMPASS_WORKER_MODE`, and `COMPASS_MAX_REPO_MB` already have correct
defaults in `render.yaml` and don't need dashboard values unless you want to
override them.

**Migrations run via `render.yaml`'s `dockerCommand`** (`alembic upgrade
head && uvicorn ...`), not a separate pre-deploy step — Render's **free**
plan rejects a Blueprint with `preDeployCommand` set outright ("pre-deploy
command is not supported for free tier services"). The reason
migrations are normally kept out of the container's own start command is to
avoid two instances racing `alembic upgrade head` against the same database
at boot — but Render's free tier never runs more than one instance of a
service at a time, so that race can't happen here, and folding the
migration into `dockerCommand` is safe specifically because of that
constraint. **If you ever upgrade this service to a paid plan that scales
beyond one instance**, switch `render.yaml` back to a real
`preDeployCommand: alembic upgrade head` and drop the migration out of
`dockerCommand` — see the comment directly above `dockerCommand` in
`render.yaml`.

---

## 6. Set up the keep-alive ping

Render's free tier spins the service down after 15 minutes of no incoming
requests, and the next request pays a cold-start penalty (tens of seconds).
A cheap, free external ping keeps it warm:

1. Go to [cron-job.org](https://cron-job.org) and create a free account.
2. Create a new cron job: URL = `https://{your-render-service}.onrender.com/health`,
   interval = every 10 minutes (comfortably under the 15-minute spin-down
   window), method = GET.
3. That's it — `/health` runs a trivial `SELECT 1`, so the ping also proves
   the database connection itself is alive, not just the process.

---

## 7. Vercel setup (frontend)

1. Import this repository into Vercel, with **Root Directory** set to
   `frontend/`.
2. Vercel auto-detects the Vite build (`npm run build`, output `dist/`).
   `frontend/vercel.json`'s SPA rewrite is already committed, so a deep link
   like `/repos/<uuid>/architecture` won't 404 on a hard refresh.
3. Set the environment variable `VITE_API_URL` to your Render service's
   public URL, e.g. `https://compass-api.onrender.com` (no trailing slash).
4. Deploy. Once it's live, go back to Render and set `FRONTEND_ORIGIN` to
   this exact Vercel URL (step 5) — CORS will reject the frontend's requests
   until that matches.

---

## 8. Verify it works

**The web app end-to-end:** open the Vercel URL, submit a small public
GitHub repo, and watch the repo page fill in stage by stage.

**The Actions dispatch path, manually, with curl** (useful to confirm the
PAT/repo name are right before trusting the web app to exercise it):

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <COMPASS_WORKER_PAT>" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/<owner>/<repo>/dispatches \
  -d '{"event_type":"compass-mine","client_payload":{"repo_id":"<uuid>","run_id":"<uuid>"}}'
```

A `204 No Content` response means GitHub accepted the dispatch. Open the
**Actions** tab on this repo — a new "Mine" run should appear within a few
seconds (repo_id/run_id only matter for the DB-backed steps; use real
values from a repo you've actually submitted if you want the run to
complete successfully rather than just prove the dispatch fires).

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser console shows CORS errors | `FRONTEND_ORIGIN`/`COMPASS_CORS_ORIGINS` on Render doesn't match the Vercel URL exactly (scheme, no trailing slash) | Update the Render env var to the exact origin, redeploy |
| First request after idle takes 30–60s | Render free-tier cold start | Confirm the cron-job.org ping (step 6) is actually running and hitting `/health` every ≤14 minutes |
| API returns 500s referencing a missing column/table | Migration didn't run, or ran against the wrong database | Check the deploy's logs for the `alembic upgrade head` line (it runs as the first thing `dockerCommand` does, before uvicorn starts); confirm `DATABASE_URL` is set correctly on the service |
| Blueprint deploy fails with "pre-deploy command is not supported for free tier services" | `render.yaml` still has `preDeployCommand` set (a paid-tier-only field) instead of the free-tier-safe `dockerCommand` | Use the `dockerCommand` form already in this repo's `render.yaml`; only switch back to `preDeployCommand` if you upgrade off the free plan |
| `repository_dispatch` curl/API call returns `404` | Either `COMPASS_WORKER_REPO` is wrong, or the PAT's repository selection/Actions permission is wrong — **GitHub returns 404 for both cases, you cannot tell which from the status code alone** | Double-check `COMPASS_WORKER_REPO` is exactly `{owner}/{repo}` (case-sensitive) and that the PAT (step 3) has Actions: Read and write scoped to that exact repository |
| Dispatch succeeds (204) but no workflow run appears | `mine.yml` is not on the repository's **default branch** — `repository_dispatch` only ever triggers workflows defined on the default branch, silently, with no error | Merge `mine.yml`/`reaper.yml` to the default branch (usually `main`) |
| Runner OOM / killed mid-run | A very large repo, or a runner-level infra failure | `mine.yml`'s `if: failure()` step marks the run failed immediately; if it also died before that step could run, `reaper.yml` catches it within 15 minutes regardless |
| A repo's status is stuck showing "running" indefinitely | The runner died in a way neither `mine.yml`'s failure step nor (yet) `reaper.yml`'s 15-minute schedule has caught | Wait up to ~20 minutes for the next reaper run, or trigger it manually: **Actions** tab → **Reaper** → **Run workflow** |
| Repos over the size cap get accepted anyway | `check_github_repo_size` only checks github.com repos and doesn't block on its own API failures (rate limiting, network) by design — see its docstring | Not a bug to "fix" by making it stricter; if GitHub's API is unreachable the check is skipped rather than blocking a legitimate submission |

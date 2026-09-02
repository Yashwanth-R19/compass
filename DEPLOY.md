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
   bare `postgresql://` — `app/db/base.py` rewrites the scheme automatically
   at runtime, so either form works as `DATABASE_URL`; the pre-rewritten
   `postgresql+psycopg://` form is what's shown everywhere below for
   clarity. This is the value for `DATABASE_URL` everywhere below.

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
to `.github/workflows/*.yml` with that in mind — session 02 added a GitHub
token (`COMPASS_TOKEN_ENCRYPTION_KEY`-decrypted, for private-repo clones) to
this workflow's reach, which raises the stakes on that discipline, not just
the DB connection string it already carried.

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
   `COMPASS_WORKER_PAT` (step 7 below). Never commit it, never put it in a
   GitHub Actions secret on this repo (the worker doesn't need it — it's the
   *caller*, in Render, that needs it to dispatch *to* this repo).

---

## 4. Create the GitHub OAuth App (session 02)

This is a separate, unrelated credential from the PAT above: the PAT lets
Render *dispatch workflow runs to* this repository; the OAuth App is what
lets Compass *users* log in with their own GitHub account.

1. GitHub → your avatar → **Settings** → **Developer settings** →
   **OAuth Apps** → **New OAuth App** (or, for an organization-owned app,
   the equivalent under the org's settings).
2. **Application name:** anything recognizable, e.g. "Compass".
3. **Homepage URL:** your Vercel frontend URL (step 9 below) — if you
   haven't deployed the frontend yet, use `http://localhost:5173` for now
   and come back to update it once you have the real URL.
4. **Authorization callback URL:** your Render API's `/auth/github/callback`
   path, e.g. `https://compass-api.onrender.com/auth/github/callback` — this
   MUST match `GITHUB_OAUTH_REDIRECT_URI` (step 7 below) **exactly**
   (scheme, host, path — no trailing slash), or GitHub rejects the callback
   with a redirect_uri_mismatch error. If you haven't deployed the API yet,
   use `http://localhost:8000/auth/github/callback` for local dev and update
   this once you have the real Render URL.
5. Generate the app, then **Generate a new client secret**. Copy both the
   **Client ID** and the **Client secret** — you'll need them as
   `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` in step 7.
6. **This one OAuth App is used for BOTH consent screens** (`scope=basic`
   and `scope=repo` — CLAUDE.md's "two-step scope escalation"). You do not
   need, and should not create, a second OAuth App for the repo-scoped
   "Connect private repositories" flow — only the requested `scope` string
   differs per login, not the App itself.

---

## 5. Generate the Fernet key and JWT secret (session 02)

Two independent secrets, generated once and then treated exactly like
`DATABASE_URL` — never committed, never logged:

```bash
# COMPASS_TOKEN_ENCRYPTION_KEY -- encrypts GitHub tokens at rest (Fernet).
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# COMPASS_JWT_SECRET -- signs the session/OAuth-state cookies (HS256).
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**If `COMPASS_TOKEN_ENCRYPTION_KEY` is ever rotated or lost**, every
previously-stored `users.access_token_encrypted` value becomes permanently
undecryptable — those users simply need to log in (and, if they'd connected
private repos, reconnect via `scope=repo`) again; there's no migration path
for re-encrypting under a new key, since the plaintext token was never
retained anywhere to re-encrypt from. Store both secrets somewhere you can
retrieve them again (a password manager), not just in the Render dashboard —
losing `COMPASS_JWT_SECRET` just logs everyone out (harmless, they log back
in); losing `COMPASS_TOKEN_ENCRYPTION_KEY` is the one that actually costs
your users a re-connection step.

---

## 6. GitHub repository secrets (on this repo, for the workflows)

Repo → **Settings** → **Secrets and variables** → **Actions** → **New
repository secret**:

| Secret name | Value | Used by |
|---|---|---|
| `DATABASE_URL` | The same Neon pooled connection string from step 1, with `postgresql+psycopg://` scheme | `mine.yml`, `reaper.yml` |
| `COMPASS_TOKEN_ENCRYPTION_KEY` | The Fernet key from step 5 | `mine.yml` — `app/jobs/worker.py` needs this to decrypt a private repo owner's stored GitHub token via `resolve_clone_url`, since the worker resolves private clone URLs itself with no callback to the API (CLAUDE.md) |

The worker never needs a GitHub OAuth token or client secret of its own — it
only talks to Postgres, and decrypts what's already stored there.

---

## 7. Render environment variables (the web service)

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
| `GITHUB_CLIENT_ID` | The OAuth App's Client ID (step 4) |
| `GITHUB_CLIENT_SECRET` | The OAuth App's Client secret (step 4) |
| `GITHUB_OAUTH_REDIRECT_URI` | Must exactly match the OAuth App's callback URL (step 4), e.g. `https://compass-api.onrender.com/auth/github/callback` |
| `COMPASS_JWT_SECRET` | The value generated in step 5 |
| `COMPASS_TOKEN_ENCRYPTION_KEY` | The Fernet key generated in step 5 (same value as the repository secret in step 6) |
| `COMPASS_FRONTEND_URL` | Your Vercel deployment URL — same value as `FRONTEND_ORIGIN` above, used for building OAuth redirect URLs rather than for CORS matching |
| `COMPASS_ENV` | `production` — **required** for the app to refuse to start with a missing/invalid `COMPASS_TOKEN_ENCRYPTION_KEY` instead of silently deriving an ephemeral one |
| `COMPASS_SECRET_SCAN_SALT` | A random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"` — not startup-fatal like `COMPASS_TOKEN_ENCRYPTION_KEY` if left unset, but the shipped dev default is public (it's in this repo's `.env.example`), so set a real value here rather than deploying with it |
| `COMPASS_GEMINI_KEYS` | Comma-separated Google Gemini API key(s) — get one free at [Google AI Studio](https://aistudio.google.com/apikey) ("Create API key"). Optional: leave unset and the narrative layer (session 12, CLAUDE.md) just reports `{"available": false, "reason": "no_keys"}` everywhere — nothing else in Compass depends on it |
| `COMPASS_GROQ_KEYS` | Comma-separated Groq API key(s) — get one free at [console.groq.com/keys](https://console.groq.com/keys). Also optional, same fallback as above; configure either or both providers, or neither |
| `COMPASS_ADMIN_TOKEN` | A random string (same generation command as `COMPASS_SECRET_SCAN_SALT`) — gates `POST /internal/runs/{id}/pregenerate-narratives` (session 16's showcase-repo pre-generation). Unlike the salt above, leaving this unset makes that ONE endpoint permanently unreachable (503), never silently open, since it guards a real action rather than a fingerprint |

`ENV`, `COMPASS_WORKER_MODE`, `COMPASS_MAX_REPO_MB`,
`COMPASS_GEMINI_MODEL`/`COMPASS_GROQ_MODEL`, and the
`COMPASS_RATE_LIMIT_*`/`COMPASS_NARRATIVE_RATE_LIMIT_*`/
`COMPASS_MAX_CONCURRENT_RUNS` settings already have correct defaults in
`render.yaml` and don't need dashboard values unless you want to override
them.

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
`render.yaml`. **This same one-instance assumption is also why
`app/api/limits.py`'s rate limiter is safe as an in-memory, single-process
structure** — see that module's docstring before scaling beyond one instance
for either reason.

---

## 8. Set up the keep-alive ping

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

## 9. Vercel setup (frontend)

1. Import this repository into Vercel, with **Root Directory** set to
   `frontend/`.
2. Vercel auto-detects the Vite build (`npm run build`, output `dist/`).
   `frontend/vercel.json`'s SPA rewrite is already committed, so a deep link
   like `/repos/<uuid>/architecture` won't 404 on a hard refresh.
3. Set the environment variable `VITE_API_URL` to your Render service's
   public URL, e.g. `https://compass-api.onrender.com` (no trailing slash).
4. Deploy. Once it's live, go back to Render and set `FRONTEND_ORIGIN` **and**
   `COMPASS_FRONTEND_URL` (step 7) to this exact Vercel URL — CORS will
   reject the frontend's requests, and OAuth callbacks will redirect to the
   wrong place, until both match. Also update the OAuth App's **Homepage
   URL** (step 4) to match, if you used a placeholder earlier.

---

## 10. Verify it works

**The web app end-to-end:** open the Vercel URL, submit a small public
GitHub repo, and watch the repo page fill in stage by stage.

**Login end-to-end:** click "Log in with GitHub" — you should land on
GitHub's `read:user`-only consent screen (not `repo` scope; if you see a
`repo`-scope consent screen on the FIRST login, something is wrong — see
CLAUDE.md's two-step scope escalation note), approve, and land back on the
frontend logged in. Click "Connect private repositories" separately and
confirm THAT consent screen does ask for `repo` scope. Submit a private repo
you own and confirm it analyzes successfully; log out (or open a private/
incognito window) and confirm the same private repo's URL returns "Connect
private repositories to analyze it" instead of quietly succeeding.

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

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser console shows CORS errors | `FRONTEND_ORIGIN`/`COMPASS_CORS_ORIGINS` on Render doesn't match the Vercel URL exactly (scheme, no trailing slash) | Update the Render env var to the exact origin, redeploy |
| First request after idle takes 30–60s | Render free-tier cold start | Confirm the cron-job.org ping (step 8) is actually running and hitting `/health` every ≤14 minutes |
| API returns 500s referencing a missing column/table | Migration didn't run, or ran against the wrong database | Check the deploy's logs for the `alembic upgrade head` line (it runs as the first thing `dockerCommand` does, before uvicorn starts); confirm `DATABASE_URL` is set correctly on the service |
| Blueprint deploy fails with "pre-deploy command is not supported for free tier services" | `render.yaml` still has `preDeployCommand` set (a paid-tier-only field) instead of the free-tier-safe `dockerCommand` | Use the `dockerCommand` form already in this repo's `render.yaml`; only switch back to `preDeployCommand` if you upgrade off the free plan |
| `repository_dispatch` curl/API call returns `404` | Either `COMPASS_WORKER_REPO` is wrong, or the PAT's repository selection/Actions permission is wrong — **GitHub returns 404 for both cases, you cannot tell which from the status code alone** | Double-check `COMPASS_WORKER_REPO` is exactly `{owner}/{repo}` (case-sensitive) and that the PAT (step 3) has Actions: Read and write scoped to that exact repository |
| Dispatch succeeds (204) but no workflow run appears | `mine.yml` is not on the repository's **default branch** — `repository_dispatch` only ever triggers workflows defined on the default branch, silently, with no error | Merge `mine.yml`/`reaper.yml` to the default branch (usually `main`) |
| Runner OOM / killed mid-run | A very large repo, or a runner-level infra failure | `mine.yml`'s `if: failure()` step marks the run failed immediately; if it also died before that step could run, `reaper.yml` catches it within 15 minutes regardless |
| A repo's status is stuck showing "running" indefinitely | The runner died in a way neither `mine.yml`'s failure step nor (yet) `reaper.yml`'s 15-minute schedule has caught | Wait up to ~20 minutes for the next reaper run, or trigger it manually: **Actions** tab → **Reaper** → **Run workflow** |
| Repos over the size cap get accepted anyway | `check_github_repo_size` only checks github.com repos and doesn't block on its own API failures (rate limiting, network) by design — see its docstring | Not a bug to "fix" by making it stricter; if GitHub's API is unreachable the check is skipped rather than blocking a legitimate submission |
| GitHub OAuth login fails with `redirect_uri_mismatch` | `GITHUB_OAUTH_REDIRECT_URI` (Render) doesn't byte-for-byte match the OAuth App's **Authorization callback URL** (step 4) | Make both exactly the same string — scheme, host, path, no trailing slash |
| App refuses to start in production citing `COMPASS_TOKEN_ENCRYPTION_KEY` | The key is missing, empty, or not a valid Fernet key, and `COMPASS_ENV=production` | Generate one per step 5 and set it on the Render service; this check is intentional (`app/auth/crypto.py`) — do not "fix" it by unsetting `COMPASS_ENV` |
| A private repo's re-analysis fails with a token/decryption error | The repo owner's stored token was encrypted under a DIFFERENT `COMPASS_TOKEN_ENCRYPTION_KEY` than the one currently configured (the key was rotated) | The owner needs to reconnect private repositories (`scope=repo` login) to re-store a token under the current key — there's no way to recover the old one |
| `POST /repos` returns 429 | The per-IP/per-user rate limit or the global concurrency cap (`app/api/limits.py`) was hit | Expected behavior under load — the response's `Retry-After` header/detail message says when to retry; if this fires constantly under normal usage, the limits in `COMPASS_RATE_LIMIT_*`/`COMPASS_MAX_CONCURRENT_RUNS` may need raising |

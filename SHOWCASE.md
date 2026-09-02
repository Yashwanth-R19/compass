# Showcase repositories

Four repositories are pinned (`repos.is_showcase = True`) so a visitor to the
home page can click straight into a fully-analysed passport with no waiting —
see `CLAUDE.md`'s "Showcase mode" section for how pinning, public
readability, and eviction-exemption work mechanically, and
`backend/app/scripts/showcase.py` for the management command that produced
this page's numbers.

Every number below is real, read directly from the database after running
`python -m app.scripts.showcase add <url>` against each repository — nothing
here is invented or rounded for effect.

## Why these four, and why each one

| Repo | Rank | Chosen to prove |
|---|---|---|
| [`psf/requests`](https://github.com/psf/requests) | 1 | A large, mature Python project — deep history, real hotspots, and (unusually) high coupling for a library this well-regarded |
| [`ianstormtaylor/slate`](https://github.com/ianstormtaylor/slate) | 2 | The JavaScript/TypeScript analyzer, on a real multi-package React-ecosystem project (`slate`, `slate-react`, `slate-history`, ...) |
| [`spring-projects/spring-petclinic`](https://github.com/spring-projects/spring-petclinic) | 3 | The Java analyzer, on the canonical Spring Boot sample app — a real `@SpringBootApplication` `main()` method, so entry-point detection has something unambiguous to find |
| [`tartley/colorama`](https://github.com/tartley/colorama) | 4 | The small-repository story — few files, few contributors, where subsystem/module-level coupling (session 04) has to carry the insight rather than a large, rich file-level graph |

Together the set proves range across language (Python, TypeScript, Java),
size (293 to 4,881 commits), and team shape (single-maintainer to small
team) — not four variations on the same demo.

### The genuinely interesting findings

- **`psf/requests` — 50 detected circular-dependency cycles and 223 hidden
  dependencies, on a library most engineers assume is architecturally
  clean.** Health score 39.7/100, driven overwhelmingly by
  `hidden_dependency_count`/`cycle_count`, not by risk. This is the exact
  "wait, really?" moment the product exists to produce — a widely-trusted
  library that still has real, computable structural findings an AI reading
  the current tree would have no way to surface (they come from *how the
  code was actually written together over time*, via the change-coupling
  formula, not from reading any single file).
- **`tartley/colorama` — truck factor 1.** A single contributor's departure
  would orphan the majority of the codebase's expert coverage — an honest,
  slightly uncomfortable number for a library that ships inside `pip` itself
  and countless other tools' dependency trees. Session 05's knowledge-
  distribution framing ("the project's risk, not an individual's
  importance" — `plan/RULES.md` §11.4) is exactly the right way to present
  this.
- **`ianstormtaylor/slate` — also truck factor 1**, and 12 subsystems
  detected across its multi-package layout (`slate` / `slate-react` /
  `slate-history` / `slate-hyperscript` / `slate-dom`), a genuine test of
  whether Louvain community detection finds real package boundaries in a
  monorepo-shaped project rather than one undifferentiated blob.

## The secret check — done by hand, per repository

Session 16 Known Hazard #6 is explicit: this check is not optional, and a
showcase repository must never surface a live, unremediated credential. Every
one of the four repositories above was checked. `app/scripts/showcase.py`'s
`add` command always prints the full secrets picture (every hit still in
HEAD, every hit found only in deleted history) before pinning, and refuses to
pin outright if anything is still in HEAD unless `--confirm-no-live-secrets`
is passed *after* the operator has actually read the printed hits.

- **`ianstormtaylor/slate`, `spring-projects/spring-petclinic`,
  `tartley/colorama`** — zero hits, live or historical. Pinned with no
  override needed.
- **`psf/requests`** — the scanner flagged one hit still in HEAD
  (`private-key-pem`) and two in deleted history
  (`generic-high-entropy-assignment`). The live hit was inspected directly
  (path, commit, rule) before overriding:
  - Path: `tests/certs/expired/ca/ca-private.key`
  - This is a **deliberately expired test certificate authority's private
    key**, checked in specifically so `requests`' own test suite can
    exercise certificate-expiry handling — the directory name
    (`tests/certs/expired/`) and the key's own designated purpose both
    confirm this is a documented test fixture, not a real, exploitable
    credential. `requests` is one of the most widely used and heavily
    scrutinized libraries in the Python ecosystem; a genuine live secret in
    its `main` branch would not have gone unnoticed.
  - The two history-only hits are lower stakes by construction (they are
    not reachable from the current tree at all — the product's own
    still-in-head vs. history-only distinction, `app/security/scanner.py`),
    and were left as-is; they are a real, honest demonstration of what
    "secrets in deleted history" actually looks like on a real repository.
  - Pinned with `--confirm-no-live-secrets` only after this review.

No repository was pinned on the strength of "it's probably fine" — every
decision above is either zero hits, or a specific, checked, named file with a
stated reason it isn't a real credential.

## The numbers, as of pinning

| Repo | Commits | Subsystems | Truck factor | Health |
|---|---:|---:|---:|---:|
| `psf/requests` | 4,881 | 6 | 2 | 39.7 |
| `ianstormtaylor/slate` | 4,267 | 12 | 1 | 40.0 |
| `spring-projects/spring-petclinic` | 957 | 7 | 2 | 69.4 |
| `tartley/colorama` | 293 | 5 | 1 | 67.6 |

Total storage footprint for all four (Facts + Insight, Neon free tier, 0.5 GB
limit): **~60 MB (≈12%)** — comfortably inside budget with room for real user
submissions on top; see `GET /internal/storage` and `app/jobs/eviction.py`
for how storage stays bounded as more repositories are analysed.

## What was deliberately not done

- **A fifth repository was not added.** The session prompt allows 4–5;
  `tartley/colorama` already carries both the "small solo project" and
  "genuinely interesting finding" (truck factor 1) criteria at once, so a
  fifth repository would have added clone/analysis time without covering a
  genuinely new dimension the other four don't already show. If a future
  session wants a fifth (e.g. a GitLab-hosted repository, since all four
  here are GitHub), `python -m app.scripts.showcase add <url> --rank 5` is
  the entire mechanism needed.
- **Narrative pre-generation ran but produced nothing** — every surface
  (`passport`/`security`/the top 10 `risk_file`s per repo) reports
  `skipped ... no_keys`, because no `COMPASS_GEMINI_KEYS`/
  `COMPASS_GROQ_KEYS` were configured in the environment this session ran
  in. This is the system behaving exactly as designed for zero configured
  keys (`app/narrative/pool.py` — "the system works correctly with zero
  keys configured"), not a failure. **Before shipping**, configure at least
  one provider's key(s) and re-run
  `python -m app.scripts.showcase add <url> --rank N` for each of the four
  URLs above (idempotent — it re-analyses and re-pins, and
  `pregenerate_narratives` overwrites any stale cached row) so a real
  visitor never triggers a live LLM call, per session 16's own requirement.

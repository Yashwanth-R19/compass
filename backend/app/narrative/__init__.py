"""The narrative layer (session 12, Phase 14): an OPTIONAL phrasing pass over
already-computed metrics, using a rotating pool of free-tier LLM API keys.

Read ``master-context.md`` sec 10 and ``CLAUDE.md``'s "Narrative layer"
section before touching anything in this package -- the six rules stated
there are enforced IN CODE across this package's modules, not by convention:

1. The model only phrases facts already computed and already rendered on the
   same screen (structurally enforced by ``factpack.py``'s field-type
   allowlist -- a fact pack can never carry a score/rank/file-list/count/
   finding/recommendation that isn't a plain number, boolean, or a label from
   a fixed set).
2. Every narrative renders next to the metrics it describes, labelled as
   generated (frontend: ``components/NarrativeBlock.tsx``).
3. Every page is fully usable with narrative off.
4. Prompts contain only already-computed numbers for that repo -- never
   source, diffs, commit messages, or a token (``factpack.py`` again: the
   builders have no import path to ``app.ingestion``/``app.security``, so
   there is nothing to leak by construction).
5. Output is cached in Postgres against ``analysis_run_id`` (``narratives``
   table, ``app/db/models.py``).
6. On pool exhaustion the caller says "narrative unavailable" and renders the
   computed data as normal -- no fallback model, no retry storm
   (``pool.py``'s cooldown-based health tracking is what prevents the storm).

Modules: ``pool.py`` (the key pool + health tracking), ``providers.py``
(thin per-provider HTTP adapters), ``factpack.py`` (the fact-pack models and
their structural field-type allowlist), ``generate.py`` (prompting +
the output validator that makes rule 1 true in practice, not just in the
fact pack's shape).

**No stage in ``app/jobs/stages.py`` calls into this package.** Generation is
lazy, triggered only by ``GET /repos/{id}/narrative`` (or session 16's
pre-generation endpoint) -- the analysis pipeline itself makes zero LLM
calls. See generate.py's module docstring for why this is worth protecting.
"""

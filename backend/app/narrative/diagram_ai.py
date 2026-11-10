"""Optional AI labelling for the Map (``GET /repos/{id}/diagram/ai``).

On demand only: like ``generate.py``, nothing in ``app/jobs/`` imports this
module, so "the analysis pipeline contains no LLM call" stays literally
true. The model writes TEXT ONLY -- friendly group names, one-line captions,
a short summary, band names and arrow verbs -- for a diagram that
``app/analysis/diagram.py`` has already computed in full. It is never asked
to (and has no way to) add or remove a box or an arrow, and the Map is
complete and usable without any of this.

Every item the model returns is validated against the fact pack built from
that computed diagram; an invalid item is DROPPED, never repaired:

- group/band/edge references must exist in the fact pack;
- names and verbs must match tight shape rules (plain words, no digits);
- a caption may only mention file/folder/identifier tokens that belong to
  its own group, and may contain no digits at all;
- the summary goes through the narrative layer's own ``validate_output``
  (every number and identifier-like token must trace back to the facts).

Arrow verbs are the one inherently unprovable output (they're inferred from
names, not from code semantics); the UI marks them as suggestions.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.stopwords import STOPWORDS, tokenize_identifier
from app.db.models import Repo, RepoPath, Symbol
from app.jobs.log_redaction import redact
from app.narrative import pool, providers

# Private helpers reused deliberately: one grounding implementation for both
# AI surfaces, rather than a second copy that could drift from the first.
from app.narrative.generate import (
    _extract_identifier_like_tokens,
    _model_name_for,
    validate_output,
)
from app.schemas.diagram import (
    DiagramAiBandOut,
    DiagramAiEdgeVerbOut,
    DiagramAiGroupOut,
    DiagramAiPayload,
    DiagramResponse,
)

logger = logging.getLogger(__name__)

DIAGRAM_AI_MAX_TOKENS = 1600
DIAGRAM_AI_TIME_BUDGET_SECONDS = 9.0
"""A NEW provider attempt only starts while elapsed time is under this --
the provider timeout is 20s, so 9s + 20s stays under the API's 30s
request timeout (app/api/middleware.py)."""
MAX_KEY_ATTEMPTS = 4
MAX_TOP_PATHS_PER_GROUP = 12
MAX_SUBFOLDERS_PER_GROUP = 8
MAX_IDENTIFIERS_PER_GROUP = 10
MAX_IMPORT_FACTS = 30
MAX_HIDDEN_FACTS = 15
MAX_CAPTION_CHARS = 120
MAX_EDGE_VERBS = 30

_FRIENDLY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z &/\-]{0,31}$")
_BAND_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z &\-]{0,23}$")
_VERB_RE = re.compile(r"^[a-z]+( [a-z]+){0,2}$")
_DIGIT_RE = re.compile(r"\d")


class GroupFact(BaseModel):
    group_id: str
    computed_label: str
    file_count: int
    total_loc: int
    top_paths: list[str]
    subfolders: list[str]
    top_identifiers: list[str]
    entry_kinds: list[str]


class ImportFact(BaseModel):
    from_group: str
    to_group: str
    import_count: int


class HiddenFact(BaseModel):
    a: str
    b: str
    max_degree: float


class BandFact(BaseModel):
    layer: int
    kind: str
    group_ids: list[str]


class DiagramFactPack(BaseModel):
    """Deliberately NOT run through ``factpack.validate_factpack_allowlist``:
    unlike the repo narrative's numbers-only pack, captions need the
    repository's own vocabulary (paths, labels, identifiers). Safety here
    comes from OUTPUT validation -- every token the model writes must exist
    in this pack (see the module docstring)."""

    repo_name: str
    grouping: str
    groups: list[GroupFact]
    imports: list[ImportFact]
    hidden: list[HiddenFact]
    bands: list[BandFact]
    infra_labels: list[str]


SYSTEM_PROMPT = """You are labelling an architecture diagram that Compass has ALREADY computed from a
code repository's import graph and commit history. You do not draw anything: the
groups, layers and arrows are fixed. You only write short text for them.

Return ONLY a JSON object, no prose, no code fences, with exactly these keys:
{
  "summary": string,                       // 2-4 sentences, max 600 characters, about how the codebase is organised
  "groups": [{"group_id": string, "friendly_name": string, "caption": string}],
  "bands": [{"layer": integer, "name": string}],
  "edge_verbs": [{"from_group": string, "to_group": string, "verb": string}]
}

Rules, followed exactly:
- Use only group_id values, layer numbers and from_group/to_group pairs that appear in the facts.
- friendly_name: 1 to 4 plain words, no digits, no file names (e.g. "Analysis engines", "Web UI").
- caption: one sentence, at most 120 characters, no digits, describing the group's likely role.
  Only mention file or folder names that appear in that group's own top_paths or subfolders.
- band name: 1 to 3 plain words, no digits (e.g. "User interface", "Core logic", "Data access").
- verb: 1 to 3 lowercase words describing how from_group uses to_group (e.g. "calls", "renders with", "persists via").
  Only for pairs listed under imports.
- summary: do not introduce any number that is not in the facts; never calculate new numbers.
- Do not mention people, do not make recommendations, do not judge code quality.

Facts (JSON):
"""


def build_fact_pack(diagram: DiagramResponse, repo: Repo, db: Session) -> DiagramFactPack:
    files = diagram.files
    members: dict[str, list[int]] = {g.id: [] for g in diagram.groups}
    for f in files:
        members.setdefault(f.group_id, []).append(f.i)

    # Symbol names per live file, iterated in path then name order so the
    # Counter's tie-breaking below is deterministic.
    index_by_path = {f.path: f.i for f in files}
    symbols_by_index: dict[int, list[str]] = {}
    rows = db.execute(
        select(RepoPath.path, Symbol.name)
        .select_from(Symbol)
        .join(RepoPath, RepoPath.id == Symbol.path_id)
        .where(Symbol.repo_id == repo.id)
    ).all()
    for path, name in rows:
        i = index_by_path.get(path)
        if i is not None:
            symbols_by_index.setdefault(i, []).append(name)

    groups: list[GroupFact] = []
    for g in diagram.groups:
        idx = members.get(g.id, [])
        if diagram.grouping == "subsystem":
            ranked = sorted(idx, key=lambda i: (-(files[i].centrality or 0.0), files[i].path))
        else:
            ranked = sorted(idx, key=lambda i: (-files[i].loc, files[i].path))
        top_paths = [files[i].path for i in ranked[:MAX_TOP_PATHS_PER_GROUP]]

        sub_counts: Counter[str] = Counter()
        for i in idx:
            path = files[i].path
            rel = path[len(g.base_path) + 1 :] if g.base_path else path
            if "/" in rel:
                sub_counts[rel.split("/")[0]] += 1
        subfolders = [
            name
            for name, _ in sorted(sub_counts.items(), key=lambda kv: (-kv[1], kv[0]))[
                :MAX_SUBFOLDERS_PER_GROUP
            ]
        ]

        tokens: Counter[str] = Counter()
        for i in sorted(idx, key=lambda i: files[i].path):
            for name in sorted(symbols_by_index.get(i, [])):
                for token in tokenize_identifier(name):
                    if len(token) >= 3 and token not in STOPWORDS:
                        tokens[token] += 1
        top_identifiers = [t for t, _ in tokens.most_common(MAX_IDENTIFIERS_PER_GROUP)]

        groups.append(
            GroupFact(
                group_id=g.id,
                computed_label=g.label,
                file_count=g.file_count,
                total_loc=g.total_loc,
                top_paths=top_paths,
                subfolders=subfolders,
                top_identifiers=top_identifiers,
                entry_kinds=sorted({ep.kind for ep in g.entry_points}),
            )
        )

    imports = [
        ImportFact(from_group=e.source, to_group=e.target, import_count=e.import_count)
        for e in sorted(diagram.group_edges, key=lambda e: (-e.import_count, e.source, e.target))[
            :MAX_IMPORT_FACTS
        ]
    ]
    hidden = [
        HiddenFact(a=h.a, b=h.b, max_degree=round(h.max_degree, 2))
        for h in sorted(diagram.hidden_group_edges, key=lambda h: (-h.max_degree, h.a, h.b))[
            :MAX_HIDDEN_FACTS
        ]
    ]
    bands = [
        BandFact(layer=layer.index, kind=layer.kind, group_ids=layer.group_ids)
        for layer in diagram.layers
    ]
    return DiagramFactPack(
        repo_name=f"{repo.owner}/{repo.name}",
        grouping=diagram.grouping,
        groups=groups,
        imports=imports,
        hidden=hidden,
        bands=bands,
        infra_labels=[item.label for item in diagram.infra],
    )


def build_prompt(fact_pack: DiagramFactPack) -> str:
    return SYSTEM_PROMPT + json.dumps(fact_pack.model_dump(), sort_keys=True)


def parse_model_json(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.lstrip().lower().startswith("json"):
                raw = raw.lstrip()[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _allowed_tokens(group: GroupFact) -> set[str]:
    allowed: set[str] = {group.computed_label.lower()}
    for path in group.top_paths:
        p = PurePosixPath(path)
        allowed.add(path.lower())
        allowed.update(seg.lower() for seg in p.parts)
        allowed.add(p.name.lower())
        allowed.add(p.stem.lower())
    allowed.update(s.lower() for s in group.subfolders)
    allowed.update(t.lower() for t in group.top_identifiers)
    allowed.update(name.lower() for name in DiagramFactPack.model_fields)
    allowed.update(name.lower() for name in GroupFact.model_fields)
    return allowed


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"[\s/]+", text) if w])


def validate_payload(data: dict[str, Any], fact_pack: DiagramFactPack) -> DiagramAiPayload | None:
    """Item-by-item validation (see module docstring). ``None`` when nothing
    usable survived -- no summary AND no group item."""
    summary: str | None = None
    raw_summary = data.get("summary")
    if isinstance(raw_summary, str) and raw_summary.strip():
        ok, reason = validate_output(raw_summary.strip(), fact_pack)
        if ok:
            summary = raw_summary.strip()
        else:
            logger.info("diagram ai: summary dropped: reason=%s", reason)

    groups_by_id = {g.group_id: g for g in fact_pack.groups}
    seen_groups: set[str] = set()
    group_items: list[DiagramAiGroupOut] = []
    raw_groups = data.get("groups")
    for item in raw_groups if isinstance(raw_groups, list) else []:
        if not isinstance(item, dict):
            continue
        gid = item.get("group_id")
        if not isinstance(gid, str) or gid not in groups_by_id or gid in seen_groups:
            continue
        seen_groups.add(gid)

        friendly: str | None = None
        raw_name = item.get("friendly_name")
        if isinstance(raw_name, str):
            name = raw_name.strip()
            if _FRIENDLY_NAME_RE.match(name) and _word_count(name) <= 4:
                friendly = name

        caption: str | None = None
        raw_caption = item.get("caption")
        if isinstance(raw_caption, str):
            text = raw_caption.strip()
            if text and len(text) <= MAX_CAPTION_CHARS and not _DIGIT_RE.search(text):
                allowed = _allowed_tokens(groups_by_id[gid])
                tokens = [t.strip(".,;:()").lower() for t in _extract_identifier_like_tokens(text)]
                if all(t in allowed for t in tokens):
                    caption = text

        if friendly is not None or caption is not None:
            group_items.append(
                DiagramAiGroupOut(group_id=gid, friendly_name=friendly, caption=caption)
            )

    layers = {b.layer for b in fact_pack.bands}
    seen_layers: set[int] = set()
    bands: list[DiagramAiBandOut] = []
    raw_bands = data.get("bands")
    for item in raw_bands if isinstance(raw_bands, list) else []:
        if not isinstance(item, dict):
            continue
        layer = item.get("layer")
        raw_band_name = item.get("name")
        band_name = raw_band_name.strip() if isinstance(raw_band_name, str) else ""
        if (
            isinstance(layer, int)
            and not isinstance(layer, bool)
            and layer in layers
            and layer not in seen_layers
            and _BAND_NAME_RE.match(band_name)
            and _word_count(band_name) <= 3
        ):
            seen_layers.add(layer)
            bands.append(DiagramAiBandOut(layer=layer, name=band_name))

    import_pairs = {(f.from_group, f.to_group) for f in fact_pack.imports}
    seen_edges: set[tuple[str, str]] = set()
    verbs: list[DiagramAiEdgeVerbOut] = []
    raw_verbs = data.get("edge_verbs")
    for item in raw_verbs if isinstance(raw_verbs, list) else []:
        if len(verbs) >= MAX_EDGE_VERBS:
            break
        if not isinstance(item, dict):
            continue
        a, b, verb = item.get("from_group"), item.get("to_group"), item.get("verb")
        if not (isinstance(a, str) and isinstance(b, str) and isinstance(verb, str)):
            continue
        verb = verb.strip()
        pair = (a, b)
        if (
            pair in import_pairs
            and pair not in seen_edges
            and len(verb) <= 20
            and _VERB_RE.match(verb)
        ):
            seen_edges.add(pair)
            verbs.append(DiagramAiEdgeVerbOut(from_group=a, to_group=b, verb=verb))

    if summary is None and not group_items:
        return None
    return DiagramAiPayload(
        summary=summary,
        groups=sorted(group_items, key=lambda g: g.group_id),
        bands=sorted(bands, key=lambda b: b.layer),
        edge_verbs=sorted(verbs, key=lambda v: (v.from_group, v.to_group)),
    )


@dataclass
class DiagramAiResult:
    ok: bool
    payload: DiagramAiPayload | None
    provider: str | None
    model: str | None
    reason: str | None  # "no_keys" | "pool_exhausted" | "rejected"


def _call_provider(key: pool.ProviderKey, prompt: str) -> str | None:
    try:
        text = providers.generate(prompt, key, DIAGRAM_AI_MAX_TOKENS)
    except providers.ProviderError as exc:
        pool.report_failure(key, exc.kind)
        logger.warning(
            "diagram ai provider failure: provider=%s kind=%s detail=%s",
            key.provider,
            exc.kind,
            redact(str(exc)),
        )
        return None
    pool.report_success(key)
    return text


def generate_diagram_ai(fact_pack: DiagramFactPack) -> DiagramAiResult:
    """Same discipline as ``generate.generate_narrative`` (no fallback model,
    no retry storm), plus a wall-clock budget so a slow provider can never
    push the request past the API's own timeout."""
    if not pool.has_any_keys():
        return DiagramAiResult(False, None, None, None, "no_keys")

    prompt = build_prompt(fact_pack)
    start = time.monotonic()
    any_success = False

    def _out_of_time() -> bool:
        return time.monotonic() - start >= DIAGRAM_AI_TIME_BUDGET_SECONDS

    for _ in range(MAX_KEY_ATTEMPTS):
        if _out_of_time():
            break
        key = pool.get_key()
        if key is None:
            break
        text = _call_provider(key, prompt)
        if text is None:
            continue
        any_success = True
        for attempt in range(2):
            if attempt == 1:
                if _out_of_time():
                    return DiagramAiResult(False, None, None, None, "rejected")
                text = _call_provider(key, prompt)
                if text is None:
                    return DiagramAiResult(False, None, None, None, "rejected")
            parsed = parse_model_json(text)
            payload = validate_payload(parsed, fact_pack) if parsed is not None else None
            if payload is not None:
                return DiagramAiResult(
                    True, payload, key.provider, _model_name_for(key.provider), None
                )
            logger.warning("diagram ai generation rejected: attempt=%s", attempt + 1)
        return DiagramAiResult(False, None, None, None, "rejected")

    return DiagramAiResult(False, None, None, None, "rejected" if any_success else "pool_exhausted")


__all__ = [
    "DiagramAiResult",
    "DiagramFactPack",
    "build_fact_pack",
    "build_prompt",
    "generate_diagram_ai",
    "parse_model_json",
    "validate_payload",
]

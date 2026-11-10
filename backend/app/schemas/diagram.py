"""Response models for the Map surface (``GET /repos/{id}/diagram`` and
``GET /repos/{id}/diagram/ai``).

The diagram payload is a pure, read-time aggregation of already-persisted
Facts/Insight rows (see ``app/analysis/diagram.py``) -- every group, band,
arrow and infrastructure box in it is computed. The AI models at the bottom
of this module only ever carry TEXT for those computed elements (names,
captions, a summary, band names, arrow verbs); nothing in them can add or
remove a box or an arrow.
"""

import uuid
from typing import Literal

from pydantic import BaseModel

DiagramGrouping = Literal["subsystem", "folder"]
LayerKind = Literal["actor", "surface", "middle", "foundation", "connected", "standalone", "infra"]
InfraCategory = Literal["container", "deploy", "ci", "datastore"]


class DiagramSourceOut(BaseModel):
    host: Literal["github", "gitlab", "other"]
    head_sha: str | None
    # Both always end with "/" when not None -- the client appends a path.
    blob_base_url: str | None
    tree_base_url: str | None


class DiagramFileOut(BaseModel):
    i: int
    path: str
    group_id: str
    loc: int
    churn_365d: int
    commit_count: int
    last_changed: int
    language: str
    is_test: bool
    centrality: float | None


class DiagramEntryPointOut(BaseModel):
    file_index: int
    path: str
    kind: str
    evidence: str
    confidence: float


class DiagramGroupOut(BaseModel):
    id: str
    label: str
    label_source: str
    base_path: str
    layer: int
    file_count: int
    total_loc: int
    churn_365d: int
    commit_count: int
    last_changed: int
    cohesion: float | None
    internal_edges: int | None
    external_edges: int | None
    entry_points: list[DiagramEntryPointOut]
    in_group_cycle: bool
    folded_count: int


class DiagramGroupEdgeOut(BaseModel):
    source: str
    target: str
    import_count: int
    in_file_cycle: bool
    in_group_cycle: bool


class DiagramHiddenGroupEdgeOut(BaseModel):
    a: str
    b: str
    pair_count: int
    max_degree: float
    total_shared_revs: int


class DiagramHiddenPairOut(BaseModel):
    a: int
    b: int
    degree: float
    shared_revs: int


class DiagramLayerOut(BaseModel):
    index: int
    kind: LayerKind
    label: str
    group_ids: list[str]


class DiagramInfraOut(BaseModel):
    id: str
    category: InfraCategory
    label: str
    evidence: list[str]
    paths: list[str]
    runs_group_ids: list[str]


class DiagramActorOut(BaseModel):
    id: str
    label: str
    group_ids: list[str]
    entry_kinds: list[str]


class DiagramStatsOut(BaseModel):
    file_count: int
    group_count: int
    import_edge_count: int
    hidden_pair_count: int
    cycle_count: int
    imports_truncated: bool
    other_folded_count: int


class DiagramCapsOut(BaseModel):
    max_top_groups: int
    max_children_visible: int
    max_import_edges: int
    folder_split_dominance: float
    folder_min_groups: int


class DiagramResponse(BaseModel):
    repo_id: uuid.UUID
    run_id: uuid.UUID
    grouping: DiagramGrouping
    facts_archived: bool
    source: DiagramSourceOut
    groups: list[DiagramGroupOut]
    group_edges: list[DiagramGroupEdgeOut]
    hidden_group_edges: list[DiagramHiddenGroupEdgeOut]
    layers: list[DiagramLayerOut]
    infra: list[DiagramInfraOut]
    actor: DiagramActorOut | None
    files: list[DiagramFileOut]
    # [from_index, to_index] -- "from" imports "to".
    imports: list[list[int]]
    hidden_pairs: list[DiagramHiddenPairOut]
    cycles: list[list[int]]
    stats: DiagramStatsOut
    caps: DiagramCapsOut


class DiagramAiGroupOut(BaseModel):
    group_id: str
    friendly_name: str | None
    caption: str | None


class DiagramAiBandOut(BaseModel):
    layer: int
    name: str


class DiagramAiEdgeVerbOut(BaseModel):
    from_group: str
    to_group: str
    verb: str


class DiagramAiPayload(BaseModel):
    """Exactly what gets cached (as JSON) in ``narratives.content`` for
    ``surface="diagram"`` rows -- already validated, item by item."""

    summary: str | None
    groups: list[DiagramAiGroupOut]
    bands: list[DiagramAiBandOut]
    edge_verbs: list[DiagramAiEdgeVerbOut]


DiagramAiUnavailableReason = Literal["no_keys", "pool_exhausted", "rejected", "disabled"]


class DiagramAiResponse(BaseModel):
    available: bool
    reason: DiagramAiUnavailableReason | None = None
    provider: str | None = None
    model: str | None = None
    generated_at: str | None = None
    grouping: DiagramGrouping
    payload: DiagramAiPayload | None = None

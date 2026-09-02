"""The evolution scrubber's data source (session 13, Part D) -- mirrors
``app/engines/timeline.py``'s per-snapshot ``metrics`` JSONB payload. Kept in
its own file, matching the precedent ``app/schemas/{share,narrative}.py``
already set for a self-contained feature.
"""

import uuid

from pydantic import BaseModel


class TimelineCouplingPairOut(BaseModel):
    path_a: str
    path_b: str
    shared_revs: int
    coupling_degree: float


class TimelineHotspotOut(BaseModel):
    """One entry in a snapshot's ``churn_ranked_hotspots`` -- deliberately
    NOT called "risk": this is churn alone, since complexity at a historical
    revision was never measured (see app/engines/timeline.py's module
    docstring, the HONESTY CONSTRAINT)."""

    path: str
    churn_to_date: int


class TimelineContributorShareOut(BaseModel):
    name: str
    commits: int
    share: float


class TimelineSnapshotOut(BaseModel):
    position: int
    commit_sha: str
    at_date: str
    commit_index: int
    file_count: int
    churn_to_date: int
    commits_to_date: int
    active_contributors: int
    contributor_shares: list[TimelineContributorShareOut]
    coupling_pairs_count: int
    top_coupling_pairs: list[TimelineCouplingPairOut]
    churn_ranked_hotspots: list[TimelineHotspotOut]


class TimelineMetricBounds(BaseModel):
    min: float
    max: float


class TimelineBounds(BaseModel):
    """Global min/max for every animatable metric, computed ONCE here from
    the same snapshot rows the response embeds (Part D: "the frontend must
    not compute these per frame; the backend supplying them is what
    guarantees the fixed scale") -- same "the client never derives its own
    scale" contract CityBounds already established (app/schemas/analysis.py).
    ``hotspot_churn`` is the bound the fixed-axis hotspot BAR CHART needs
    specifically -- min/max across every file in every snapshot's
    churn_ranked_hotspots, not just the current one being displayed."""

    file_count: TimelineMetricBounds
    churn_to_date: TimelineMetricBounds
    commits_to_date: TimelineMetricBounds
    active_contributors: TimelineMetricBounds
    coupling_pairs_count: TimelineMetricBounds
    hotspot_churn: TimelineMetricBounds


class TimelineResolution(BaseModel):
    history: int


class TimelineResponse(BaseModel):
    repo_id: uuid.UUID
    snapshots: list[TimelineSnapshotOut]
    bounds: TimelineBounds
    resolution: TimelineResolution
    covers: list[str]
    not_covered: str

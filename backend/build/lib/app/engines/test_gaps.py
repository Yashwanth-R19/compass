"""Test gap analysis (session 07, Part C): this measures test MAINTENANCE
-- whether a file's mapped tests keep changing alongside it -- never test
COVERAGE or QUALITY. A repository with an integration-test-only strategy, or
one whose tests are simply well-written and rarely need touching, will look
worse here than it actually is; mapping itself is best-effort (see
`_mirrored_candidate` below). The word surfaced anywhere near this feature's
output must be "maintenance", never "untested code" or "coverage" -- see
`app/api/analysis.py::TEST_GAP_LIMITATION_NOTE`, attached to every
`/test-gaps` response, not just documented here.

`files.is_test` (session 03's shared classifier,
app/ingestion/persist.py::classify_is_test) is the ONE source of truth for
"is this a test file" -- this module never re-derives it.
"""

from __future__ import annotations

import uuid
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from sqlalchemy import bindparam, insert, select, update
from sqlalchemy.orm import Session

from app.db.models import Commit, Dependency, File, FileMetrics, Finding, Severity
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.signature import finding_signature

if TYPE_CHECKING:
    from app.engines.context import RunContext

# ---- Config ----

MIN_COMMITS_FOR_STALE_CLASSIFICATION = 5
"""Known Hazard #6: test_cochange_ratio on a file with 1-2 commits is either
0.0 or 1.0 and meaningless either way. A file below this floor is never
classified "stale_test" (it falls through to "tracked" instead, benefit of
the doubt) and is excluded from the repo-level mean_test_cochange_ratio."""

STALE_TEST_RATIO_THRESHOLD = 0.2

TEST_GAP_RISK_QUARTILE = 0.75
"""HEURISTIC (plan/RULES.md sec 3): "top quartile of risk_score" for the
flagship finding -- the 75th percentile of this run's own risk_score
distribution, same within-run relative-cutoff technique
app/engines/expertise.py's orphaned_knowledge finding already uses (a
simple, hand-rolled percentile, not statistics.quantiles, which raises
below 2 data points)."""

MAX_TEST_GAP_FINDINGS = 8
TEST_GAP_SEVERITY = Severity.med
TEST_GAP_CONFIDENCE = 0.7


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(fraction * (len(sorted_values) - 1))
    return sorted_values[idx]


_JAVA_TEST_SUFFIXES = ("Tests", "Test", "IT")


def _mirrored_candidate(path: str, language: str) -> tuple[str, str] | None:
    """Session 07 Part C.2.a: the mirrored non-test path a test file's own
    naming convention points at, plus the bare stem to use for the
    repo-wide fallback (Known Hazard #5). Returns None when `path` doesn't
    match any known convention for its language -- never a guess."""
    p = PurePosixPath(path)
    stem, suffix = p.stem, p.suffix

    if language == "python":
        if stem.startswith("test_"):
            candidate_stem = stem[len("test_") :]
        elif stem.endswith("_test"):
            candidate_stem = stem[: -len("_test")]
        else:
            return None
        if not candidate_stem:
            return None
        mirrored = p.parent / f"{candidate_stem}{suffix}"
        return str(mirrored), candidate_stem

    if language in ("javascript", "typescript"):
        name = p.name
        for infix in (".test.", ".spec."):
            if infix in name:
                candidate_name = name.replace(infix, ".", 1)
                mirrored = p.parent / candidate_name
                return str(mirrored), PurePosixPath(candidate_name).stem
        return None

    if language == "java":
        matched_suffix = next((s for s in _JAVA_TEST_SUFFIXES if stem.endswith(s)), None)
        if matched_suffix is None:
            return None
        candidate_stem = stem[: -len(matched_suffix)]
        if not candidate_stem:
            return None
        parts = list(p.parts)
        # src/test/java/... -> src/main/java/... (session 07 spec's
        # explicit example); a Java test NOT under that exact convention
        # keeps the same directory, only the filename stem changes.
        if len(parts) >= 2 and parts[0] == "src" and parts[1] == "test":
            parts = ["src", "main", *parts[2:]]
        mirrored_parent = PurePosixPath(*parts[:-1]) if len(parts) > 1 else PurePosixPath()
        mirrored = mirrored_parent / f"{candidate_stem}.java"
        return str(mirrored), candidate_stem

    return None


def _naming_mapped_source(
    test_file: File,
    path_id_by_path: dict[str, int],
    stem_index: dict[tuple[str, str], list[int]],
) -> int | None:
    """Session 07 Known Hazard #5: resolve within the mirrored directory
    structure FIRST (exact path match); only fall back to a repo-wide
    unique-stem match when EXACTLY ONE candidate exists. Never pick one of
    several -- a conservative resolver refuses rather than guesses, same
    discipline as every import/entry-point resolver in this codebase."""
    candidate = _mirrored_candidate(test_file.path, test_file.language)
    if candidate is None:
        return None
    mirrored_path, candidate_stem = candidate

    direct = path_id_by_path.get(mirrored_path)
    if direct is not None:
        return direct

    fallback = stem_index.get((test_file.language, candidate_stem), [])
    if len(fallback) == 1:
        return fallback[0]
    return None


def _load_mapped_tests_by_source(
    repo_id: uuid.UUID, test_files: list[File], source_files: list[File], session: Session
) -> dict[int, set[int]]:
    """Union of the two independent mapping methods (Part C.2), keyed by
    SOURCE path_id -> set of mapped TEST path_ids. Keeping both methods
    (rather than picking whichever fires first) means a file counts as
    "has a mapped test" if EITHER method found one."""
    path_id_by_path = {f.path: f.path_id for f in source_files}
    stem_index: dict[tuple[str, str], list[int]] = {}
    for f in source_files:
        stem_index.setdefault((f.language, PurePosixPath(f.path).stem), []).append(f.path_id)

    mapped_tests_by_source: dict[int, set[int]] = {}

    # (a) naming convention
    for t in test_files:
        source_path_id = _naming_mapped_source(t, path_id_by_path, stem_index)
        if source_path_id is not None:
            mapped_tests_by_source.setdefault(source_path_id, set()).add(t.path_id)

    # (b) structural: a dependencies edge FROM a test file TO a non-test file
    test_path_ids = {t.path_id for t in test_files}
    source_path_ids = {f.path_id for f in source_files}
    edge_rows = session.execute(
        select(Dependency.from_path_id, Dependency.to_path_id).where(
            Dependency.repo_id == repo_id, Dependency.from_path_id.in_(test_path_ids)
        )
    ).all()
    for from_id, to_id in edge_rows:
        if to_id in source_path_ids:
            mapped_tests_by_source.setdefault(to_id, set()).add(from_id)

    return mapped_tests_by_source


def compute_test_gaps(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session
) -> tuple[dict[int, dict[str, Any]], float, float]:
    """Pure computation (no writes): returns
    (result_by_source_path_id, test_file_ratio, mean_test_cochange_ratio).
    Each result dict has "classification"/"test_cochange_ratio"/
    "mapped_test_path_ids". Exposed as a standalone function (matching every
    other engine's compute_*/Engine.run split) so the API layer or tests can
    call it directly without a session-scoped RunContext.
    """
    files = session.scalars(
        select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
    ).all()
    test_files = [f for f in files if f.is_test]
    source_files = [f for f in files if not f.is_test]

    test_file_ratio = (len(test_files) / len(source_files)) if source_files else 0.0

    mapped_tests_by_source = _load_mapped_tests_by_source(
        repo_id, test_files, source_files, session
    )

    # Co-change: one pass over every commit, counting -- for each source
    # file with mapped tests -- how many of the commits touching it ALSO
    # touch at least one of its mapped tests.
    commits = session.execute(
        select(Commit.changed_path_ids).where(Commit.repo_id == repo_id)
    ).all()
    touch_count: Counter[int] = Counter()
    cochange_count: Counter[int] = Counter()
    for (changed_path_ids,) in commits:
        changed_set = set(changed_path_ids)
        for path_id in changed_set:
            tests = mapped_tests_by_source.get(path_id)
            if tests is None:
                continue
            touch_count[path_id] += 1
            if changed_set & tests:
                cochange_count[path_id] += 1

    commit_count_by_path = {f.path_id: f.commit_count for f in source_files}

    result: dict[int, dict[str, Any]] = {}
    ratios_for_mean: list[float] = []
    for f in source_files:
        mapped = mapped_tests_by_source.get(f.path_id, set())
        if not mapped:
            result[f.path_id] = {
                "classification": "no_test",
                "test_cochange_ratio": None,
                "mapped_test_path_ids": [],
            }
            continue

        touches = touch_count.get(f.path_id, 0)
        ratio = (cochange_count.get(f.path_id, 0) / touches) if touches else 0.0
        commit_count = commit_count_by_path.get(f.path_id, 0)

        # Known Hazard #6: below the commit floor, a ratio is meaningless --
        # never classify "stale_test" from it, fall through to "tracked".
        if (
            ratio < STALE_TEST_RATIO_THRESHOLD
            and commit_count >= MIN_COMMITS_FOR_STALE_CLASSIFICATION
        ):
            classification = "stale_test"
        else:
            classification = "tracked"

        if commit_count >= MIN_COMMITS_FOR_STALE_CLASSIFICATION:
            ratios_for_mean.append(ratio)

        result[f.path_id] = {
            "classification": classification,
            "test_cochange_ratio": ratio,
            "mapped_test_path_ids": sorted(mapped),
        }

    mean_ratio = sum(ratios_for_mean) / len(ratios_for_mean) if ratios_for_mean else 0.0
    return result, test_file_ratio, mean_ratio


def _test_gap_findings(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    result_by_path: dict[int, dict[str, Any]],
    path_map: dict[int, str],
    session: Session,
) -> list[dict[str, Any]]:
    """Part C.5, the finding that matters: intersect no_test/stale_test with
    the top risk quartile for this run. Requires RiskEngine to have already
    run for this run_id (TestGapEngine runs last in the "risk" stage)."""
    risk_rows = session.execute(
        select(FileMetrics.path_id, FileMetrics.risk_score).where(
            FileMetrics.analysis_run_id == run_id
        )
    ).all()
    risk_by_path = {row.path_id: row.risk_score for row in risk_rows if row.risk_score is not None}
    if not risk_by_path:
        return []
    risk_threshold = _percentile(sorted(risk_by_path.values()), TEST_GAP_RISK_QUARTILE)

    candidates: list[dict[str, Any]] = []
    for path_id, info in result_by_path.items():
        if info["classification"] not in ("no_test", "stale_test"):
            continue
        risk_score = risk_by_path.get(path_id)
        if risk_score is None or risk_score < risk_threshold:
            continue
        path = path_map[path_id]

        if info["classification"] == "no_test":
            detail = (
                f"This file is in the top quartile of risk (risk_score={risk_score:.2f}) "
                "and has no test mapped to it by naming convention or import edge."
            )
        else:
            ratio = info["test_cochange_ratio"] or 0.0
            detail = (
                f"This file is in the top quartile of risk (risk_score={risk_score:.2f}) "
                f"and its mapped test has changed alongside it in only "
                f"{ratio:.0%} of the commits that touched it -- the test may be stale."
            )

        candidates.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "test_gap",
                "severity": TEST_GAP_SEVERITY,
                "confidence": TEST_GAP_CONFIDENCE,
                "path_id": path_id,
                "evidence_sha": None,
                "title": f"Test maintenance gap: {path}",
                "detail": detail,
                "signature": finding_signature("test_gap", path),
                "_risk_score": risk_score,
            }
        )

    candidates.sort(key=lambda f: f["_risk_score"], reverse=True)
    candidates = candidates[:MAX_TEST_GAP_FINDINGS]
    for rank, f in enumerate(candidates):
        f["rank"] = rank
        del f["_risk_score"]
    return candidates


class TestGapEngine(Engine):
    """Test gap / maintenance analysis (session 07, Part C). Runs LAST in
    the "risk" stage (app/jobs/stages.py: RiskEngine -> HygieneEngine ->
    TestGapEngine) -- like HygieneEngine, UPDATES the ``file_metrics`` rows
    RiskEngine already inserted, never a second insert.
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id

        result_by_path, test_file_ratio, mean_ratio = compute_test_gaps(repo_id, run_id, session)

        if result_by_path:
            update_rows = [
                {
                    "b_path_id": path_id,
                    "b_classification": info["classification"],
                    "b_ratio": info["test_cochange_ratio"],
                    "b_mapped": info["mapped_test_path_ids"],
                }
                for path_id, info in result_by_path.items()
            ]
            session.execute(
                update(FileMetrics)
                .where(
                    FileMetrics.analysis_run_id == run_id,
                    FileMetrics.path_id == bindparam("b_path_id"),
                )
                .values(
                    test_classification=bindparam("b_classification"),
                    test_cochange_ratio=bindparam("b_ratio"),
                    mapped_test_path_ids=bindparam("b_mapped"),
                ),
                update_rows,
            )

        path_map = load_path_map(repo_id, session)
        findings = _test_gap_findings(repo_id, run_id, result_by_path, path_map, session)
        if findings:
            session.execute(insert(Finding), findings)

        classifications = Counter(info["classification"] for info in result_by_path.values())
        return {
            "files_scored": len(result_by_path),
            "no_test": classifications.get("no_test", 0),
            "stale_test": classifications.get("stale_test", 0),
            "tracked": classifications.get("tracked", 0),
            "test_file_ratio": test_file_ratio,
            "mean_test_cochange_ratio": mean_ratio,
            "findings_emitted": len(findings),
        }

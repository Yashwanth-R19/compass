"""session 14, Part D -- GET /repos/{id}/benchmark. Runs the real pipeline
against a tiny local fixture repo (same pattern as tests/test_ingestion.py)
so file_metrics/health/repo_passport rows genuinely exist, then checks the
corpus-comparison response shape and the honesty fields (n_repos/widened).
"""

import subprocess
import uuid
from pathlib import Path

from app.db.models import Baseline, Job, JobStatus, Repo, RepoStatus
from app.jobs.runner import run_ingestion_job


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_fixture_repo(root: Path) -> Path:
    repo_dir = root / "benchmark-fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    (repo_dir / "a.py").write_text("def foo():\n    return 1\n")
    _git(repo_dir, "add", "a.py")
    _git(repo_dir, "commit", "-m", "add a.py")

    (repo_dir / "b.py").write_text("def bar():\n    return 2\n")
    (repo_dir / "a.py").write_text("def foo():\n    if True:\n        return 1\n    return 0\n")
    _git(repo_dir, "add", "a.py", "b.py")
    _git(repo_dir, "commit", "-m", "fix foo and add b.py")

    return repo_dir


def test_benchmark_reports_percentiles_with_honesty_fields(tmp_path, db_session, client):
    fixture_repo = _init_fixture_repo(tmp_path)
    url = str(fixture_repo)

    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.flush()
    job = Job(repo_id=repo.id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job)
    db_session.commit()

    run_ingestion_job(repo.id, job.id, worker_mode="inline")
    db_session.refresh(repo)
    assert repo.status == RepoStatus.ready

    # Seed exactly one, well-powered corpus cell for "complexity" -- every
    # OTHER metric has no corpus row at all, so the response must show
    # widened=False/n_repos>0 for complexity and n_repos=0 for the rest.
    db_session.add(
        Baseline(
            id=uuid.uuid4(),
            metric="complexity",
            language="python",
            size_bucket="small",
            p10=0.5,
            p25=1.0,
            p50=1.5,
            p75=2.0,
            p90=3.0,
            n_repos=10,
            n_files=200,
        )
    )
    db_session.commit()

    resp = client.get(f"/repos/{repo.id}/benchmark")
    assert resp.status_code == 200
    body = resp.json()

    assert body["dominant_language"] == "python"
    metric_names = {m["metric"] for m in body["metrics"]}
    assert metric_names == {
        "complexity",
        "churn_weighted",
        "max_coupling_degree",
        "risk_score",
        "health_score",
        "onboarding_difficulty",
    }

    by_metric = {m["metric"]: m for m in body["metrics"]}
    complexity = by_metric["complexity"]
    assert complexity["n_repos"] == 10
    assert complexity["n_files"] == 200
    assert complexity["widened"] is False
    assert 0.0 <= complexity["percentile"] <= 1.0

    health = by_metric["health_score"]
    assert health["n_repos"] == 0
    assert health["widened"] is False


def test_benchmark_404_when_no_run_exists(client, db_session):
    repo = Repo(url="https://github.com/o/none", owner="o", name="none", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()

    resp = client.get(f"/repos/{repo.id}/benchmark")
    assert resp.status_code == 404

import json
import urllib.error
import uuid

import pytest
from fastapi import BackgroundTasks

from app.jobs import dispatch as dispatch_module


@pytest.fixture(autouse=True)
def _worker_repo_configured(monkeypatch):
    monkeypatch.setattr(dispatch_module.settings, "COMPASS_WORKER_REPO", "acme/compass-workers")
    monkeypatch.setattr(dispatch_module.settings, "COMPASS_WORKER_PAT", "fake-pat-for-tests")


def test_inline_mode_schedules_background_task(monkeypatch):
    monkeypatch.setattr(dispatch_module.settings, "COMPASS_WORKER_MODE", "inline")
    background_tasks = BackgroundTasks()

    repo_id, run_id = uuid.uuid4(), uuid.uuid4()
    mode = dispatch_module.dispatch_run(
        repo_id, run_id, session=None, background_tasks=background_tasks
    )

    assert mode == "inline"
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is dispatch_module.run_ingestion_job
    assert task.args == (repo_id, run_id)
    assert task.kwargs == {"worker_mode": "inline", "triggered_by_user_id": None}


def test_actions_mode_posts_dispatch_with_only_the_two_identifiers(monkeypatch):
    monkeypatch.setattr(dispatch_module.settings, "COMPASS_WORKER_MODE", "actions")

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Resp()

    monkeypatch.setattr(dispatch_module.urllib.request, "urlopen", fake_urlopen)

    background_tasks = BackgroundTasks()
    repo_id, run_id = uuid.uuid4(), uuid.uuid4()
    mode = dispatch_module.dispatch_run(
        repo_id, run_id, session=None, background_tasks=background_tasks
    )

    assert mode == "actions"
    assert len(background_tasks.tasks) == 0  # no inline fallback needed
    assert captured["url"] == "https://api.github.com/repos/acme/compass-workers/dispatches"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "event_type": "compass-mine",
        "client_payload": {"repo_id": str(repo_id), "run_id": str(run_id)},
    }
    # Only the two identifiers ever leave the process -- no token, no clone
    # URL, no repo URL, no user id in the payload.
    assert set(captured["body"]["client_payload"].keys()) == {"repo_id", "run_id"}
    # The PAT goes in the Authorization header, never the body.
    assert "fake-pat-for-tests" in captured["headers"]["Authorization"]


def test_failing_dispatch_falls_back_to_inline(monkeypatch):
    monkeypatch.setattr(dispatch_module.settings, "COMPASS_WORKER_MODE", "actions")

    def failing_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dispatch_module.urllib.request, "urlopen", failing_urlopen)

    background_tasks = BackgroundTasks()
    repo_id, run_id = uuid.uuid4(), uuid.uuid4()
    mode = dispatch_module.dispatch_run(
        repo_id, run_id, session=None, background_tasks=background_tasks
    )

    assert mode == "inline_fallback"
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.kwargs == {"worker_mode": "inline_fallback", "triggered_by_user_id": None}

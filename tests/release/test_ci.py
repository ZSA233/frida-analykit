from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from tests.release.constants import EXAMPLE_RELEASE_REF
from tests.support.paths import SCRIPTS_ROOT

import pytest


MODULE_PATH = SCRIPTS_ROOT / "release_ci.py"
SPEC = importlib.util.spec_from_file_location("release_ci_script", MODULE_PATH)
release_ci_script = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = release_ci_script
SPEC.loader.exec_module(release_ci_script)


def test_resolve_current_branch_rejects_detached_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        release_ci_script,
        "_run_checked",
        lambda command, *, cwd, capture_output=True: subprocess.CompletedProcess(command, 0, "HEAD\n", ""),
    )

    with pytest.raises(release_ci_script.ReleaseCiError, match="detached"):
        release_ci_script.resolve_current_branch(repo_root)


def test_trigger_ci_workflow_dispatches_ci_on_requested_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    calls: list[list[str]] = []

    def fake_run_checked(command, *, cwd, capture_output=True):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release_ci_script, "_run_checked", fake_run_checked)

    release_ci_script.trigger_ci_workflow(repo_root, EXAMPLE_RELEASE_REF)

    assert calls == [["gh", "workflow", "run", "CI", "--ref", EXAMPLE_RELEASE_REF]]


def test_find_matching_dispatched_run_prefers_same_sha() -> None:
    runs = [
        {
            "databaseId": 100,
            "event": "push",
            "headSha": "abc123",
            "url": "https://example.invalid/push",
        },
        {
            "databaseId": 101,
            "event": "workflow_dispatch",
            "headSha": "def456",
            "url": "https://example.invalid/other",
        },
        {
            "databaseId": 102,
            "event": "workflow_dispatch",
            "headSha": "abc123",
            "url": "https://example.invalid/match",
        },
    ]

    matched = release_ci_script.find_matching_dispatched_run(runs, head_sha="abc123")

    assert matched == runs[2]


def test_find_matching_dispatched_run_ignores_older_matching_dispatches() -> None:
    runs = [
        {
            "databaseId": 200,
            "event": "workflow_dispatch",
            "headSha": "abc123",
            "url": "https://example.invalid/old",
        },
        {
            "databaseId": 201,
            "event": "workflow_dispatch",
            "headSha": "abc123",
            "url": "https://example.invalid/new",
        },
    ]

    matched = release_ci_script.find_matching_dispatched_run(
        runs,
        head_sha="abc123",
        min_database_id=200,
    )

    assert matched == runs[1]


def test_wait_for_ci_run_polls_until_matching_dispatch_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    responses = iter(
        [
            [],
            [
                {
                    "databaseId": 123,
                    "event": "workflow_dispatch",
                    "headSha": "abc123",
                    "url": "https://example.invalid/run/123",
                }
            ],
        ]
    )

    monkeypatch.setattr(release_ci_script, "list_ci_runs", lambda repo_root, ref: next(responses))
    monkeypatch.setattr(release_ci_script.time, "sleep", lambda _: None)

    run = release_ci_script.wait_for_ci_run(
        repo_root,
        ref=EXAMPLE_RELEASE_REF,
        head_sha="abc123",
        timeout_seconds=10,
        poll_interval_seconds=0,
    )

    assert run["databaseId"] == 123


def test_wait_for_ci_run_ignores_stale_dispatch_run_with_same_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    responses = iter(
        [
            [
                {
                    "databaseId": 400,
                    "event": "workflow_dispatch",
                    "headSha": "abc123",
                    "url": "https://example.invalid/run/400",
                }
            ],
            [
                {
                    "databaseId": 400,
                    "event": "workflow_dispatch",
                    "headSha": "abc123",
                    "url": "https://example.invalid/run/400",
                },
                {
                    "databaseId": 401,
                    "event": "workflow_dispatch",
                    "headSha": "abc123",
                    "url": "https://example.invalid/run/401",
                },
            ],
        ]
    )

    monkeypatch.setattr(release_ci_script, "list_ci_runs", lambda repo_root, ref: next(responses))
    monkeypatch.setattr(release_ci_script.time, "sleep", lambda _: None)

    run = release_ci_script.wait_for_ci_run(
        repo_root,
        ref=EXAMPLE_RELEASE_REF,
        head_sha="abc123",
        min_database_id=400,
        timeout_seconds=10,
        poll_interval_seconds=0,
    )

    assert run["databaseId"] == 401


def test_main_uses_pre_dispatch_run_id_floor_for_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(release_ci_script.Path, "cwd", staticmethod(lambda: repo_root))
    monkeypatch.setattr(release_ci_script, "resolve_head_sha", lambda repo_root, ref: "abc123")
    monkeypatch.setattr(
        release_ci_script,
        "list_ci_runs",
        lambda repo_root, ref: [
            {
                "databaseId": 500,
                "event": "workflow_dispatch",
                "headSha": "abc123",
                "url": "https://example.invalid/run/500",
            }
        ],
    )

    seen: dict[str, object] = {}

    def fake_trigger(repo_root: Path, ref: str) -> None:
        seen["trigger"] = (repo_root, ref)

    def fake_wait(repo_root: Path, *, ref: str, head_sha: str, min_database_id: int, timeout_seconds: int = 90, poll_interval_seconds: int = 3):
        seen["wait"] = {
            "repo_root": repo_root,
            "ref": ref,
            "head_sha": head_sha,
            "min_database_id": min_database_id,
            "timeout_seconds": timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        }
        return {
            "databaseId": 501,
            "url": "https://example.invalid/run/501",
        }

    def fake_watch(repo_root: Path, run_id: int) -> None:
        seen["watch"] = (repo_root, run_id)

    monkeypatch.setattr(release_ci_script, "trigger_ci_workflow", fake_trigger)
    monkeypatch.setattr(release_ci_script, "wait_for_ci_run", fake_wait)
    monkeypatch.setattr(release_ci_script, "watch_ci_run", fake_watch)

    assert release_ci_script.main(["--ref", EXAMPLE_RELEASE_REF]) == 0
    assert seen["trigger"] == (repo_root, EXAMPLE_RELEASE_REF)
    assert seen["wait"] == {
        "repo_root": repo_root,
        "ref": EXAMPLE_RELEASE_REF,
        "head_sha": "abc123",
        "min_database_id": 500,
        "timeout_seconds": 90,
        "poll_interval_seconds": 3,
    }
    assert seen["watch"] == (repo_root, 501)
    captured = capsys.readouterr()
    assert "Watching CI run: https://example.invalid/run/501" in captured.out


def test_watch_ci_run_invokes_gh_run_watch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    calls: list[tuple[list[str], bool]] = []

    def fake_run_checked(command, *, cwd, capture_output=True):
        calls.append((command, capture_output))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release_ci_script, "_run_checked", fake_run_checked)

    release_ci_script.watch_ci_run(repo_root, 123)

    assert calls == [(["gh", "run", "watch", "123", "--exit-status"], False)]

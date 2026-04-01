from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

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

    release_ci_script.trigger_ci_workflow(repo_root, "release/v2.0.8")

    assert calls == [["gh", "workflow", "run", "CI", "--ref", "release/v2.0.8"]]


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
        ref="release/v2.0.8",
        head_sha="abc123",
        timeout_seconds=10,
        poll_interval_seconds=0,
    )

    assert run["databaseId"] == 123


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

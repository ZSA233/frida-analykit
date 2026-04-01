#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class ReleaseCiError(RuntimeError):
    pass


def _run_checked(
    command: list[str],
    *,
    cwd: Path,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=capture_output,
        text=True,
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if detail:
            raise ReleaseCiError(f"`{' '.join(command)}` failed: {detail}")
        raise ReleaseCiError(f"`{' '.join(command)}` failed")
    return result


def resolve_current_branch(repo_root: Path) -> str:
    result = _run_checked(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
    )
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        raise ReleaseCiError("Current repository state is detached; pass --ref explicitly")
    return branch


def resolve_head_sha(repo_root: Path, ref: str) -> str:
    result = _run_checked(["git", "rev-parse", ref], cwd=repo_root)
    sha = result.stdout.strip()
    if not sha:
        raise ReleaseCiError(f"Could not resolve git ref `{ref}`")
    return sha


def trigger_ci_workflow(repo_root: Path, ref: str) -> None:
    _run_checked(["gh", "workflow", "run", "CI", "--ref", ref], cwd=repo_root, capture_output=True)


def list_ci_runs(repo_root: Path, ref: str, *, limit: int = 20) -> list[dict[str, Any]]:
    result = _run_checked(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            "CI",
            "--branch",
            ref,
            "--limit",
            str(limit),
            "--json",
            "databaseId,headBranch,headSha,status,conclusion,event,url,displayTitle",
        ],
        cwd=repo_root,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseCiError(f"Failed to parse `gh run list` output: {exc}") from exc
    if not isinstance(payload, list):
        raise ReleaseCiError("`gh run list` did not return a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def find_matching_dispatched_run(runs: list[dict[str, Any]], *, head_sha: str) -> dict[str, Any] | None:
    for run in runs:
        if run.get("event") != "workflow_dispatch":
            continue
        if run.get("headSha") != head_sha:
            continue
        if not isinstance(run.get("databaseId"), int):
            continue
        return run
    return None


def wait_for_ci_run(
    repo_root: Path,
    *,
    ref: str,
    head_sha: str,
    timeout_seconds: int = 90,
    poll_interval_seconds: int = 3,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        run = find_matching_dispatched_run(list_ci_runs(repo_root, ref), head_sha=head_sha)
        if run is not None:
            return run
        time.sleep(poll_interval_seconds)
    raise ReleaseCiError(f"Timed out waiting for a CI workflow_dispatch run for `{ref}` at `{head_sha}`")


def watch_ci_run(repo_root: Path, run_id: int) -> None:
    _run_checked(["gh", "run", "watch", str(run_id), "--exit-status"], cwd=repo_root, capture_output=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger and watch the CI workflow for a release ref")
    parser.add_argument("--ref", help="Git ref to validate; defaults to the current branch")
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    try:
        ref = args.ref or resolve_current_branch(repo_root)
        head_sha = resolve_head_sha(repo_root, ref)
        print(f"Triggering CI for {ref} at {head_sha}")
        trigger_ci_workflow(repo_root, ref)
        run = wait_for_ci_run(repo_root, ref=ref, head_sha=head_sha)
        print(f"Watching CI run: {run['url']}")
        watch_ci_run(repo_root, int(run["databaseId"]))
        print(f"CI passed for {ref} at {head_sha}")
        return 0
    except ReleaseCiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

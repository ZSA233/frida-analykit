from __future__ import annotations

from ruamel.yaml import YAML

from tests.support.paths import REPO_ROOT


WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _load_release_workflow() -> dict:
    yaml = YAML(typ="safe")
    payload = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _job_step_runs(job: dict) -> list[str]:
    runs: list[str] = []
    for step in job.get("steps", []):
        run = step.get("run")
        if isinstance(run, str):
            runs.append(run)
    return runs


def test_release_workflow_orders_stable_publish_after_sync() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]

    assert jobs["publish_release"]["needs"] == "build"
    assert jobs["sync_stable"]["needs"] == "publish_release"
    assert jobs["publish_npm"]["needs"] == "sync_stable"


def test_release_workflow_sync_stable_job_only_syncs_branch_state() -> None:
    workflow = _load_release_workflow()
    sync_runs = "\n".join(_job_step_runs(workflow["jobs"]["sync_stable"]))

    assert "sync-stable-ref" in sync_runs
    assert "npm publish" not in sync_runs


def test_release_workflow_publish_npm_job_runs_after_stable_sync() -> None:
    workflow = _load_release_workflow()
    publish_runs = "\n".join(_job_step_runs(workflow["jobs"]["publish_npm"]))

    assert "npm publish" in publish_runs
    assert "sync-stable-ref" not in publish_runs


def test_release_workflow_push_only_jobs_do_not_run_for_dispatch() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]
    expected_if = "${{ github.event_name == 'push' }}"

    assert jobs["publish_release"]["if"] == expected_if
    assert jobs["sync_stable"]["if"] == expected_if
    assert jobs["publish_npm"]["if"] == expected_if

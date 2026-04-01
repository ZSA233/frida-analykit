import io
import json
import threading
import time
from pathlib import Path

import pytest

from frida_analykit.config import AppConfig
from frida_analykit.frontend import FrontendError, build_agent_bundle, load_frontend_project, start_watch


def _config(base_dir: Path, *, jsfile: str = "_agent.js") -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": jsfile,
            "server": {"host": "local"},
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(base_dir, source_path=base_dir / "config.yml")


def _write_package_json(project_dir: Path, *, scripts: dict[str, str]) -> None:
    (project_dir / "package.json").write_text(json.dumps({"scripts": scripts}), encoding="utf-8")


def test_load_frontend_project_defaults_to_config_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "workspace"
    config_dir.mkdir()
    project = load_frontend_project(_config(config_dir))

    assert project.project_dir == config_dir
    assert project.package_json == config_dir / "package.json"
    assert project.entrypoint == config_dir / "index.ts"
    assert project.bundle_path == (config_dir / "_agent.js").resolve()


def test_load_frontend_project_uses_explicit_override(tmp_path: Path) -> None:
    config_dir = tmp_path / "config-home"
    config_dir.mkdir()
    project_dir = tmp_path / "agent-home"
    project_dir.mkdir()

    project = load_frontend_project(_config(config_dir), project_dir=project_dir)

    assert project.project_dir == project_dir.resolve()
    assert project.bundle_path == (config_dir / "_agent.js").resolve()


def test_build_agent_bundle_requires_package_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("frida_analykit.frontend.shutil.which", lambda _: "/usr/bin/npm")
    project = load_frontend_project(_config(tmp_path))
    project.entrypoint.write_text('import "@zsa233/frida-analykit-agent/rpc"\n', encoding="utf-8")
    project.node_modules.mkdir()

    with pytest.raises(FrontendError, match="missing `package.json`"):
        build_agent_bundle(project)


def test_build_agent_bundle_requires_index_ts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("frida_analykit.frontend.shutil.which", lambda _: "/usr/bin/npm")
    project = load_frontend_project(_config(tmp_path))
    _write_package_json(tmp_path, scripts={"build": "frida-compile index.ts -o _agent.js -c"})
    project.node_modules.mkdir()

    with pytest.raises(FrontendError, match="missing `index.ts`"):
        build_agent_bundle(project)


def test_build_agent_bundle_requires_node_modules_without_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("frida_analykit.frontend.shutil.which", lambda _: "/usr/bin/npm")
    project = load_frontend_project(_config(tmp_path))
    _write_package_json(tmp_path, scripts={"build": "frida-compile index.ts -o _agent.js -c"})
    project.entrypoint.write_text('import "@zsa233/frida-analykit-agent/rpc"\n', encoding="utf-8")

    with pytest.raises(FrontendError, match="missing `node_modules`"):
        build_agent_bundle(project)


def test_build_agent_bundle_requires_expected_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("frida_analykit.frontend.shutil.which", lambda _: "/usr/bin/npm")
    project = load_frontend_project(_config(tmp_path))
    _write_package_json(tmp_path, scripts={"build": "frida-compile index.ts -o _agent.js -c"})
    project.entrypoint.write_text('import "@zsa233/frida-analykit-agent/rpc"\n', encoding="utf-8")
    project.node_modules.mkdir()

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("frida_analykit.frontend.subprocess.run", lambda *args, **kwargs: Result())

    with pytest.raises(FrontendError, match="does not exist"):
        build_agent_bundle(project)


def test_build_agent_bundle_runs_install_then_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("frida_analykit.frontend.shutil.which", lambda _: "/usr/bin/npm")
    project = load_frontend_project(_config(tmp_path))
    _write_package_json(
        tmp_path,
        scripts={
            "build": "frida-compile index.ts -o _agent.js -c",
            "watch": "frida-compile index.ts -o _agent.js -w",
        },
    )
    project.entrypoint.write_text('import "@zsa233/frida-analykit-agent/rpc"\n', encoding="utf-8")
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command: list[str], *, cwd: Path, capture_output: bool, text: bool, check: bool):
        calls.append(command)
        if command == ["npm", "install"]:
            (cwd / "node_modules").mkdir()
        if command == ["npm", "run", "build"]:
            (cwd / "_agent.js").write_text("// built\n", encoding="utf-8")
        return Result()

    monkeypatch.setattr("frida_analykit.frontend.subprocess.run", fake_run)

    bundle = build_agent_bundle(project, install=True)

    assert bundle == project.bundle_path
    assert calls == [["npm", "install"], ["npm", "run", "build"]]


def test_start_watch_waits_for_first_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("frida_analykit.frontend.shutil.which", lambda _: "/usr/bin/npm")
    project = load_frontend_project(_config(tmp_path))
    _write_package_json(tmp_path, scripts={"watch": "frida-compile index.ts -o _agent.js -w"})
    project.entrypoint.write_text('import "@zsa233/frida-analykit-agent/rpc"\n', encoding="utf-8")
    project.node_modules.mkdir()

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.stdout = io.StringIO("")

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

        def terminate(self) -> None:
            self.returncode = 0

        def kill(self) -> None:
            self.returncode = -9

    fake_process = FakeProcess()
    monkeypatch.setattr("frida_analykit.frontend.subprocess.Popen", lambda *args, **kwargs: fake_process)

    def write_bundle() -> None:
        time.sleep(0.1)
        (tmp_path / "_agent.js").write_text("// watched\n", encoding="utf-8")

    worker = threading.Thread(target=write_bundle, daemon=True)
    worker.start()

    watcher = start_watch(project)
    try:
        assert watcher.wait_until_ready(timeout=1) == project.bundle_path
    finally:
        watcher.close()

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping

from .config import AppConfig
from .diagnostics import format_command, verbose_echo

WATCH_READY_TIMEOUT_SECONDS = 30.0
WATCH_POLL_INTERVAL_SECONDS = 0.2
OUTPUT_TAIL_LINES = 40


class FrontendError(RuntimeError):
    """Raised when the agent build workspace is missing or unusable."""


@dataclass(frozen=True)
class FrontendProject:
    config: AppConfig
    config_path: Path
    project_dir: Path
    package_json: Path
    entrypoint: Path
    bundle_path: Path

    @property
    def node_modules(self) -> Path:
        return self.project_dir / "node_modules"


@dataclass
class WatchProcess:
    project: FrontendProject
    process: subprocess.Popen[str]
    baseline_signature: tuple[int, int] | None
    output_tail: deque[str] = field(default_factory=lambda: deque(maxlen=OUTPUT_TAIL_LINES))

    def __post_init__(self) -> None:
        self._output_thread = threading.Thread(target=self._stream_output, daemon=True)
        self._output_thread.start()

    def _stream_output(self) -> None:
        if self.process.stdout is None:
            return
        for line in self.process.stdout:
            self.output_tail.append(line.rstrip())
            print(line, end="", flush=True)

    def wait_until_ready(self, timeout: float = WATCH_READY_TIMEOUT_SECONDS) -> Path:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise FrontendError(
                    f"`npm run watch` exited before `{self.project.bundle_path}` was rebuilt."
                    f"{_format_tail(self.output_tail)}"
                )
            signature = _file_signature(self.project.bundle_path)
            if signature is not None and (self.baseline_signature is None or signature != self.baseline_signature):
                return self.project.bundle_path
            time.sleep(WATCH_POLL_INTERVAL_SECONDS)
        raise FrontendError(
            f"timed out waiting for `npm run watch` to rebuild `{self.project.bundle_path}`"
        )

    def wait(self) -> None:
        returncode = self.process.wait()
        if returncode != 0:
            raise FrontendError(
                f"`npm run watch` exited with code {returncode}.{_format_tail(self.output_tail)}"
            )

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def load_frontend_project(
    config: AppConfig,
    *,
    project_dir: str | Path | None = None,
) -> FrontendProject:
    if config.source_path is None:
        raise FrontendError("config source path is unavailable; load the config from a file")

    config_path = config.source_path.expanduser().resolve()
    resolved_project_dir = (
        config_path.parent if project_dir is None else Path(project_dir).expanduser().resolve()
    )
    package_json = resolved_project_dir / "package.json"

    return FrontendProject(
        config=config,
        config_path=config_path,
        project_dir=resolved_project_dir,
        package_json=package_json,
        entrypoint=resolved_project_dir / "index.ts",
        bundle_path=config.jsfile,
    )


def build_agent_bundle(
    project: FrontendProject,
    *,
    install: bool = False,
    env: Mapping[str, str] | None = None,
) -> Path:
    _validate_frontend_project(project, command="build")
    _ensure_dependencies(project, install=install, env=env)
    _run_command(["npm", "run", "build"], cwd=project.project_dir, env=env)
    _ensure_bundle_exists(project)
    return project.bundle_path


def start_watch(project: FrontendProject, *, install: bool = False) -> WatchProcess:
    _validate_frontend_project(project, command="watch")
    _ensure_dependencies(project, install=install)
    baseline_signature = _file_signature(project.bundle_path)
    verbose_echo(f"starting watch in `{project.project_dir}`: {format_command(['npm', 'run', 'watch'])}")
    try:
        process = subprocess.Popen(
            ["npm", "run", "watch"],
            cwd=project.project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise FrontendError(
            f"failed to start `npm run watch` in `{project.project_dir}`: {exc}"
        ) from exc
    return WatchProcess(project=project, process=process, baseline_signature=baseline_signature)


def _validate_frontend_project(project: FrontendProject, *, command: str) -> None:
    if shutil.which("npm") is None:
        raise FrontendError("npm is required to build the TypeScript agent workspace")
    if not project.project_dir.exists():
        raise FrontendError(f"project directory does not exist: `{project.project_dir}`")
    if not project.package_json.is_file():
        raise FrontendError(
            f"missing `package.json` in `{project.project_dir}`; run `frida-analykit gen dev` first"
        )
    if not project.entrypoint.is_file():
        raise FrontendError(
            f"missing `index.ts` in `{project.project_dir}`; this workspace must expose the agent entrypoint there"
        )
    scripts = _load_package_scripts(project.package_json)
    if command not in scripts:
        raise FrontendError(
            f"`{project.package_json}` is missing the `{command}` npm script required by the CLI compile flow"
        )


def _ensure_dependencies(
    project: FrontendProject,
    *,
    install: bool,
    env: Mapping[str, str] | None = None,
) -> None:
    if project.node_modules.is_dir():
        return
    if not install:
        raise FrontendError(
            f"`{project.project_dir}` is missing `node_modules`; run `npm install` there or rerun with `--install`"
        )
    _run_command(["npm", "install"], cwd=project.project_dir, env=env)


def _ensure_bundle_exists(project: FrontendProject) -> None:
    if project.bundle_path.is_file():
        return
    raise FrontendError(
        f"`npm run build` completed but `{project.bundle_path}` does not exist; "
        "make sure `config.jsfile` matches the npm build output"
    )


def _run_command(command: list[str], *, cwd: Path, env: Mapping[str, str] | None = None) -> None:
    verbose_echo(f"running in `{cwd}`: {format_command(command)}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise FrontendError(f"failed to start `{' '.join(command)}` in `{cwd}`: {exc}") from exc

    if result.stdout and result.stdout.strip():
        verbose_echo(f"stdout from {format_command(command)}:\n{result.stdout.rstrip()}")
    if result.stderr and result.stderr.strip():
        verbose_echo(f"stderr from {format_command(command)}:\n{result.stderr.rstrip()}")
    verbose_echo(f"{format_command(command)} exited with code {result.returncode}")

    if result.returncode == 0:
        return

    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
    detail = f"\n\nLast output:\n{_tail_text(output.splitlines())}" if output else ""
    raise FrontendError(
        f"`{' '.join(command)}` failed in `{cwd}` with exit code {result.returncode}.{detail}"
    )


def _load_package_scripts(package_json: Path) -> dict[str, str]:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FrontendError(f"`{package_json}` is not valid JSON: {exc}") from exc

    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        raise FrontendError(f"`{package_json}` has an invalid `scripts` field")
    return {str(key): str(value) for key, value in scripts.items()}


def _file_signature(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _format_tail(lines: deque[str] | list[str]) -> str:
    if not lines:
        return ""
    return f"\n\nLast output:\n{_tail_text(list(lines))}"


def _tail_text(lines: list[str]) -> str:
    return "\n".join(lines[-OUTPUT_TAIL_LINES:])

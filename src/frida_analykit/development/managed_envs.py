from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..compat import Version
from ..device.models import DeviceSelectionError
from ..env import EnvManager


@dataclass(frozen=True, slots=True)
class ManagedFridaEnvRef:
    name: str
    frida_version: str
    python_path: Path
    source: str


def _probe_python_frida_version(
    python_executable: Path,
    env: dict[str, str],
    *,
    cwd: Path,
    timeout: int = 30,
) -> str | None:
    result = subprocess.run(
        [str(python_executable), "-c", "import frida; print(frida.__version__)"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        return None
    version = result.stdout.strip()
    return version or None


def list_managed_frida_envs(repo_root: Path) -> tuple[ManagedFridaEnvRef, ...]:
    refs: dict[str, ManagedFridaEnvRef] = {}
    for source, manager in (("repo", EnvManager.for_repo(repo_root)), ("global", EnvManager.for_global())):
        try:
            envs = manager.list_envs()
        except Exception:
            continue
        for env in envs:
            ref = ManagedFridaEnvRef(
                name=env.name,
                frida_version=env.frida_version,
                python_path=env.python_path,
                source=source,
            )
            existing = refs.get(ref.frida_version)
            if existing is None or (existing.source != "repo" and ref.source == "repo"):
                refs[ref.frida_version] = ref
    ordered = sorted(refs.values(), key=lambda item: Version.parse(item.frida_version))
    return tuple(ordered)


def resolve_managed_python(
    repo_root: Path,
    env: dict[str, str],
    requested_version: str,
) -> Path:
    current_python = Path(sys.executable)
    current_version = _probe_python_frida_version(current_python, env, cwd=repo_root)
    if current_version == requested_version:
        return current_python

    for managed in list_managed_frida_envs(repo_root):
        if managed.frida_version != requested_version:
            continue
        actual_version = _probe_python_frida_version(managed.python_path, env, cwd=repo_root)
        if actual_version == requested_version:
            return managed.python_path

    raise DeviceSelectionError(
        "device tests require a Python environment with "
        f"frida=={requested_version}. Create one with "
        f"`python scripts/env.py gen --frida-version {requested_version}` "
        "or rerun under a matching environment."
    )


def sample_frida_versions(versions: Sequence[str], iterations: int) -> tuple[str, ...]:
    if iterations <= 0:
        return ()
    ordered = sorted({version: Version.parse(version) for version in versions}.items(), key=lambda item: item[1])
    if not ordered:
        return ()
    names = [item[0] for item in ordered]
    selected: list[int] = []
    selected_set: set[int] = set()

    def add(index: int) -> None:
        if index in selected_set:
            return
        selected.append(index)
        selected_set.add(index)

    target = min(iterations, len(names))
    if target >= 1:
        add(len(names) - 1)
    if target >= 2:
        add(0)
    while len(selected) < target:
        boundaries = sorted([-1, *selected_set, len(names)])
        best_mid: int | None = None
        best_gap = -1
        for left, right in zip(boundaries, boundaries[1:]):
            if right - left <= 1:
                continue
            gap = right - left
            mid = (left + right) // 2
            if gap > best_gap:
                best_gap = gap
                best_mid = mid
        if best_mid is None:
            break
        add(best_mid)
    return tuple(names[index] for index in selected)

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from .models import DeviceSelectionError
from .selection import resolve_device_serials


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_device_test_serials(
    *,
    requested_serials: Sequence[str] = (),
    fallback_serial: str | None = None,
    adb_executable: str = "adb",
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[str, ...]:
    return resolve_device_serials(
        requested_serials,
        all_devices=not requested_serials and fallback_serial is None,
        fallback_serial=fallback_serial,
        adb_executable=adb_executable,
        env=env,
        cwd=cwd,
    )


def build_device_test_command(
    serial: str,
    *,
    repo_root: Path,
    make_target: str,
    device_test_app: str | None = None,
    device_test_skip_app: str | None = None,
) -> list[str]:
    command = ["make", "-C", str(repo_root), make_target, f"ANDROID_SERIAL={serial}"]
    if device_test_app:
        command.append(f"DEVICE_TEST_APP={device_test_app}")
    if device_test_skip_app:
        command.append(f"DEVICE_TEST_SKIP_APP={device_test_skip_app}")
    return command


def _stream_process_output(serial: str, stream: TextIO | None, output: TextIO) -> None:
    if stream is None:
        return
    for line in stream:
        output.write(f"[{serial}] {line}")
        output.flush()


def _stream_supports_color(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def _merge_pytest_color_addopts(existing: str | None) -> str:
    if not existing:
        return "--color=yes"
    if "--color=" in existing:
        return existing
    return f"{existing} --color=yes"


def _build_child_env(base_env: dict[str, str], sink: TextIO) -> dict[str, str]:
    child_env = dict(base_env)
    child_env.setdefault("PYTHONUNBUFFERED", "1")
    if child_env.get("NO_COLOR"):
        return child_env
    if _stream_supports_color(sink):
        child_env.setdefault("PY_COLORS", "1")
        child_env.setdefault("CLICOLOR_FORCE", "1")
        child_env.setdefault("FORCE_COLOR", "1")
        child_env["PYTEST_ADDOPTS"] = _merge_pytest_color_addopts(child_env.get("PYTEST_ADDOPTS"))
    return child_env


def run_device_test_all(
    serials: Sequence[str],
    *,
    repo_root: Path,
    make_target: str,
    env: dict[str, str] | None = None,
    output: TextIO | None = None,
    device_test_app: str | None = None,
    device_test_skip_app: str | None = None,
) -> int:
    sink = output or sys.stdout
    processes: list[tuple[str, subprocess.Popen[str], threading.Thread]] = []
    child_env = _build_child_env(dict(env or os.environ), sink)
    for serial in serials:
        command = build_device_test_command(
            serial,
            repo_root=repo_root,
            make_target=make_target,
            device_test_app=device_test_app,
            device_test_skip_app=device_test_skip_app,
        )
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        thread = threading.Thread(target=_stream_process_output, args=(serial, process.stdout, sink), daemon=True)
        thread.start()
        processes.append((serial, process, thread))

    failed = False
    for serial, process, thread in processes:
        returncode = process.wait()
        thread.join()
        if returncode != 0:
            failed = True
            sink.write(f"[{serial}] exited with code {returncode}\n")
            sink.flush()
    return 1 if failed else 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frida-analykit device tests across every connected device.")
    parser.add_argument("--make-target", default="device-test")
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--serial", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    env = os.environ.copy()
    raw_candidates = env.get("DEVICE_TEST_SERIALS")
    requested_serials = [item.strip() for item in raw_candidates.split(",") if item.strip()] if raw_candidates else list(args.serial)
    try:
        serials = resolve_device_test_serials(
            requested_serials=requested_serials,
            fallback_serial=env.get("ANDROID_SERIAL"),
            env=env,
            cwd=args.repo_root,
        )
    except DeviceSelectionError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return run_device_test_all(
        serials,
        repo_root=args.repo_root,
        make_target=args.make_target,
        env=env,
        device_test_app=env.get("DEVICE_TEST_APP"),
        device_test_skip_app=env.get("DEVICE_TEST_SKIP_APP"),
    )


if __name__ == "__main__":
    raise SystemExit(main())

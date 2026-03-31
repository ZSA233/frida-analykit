from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

from .constants import DEFAULT_DEVICE_TEST_APP_ID
from .models import DeviceSelectionError
from .selection import resolve_device_serials

DEVICE_TEST_APP_PROJECT_RELATIVE_PATH: Final[Path] = Path("tests/android_test_app")
DEVICE_TEST_APP_APK_RELATIVE_PATH: Final[Path] = Path("app/build/outputs/apk/debug/app-debug.apk")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_device_test_app_project_dir(repo_root: Path) -> Path:
    return repo_root / DEVICE_TEST_APP_PROJECT_RELATIVE_PATH


def get_device_test_app_gradlew_path(repo_root: Path) -> Path:
    return get_device_test_app_project_dir(repo_root) / "gradlew"


def get_device_test_app_apk_path(repo_root: Path) -> Path:
    return get_device_test_app_project_dir(repo_root) / DEVICE_TEST_APP_APK_RELATIVE_PATH


def _resolve_java_home(env: dict[str, str]) -> str | None:
    configured = env.get("JAVA_HOME")
    if configured and Path(configured, "bin", "java").is_file():
        return configured

    candidates = (
        Path("/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
    )
    for candidate in candidates:
        if candidate.joinpath("bin", "java").is_file():
            return str(candidate)

    resolved_java = shutil.which("java", path=env.get("PATH"))
    if resolved_java is None:
        return None
    java_path = Path(resolved_java).resolve()
    if java_path.parent.name == "bin":
        return str(java_path.parent.parent)
    return None


def _is_usable_java_home(path: str | None) -> bool:
    return bool(path) and Path(path, "bin", "java").is_file()


def _prepare_tool_env(env: dict[str, str] | None) -> dict[str, str]:
    effective = dict(os.environ if env is None else env)
    java_home = _resolve_java_home(effective)
    if java_home is not None:
        if not _is_usable_java_home(effective.get("JAVA_HOME")):
            effective["JAVA_HOME"] = java_home
        java_bin = str(Path(java_home) / "bin")
        path = effective.get("PATH")
        if path:
            entries = path.split(os.pathsep)
            if java_bin not in entries:
                effective["PATH"] = f"{java_bin}{os.pathsep}{path}"
        else:
            effective["PATH"] = java_bin
    return effective


def build_device_test_app(
    repo_root: Path,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> Path:
    project_dir = get_device_test_app_project_dir(repo_root)
    gradlew = get_device_test_app_gradlew_path(repo_root)
    if not project_dir.is_dir():
        raise RuntimeError(f"device test app project was not found at `{project_dir}`")
    if not gradlew.is_file():
        raise RuntimeError(f"device test app Gradle wrapper was not found at `{gradlew}`")

    effective_env = _prepare_tool_env(env)
    result = subprocess.run(
        [str(gradlew), "assembleDebug"],
        cwd=project_dir,
        env=effective_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "failed to build the default Android device test app\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    apk_path = get_device_test_app_apk_path(repo_root)
    if not apk_path.is_file():
        raise RuntimeError(f"Gradle build succeeded but `{apk_path}` was not created")
    return apk_path


def install_device_test_app(
    serial: str,
    repo_root: Path,
    *,
    adb_executable: str = "adb",
    env: dict[str, str] | None = None,
    build_timeout: int = 900,
    install_timeout: int = 300,
) -> Path:
    apk_path = build_device_test_app(repo_root, env=env, timeout=build_timeout)
    install_device_test_app_only(
        serial,
        apk_path,
        repo_root,
        adb_executable=adb_executable,
        env=env,
        install_timeout=install_timeout,
    )
    return apk_path


def install_device_test_app_only(
    serial: str,
    apk_path: Path,
    repo_root: Path,
    *,
    adb_executable: str = "adb",
    env: dict[str, str] | None = None,
    install_timeout: int = 300,
) -> None:
    effective_env = _prepare_tool_env(env)
    result = subprocess.run(
        [adb_executable, "-s", serial, "install", "-r", str(apk_path)],
        cwd=repo_root,
        env=effective_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=install_timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"failed to install `{apk_path.name}` on `{serial}`\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    if "Success" not in result.stdout and "Success" not in result.stderr:
        raise RuntimeError(
            f"`adb install` did not report success for `{serial}`\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def resolve_test_app_install_serials(
    *,
    requested_serials: tuple[str, ...] = (),
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


def install_device_test_app_all(
    serials: tuple[str, ...],
    repo_root: Path,
    *,
    adb_executable: str = "adb",
    env: dict[str, str] | None = None,
    build_timeout: int = 900,
    install_timeout: int = 300,
    output=None,
) -> Path:
    apk_path = build_device_test_app(repo_root, env=env, timeout=build_timeout)
    sink = output or sys.stdout
    failed = False
    for serial in serials:
        sink.write(f"[{serial}] installing {apk_path.name}\n")
        sink.flush()
        try:
            install_device_test_app_only(
                serial,
                apk_path,
                repo_root,
                adb_executable=adb_executable,
                env=env,
                install_timeout=install_timeout,
            )
        except RuntimeError as exc:
            failed = True
            sink.write(f"[{serial}] {exc}\n")
        else:
            sink.write(f"[{serial}] install succeeded\n")
        sink.flush()
    if failed:
        raise RuntimeError(f"failed to install `{apk_path.name}` on one or more devices")
    return apk_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or install the default Android device test app.")
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("build")

    install_parser = subcommands.add_parser("install")
    install_parser.add_argument("--serial", required=True)
    install_parser.add_argument("--adb", default="adb")

    install_all_parser = subcommands.add_parser("install-all")
    install_all_parser.add_argument("--serial", dest="serials", action="append", default=[])
    install_all_parser.add_argument("--adb", default="adb")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "build":
        apk_path = build_device_test_app(args.repo_root)
        print(apk_path)
        return 0

    if args.command == "install":
        apk_path = install_device_test_app(
            args.serial,
            args.repo_root,
            adb_executable=args.adb,
        )
        print(f"installed {apk_path} on {args.serial}")
        return 0

    if args.command == "install-all":
        env = dict(os.environ)
        raw_serials = env.get("DEVICE_TEST_SERIALS")
        requested_serials = (
            tuple(item.strip() for item in raw_serials.split(",") if item.strip())
            if raw_serials
            else tuple(args.serials)
        )
        try:
            serials = resolve_test_app_install_serials(
                requested_serials=requested_serials,
                fallback_serial=env.get("ANDROID_SERIAL"),
                adb_executable=args.adb,
                env=env,
                cwd=args.repo_root,
            )
        except DeviceSelectionError as exc:
            raise RuntimeError(str(exc)) from exc
        apk_path = install_device_test_app_all(
            serials,
            args.repo_root,
            adb_executable=args.adb,
            env=env,
        )
        print(f"installed {apk_path} on {', '.join(serials)}")
        return 0

    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

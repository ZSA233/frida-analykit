import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from frida_analykit.cli import cli
from frida_analykit.config import AppConfig, DEFAULT_SCRIPT_REPL_GLOBALS
from frida_analykit.scaffold import generate_dev_workspace
from tests.support.paths import REPO_ROOT


SCAFFOLD_IMPORT_EXAMPLE = """\
import "@zsa233/frida-analykit-agent/rpc"
import { help } from "@zsa233/frida-analykit-agent/helper"

setImmediate(() => {
    help.$error("OK!")
})
"""

DEX_EXPLICIT_RETAIN_IMPORT_EXAMPLE = """\
import "@zsa233/frida-analykit-agent/rpc"
import { DexTools as __fridaAnalykitDexPreload } from "@zsa233/frida-analykit-agent/dex"

void __fridaAnalykitDexPreload

setImmediate(() => {
    console.log("dex-preload-ready")
})
"""


def _require_npm_scaffold_checks() -> None:
    if os.environ.get("FRIDA_ANALYKIT_ENABLE_NPM") != "1":
        pytest.skip("set FRIDA_ANALYKIT_ENABLE_NPM=1 to run npm scaffold checks")
    if shutil.which("npm") is None:
        pytest.skip("npm is required for scaffold checks")


def _scaffold_npm_env(tmp_path: Path) -> dict[str, str]:
    npm_env = dict(os.environ)
    npm_cache_dir = tmp_path / ".npm-cache"
    npm_cache_dir.mkdir(parents=True, exist_ok=True)
    npm_env["npm_config_cache"] = str(npm_cache_dir)
    return npm_env


def _pack_local_runtime(tmp_path: Path, *, npm_env: dict[str, str]) -> Path:
    package_name = (
        subprocess.check_output(
            ["npm", "pack", "./packages/frida-analykit-agent"],
            cwd=REPO_ROOT,
            env=npm_env,
            text=True,
        )
        .strip()
        .splitlines()[-1]
    )
    source = REPO_ROOT / package_name
    destination = tmp_path / package_name
    shutil.move(source, destination)
    return destination


def _pin_workspace_dependencies_to_local_cache(workspace: Path, *, repo_root: Path) -> None:
    package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    package["overrides"] = {
        "frida-java-bridge": f"file:{repo_root / 'node_modules' / 'frida-java-bridge'}",
    }
    package["devDependencies"]["@types/frida-gum"] = f"file:{repo_root / 'node_modules' / '@types' / 'frida-gum'}"
    package["devDependencies"]["typescript"] = f"file:{repo_root / 'node_modules' / 'typescript'}"
    local_frida_compile = repo_root / "node_modules" / "frida-compile"
    if local_frida_compile.exists():
        package["devDependencies"]["frida-compile"] = f"file:{local_frida_compile}"
    local_frida = repo_root / "node_modules" / "frida"
    if local_frida.exists():
        package["overrides"]["frida"] = f"file:{local_frida}"
    local_types_node = repo_root / "node_modules" / "@types" / "node"
    if local_types_node.exists():
        package["devDependencies"]["@types/node"] = f"file:{local_types_node}"
    (workspace / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")


@pytest.mark.scaffold
def test_scaffold_can_use_local_packed_runtime(tmp_path: Path) -> None:
    _require_npm_scaffold_checks()

    repo_root = REPO_ROOT
    npm_env = _scaffold_npm_env(tmp_path)
    tarball = _pack_local_runtime(tmp_path, npm_env=npm_env)

    generate_dev_workspace(tmp_path, agent_package_spec=f"file:{tarball}")
    (tmp_path / "index.ts").write_text(SCAFFOLD_IMPORT_EXAMPLE, encoding="utf-8")
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    package["scripts"]["build"] = (
        "tsc -p tsconfig.json --noEmit && "
        "node -e \"require('node:fs').writeFileSync('_agent.js', '// built by scaffold test\\n');\""
    )
    package["overrides"] = {
        "frida-java-bridge": f"file:{repo_root / 'node_modules' / 'frida-java-bridge'}",
    }
    package["devDependencies"] = {
        "@types/frida-gum": f"file:{repo_root / 'node_modules' / '@types' / 'frida-gum'}",
        "typescript": f"file:{repo_root / 'node_modules' / 'typescript'}",
    }
    (tmp_path / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "module": "es2022",
                    "moduleResolution": "bundler",
                    "target": "es2021",
                    "lib": ["es2021"],
                    "types": ["frida-gum"],
                    "allowJs": True,
                    "noEmit": True,
                    "strict": True,
                    "esModuleInterop": True,
                    "allowSyntheticDefaultImports": True,
                    "skipLibCheck": True,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    subprocess.run(["npm", "install", "--ignore-scripts"], cwd=tmp_path, env=npm_env, check=True)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["build", "--config", str(tmp_path / "config.toml"), "--project-dir", str(tmp_path)],
    )

    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0, result.output
    assert package["dependencies"]["@zsa233/frida-analykit-agent"].startswith("file:")
    assert (tmp_path / "_agent.js").exists()
    assert AppConfig.from_file(tmp_path / "config.toml").script.repl.globals == list(DEFAULT_SCRIPT_REPL_GLOBALS)


@pytest.mark.scaffold
def test_scaffold_real_frida_compile_keeps_explicit_capability_references(tmp_path: Path) -> None:
    _require_npm_scaffold_checks()

    repo_root = REPO_ROOT
    local_frida_compile = repo_root / "node_modules" / "frida-compile"
    local_frida_binding = repo_root / "node_modules" / "frida" / "build" / "frida_binding.node"
    if shutil.which("frida-compile") is None and not local_frida_compile.exists():
        pytest.skip("real scaffold compile smoke test requires frida-compile in PATH or repo node_modules")
    if not local_frida_compile.exists():
        pytest.skip("real scaffold compile smoke test requires local node_modules/frida-compile")
    if not local_frida_binding.exists():
        pytest.skip("real scaffold compile smoke test requires a built local node_modules/frida binding")

    npm_env = _scaffold_npm_env(tmp_path)
    tarball = _pack_local_runtime(tmp_path, npm_env=npm_env)

    rpc_workspace = tmp_path / "rpc-only"
    dex_workspace = tmp_path / "dex-preload"
    generate_dev_workspace(rpc_workspace, agent_package_spec=f"file:{tarball}")
    generate_dev_workspace(dex_workspace, agent_package_spec=f"file:{tarball}")
    (rpc_workspace / "index.ts").write_text('import "@zsa233/frida-analykit-agent/rpc"\n', encoding="utf-8")
    (dex_workspace / "index.ts").write_text(DEX_EXPLICIT_RETAIN_IMPORT_EXAMPLE, encoding="utf-8")

    for workspace in (rpc_workspace, dex_workspace):
        _pin_workspace_dependencies_to_local_cache(workspace, repo_root=repo_root)
        subprocess.run(["npm", "install"], cwd=workspace, env=npm_env, check=True)
        subprocess.run(["npm", "run", "build"], cwd=workspace, env=npm_env, check=True)

    rpc_bundle = (rpc_workspace / "_agent.js").read_text(encoding="utf-8")
    dex_bundle = (dex_workspace / "_agent.js").read_text(encoding="utf-8")

    assert "[DexTools]" not in rpc_bundle
    assert "[DexTools]" in dex_bundle

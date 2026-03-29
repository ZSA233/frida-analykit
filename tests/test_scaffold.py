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


SCAFFOLD_IMPORT_EXAMPLE = """\
import "@zsa233/frida-analykit-agent/rpc"
import { help } from "@zsa233/frida-analykit-agent/helper"

setImmediate(() => {
    help.$error("OK!")
})
"""


@pytest.mark.scaffold
def test_scaffold_can_use_local_packed_runtime(tmp_path: Path) -> None:
    if os.environ.get("FRIDA_ANALYKIT_ENABLE_NPM") != "1":
        pytest.skip("set FRIDA_ANALYKIT_ENABLE_NPM=1 to run npm scaffold checks")
    if shutil.which("npm") is None:
        pytest.skip("npm is required for scaffold checks")

    repo_root = Path(__file__).resolve().parents[1]
    npm_env = dict(os.environ)
    npm_cache_dir = tmp_path / ".npm-cache"
    npm_cache_dir.mkdir(parents=True, exist_ok=True)
    # Use a test-local npm cache so scaffold checks do not inherit broken host cache permissions.
    npm_env["npm_config_cache"] = str(npm_cache_dir)
    package_name = (
        subprocess.check_output(
            ["npm", "pack", "./packages/frida-analykit-agent"],
            cwd=repo_root,
            env=npm_env,
            text=True,
        )
        .strip()
        .splitlines()[-1]
    )
    tarball = repo_root / package_name

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
        ["build", "--config", str(tmp_path / "config.yml"), "--project-dir", str(tmp_path)],
    )

    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0, result.output
    assert package["dependencies"]["@zsa233/frida-analykit-agent"].startswith("file:")
    assert "frida-java-bridge" not in package["dependencies"]
    assert (tmp_path / "_agent.js").exists()
    assert "OK!" in (tmp_path / "index.ts").read_text(encoding="utf-8")
    assert AppConfig.from_yaml(tmp_path / "config.yml").script.repl.globals == list(DEFAULT_SCRIPT_REPL_GLOBALS)

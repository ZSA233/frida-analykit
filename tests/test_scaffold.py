import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from frida_analykit.cli import cli
from frida_analykit.scaffold import generate_dev_workspace


SCAFFOLD_IMPORT_EXAMPLE = """\
import "@zsa233/frida-analykit-agent/rpc"
import { SSLTools, help } from "@zsa233/frida-analykit-agent"

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
    package_name = (
        subprocess.check_output(["npm", "pack", "./packages/frida-analykit-agent"], cwd=repo_root, text=True)
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
    (tmp_path / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
    subprocess.run(["npm", "install", "--ignore-scripts"], cwd=tmp_path, check=True)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["build", "--config", str(tmp_path / "config.yml"), "--project-dir", str(tmp_path)],
    )

    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0, result.output
    assert package["dependencies"]["@zsa233/frida-analykit-agent"].startswith("file:")
    assert (tmp_path / "_agent.js").exists()
    assert "OK!" in (tmp_path / "index.ts").read_text(encoding="utf-8")

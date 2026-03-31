from __future__ import annotations

import json
from pathlib import Path


def test_agent_device_tests_package_build_uses_dedicated_build_config() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    package_json = json.loads(
        (repo_root / "packages/frida-analykit-agent-device-tests/package.json").read_text(encoding="utf-8")
    )
    build_config = json.loads(
        (repo_root / "packages/frida-analykit-agent-device-tests/tsconfig.build.json").read_text(encoding="utf-8")
    )

    assert package_json["private"] is True
    assert package_json["main"] == "./dist/index.js"
    assert package_json["types"] == "./dist/index.d.ts"
    assert "dist/**/*" in package_json["files"]
    assert package_json["exports"]["."]["default"] == "./dist/index.js"
    assert package_json["exports"]["."]["types"] == "./dist/index.d.ts"
    assert package_json["peerDependencies"]["@zsa233/frida-analykit-agent"] == "*"
    assert package_json["scripts"]["build"] == "tsc -p tsconfig.build.json"
    assert package_json["scripts"]["prepack"] == "npm run build"
    assert build_config["extends"] == "./tsconfig.json"
    assert build_config["compilerOptions"]["noEmit"] is False
    assert build_config["compilerOptions"]["outDir"] == "./dist"
    assert build_config["compilerOptions"]["declaration"] is True

from __future__ import annotations

import json
from pathlib import Path


def test_agent_package_exports_prebuilt_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    package_json = json.loads(
        (repo_root / "packages/frida-analykit-agent/package.json").read_text(encoding="utf-8")
    )

    assert package_json["main"] == "./dist/index.js"
    assert package_json["types"] == "./dist/index.d.ts"
    assert "dist/**/*" in package_json["files"]
    assert package_json["exports"]["."]["default"] == "./dist/index.js"
    assert package_json["exports"]["."]["types"] == "./dist/index.d.ts"
    assert package_json["exports"]["./rpc"]["default"] == "./dist/rpc.js"
    assert package_json["exports"]["./rpc"]["types"] == "./dist/rpc.d.ts"
    assert "./*" not in package_json["exports"]


def test_agent_package_build_uses_dedicated_build_config() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    package_json = json.loads(
        (repo_root / "packages/frida-analykit-agent/package.json").read_text(encoding="utf-8")
    )
    build_config = json.loads(
        (repo_root / "packages/frida-analykit-agent/tsconfig.build.json").read_text(encoding="utf-8")
    )
    type_test_config = json.loads(
        (repo_root / "packages/frida-analykit-agent/tsconfig.type-tests.json").read_text(encoding="utf-8")
    )

    assert package_json["scripts"]["build"] == "tsc -p tsconfig.build.json"
    assert package_json["scripts"]["prepack"] == "npm run build"
    assert "tsconfig.type-tests.json" in package_json["scripts"]["check"]
    assert build_config["extends"] == "./tsconfig.json"
    assert build_config["compilerOptions"]["noEmit"] is False
    assert build_config["compilerOptions"]["outDir"] == "./dist"
    assert build_config["compilerOptions"]["declaration"] is True
    assert type_test_config["extends"] == "./tsconfig.json"
    assert type_test_config["compilerOptions"]["rootDir"] == "."
    assert type_test_config["compilerOptions"]["noEmit"] is True

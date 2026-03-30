from __future__ import annotations

import json
from pathlib import Path


def test_agent_package_exports_prebuilt_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    root_entry = (repo_root / "packages/frida-analykit-agent/src/index.ts").read_text(encoding="utf-8")
    package_json = json.loads(
        (repo_root / "packages/frida-analykit-agent/package.json").read_text(encoding="utf-8")
    )

    assert package_json["main"] == "./dist/index.js"
    assert package_json["types"] == "./dist/index.d.ts"
    assert "dist/**/*" in package_json["files"]
    assert package_json["exports"]["."]["default"] == "./dist/index.js"
    assert package_json["exports"]["."]["types"] == "./dist/index.d.ts"
    assert package_json["exports"]["./config"]["default"] == "./dist/config/index.js"
    assert package_json["exports"]["./bridges"]["default"] == "./dist/bridges/index.js"
    assert package_json["exports"]["./helper"]["default"] == "./dist/helper/index.js"
    assert package_json["exports"]["./process"]["default"] == "./dist/process/index.js"
    assert package_json["exports"]["./jni"]["default"] == "./dist/jni/index.js"
    assert package_json["exports"]["./ssl"]["default"] == "./dist/ssl/index.js"
    assert package_json["exports"]["./elf"]["default"] == "./dist/elf/index.js"
    assert package_json["exports"]["./dex"]["default"] == "./dist/dex/index.js"
    assert package_json["exports"]["./native/libssl"]["default"] == "./dist/native/libssl/index.js"
    assert package_json["exports"]["./native/libart"]["default"] == "./dist/native/libart/index.js"
    assert package_json["exports"]["./native/libc"]["default"] == "./dist/native/libc/index.js"
    assert package_json["exports"]["./rpc"]["default"] == "./dist/rpc/index.js"
    assert package_json["exports"]["./rpc"]["types"] == "./dist/rpc/index.d.ts"
    assert "./libssl" not in package_json["exports"]
    assert "./*" not in package_json["exports"]
    assert 'export { Config, LogLevel, setGlobalProperties } from "./config/index.js"' in root_entry
    assert 'export { help, NativePointerObject, BatchSender, ProgressNotify, LoggerState, FileHelper } from "./helper/index.js"' in root_entry
    assert 'export { proc } from "./process/index.js"' in root_entry
    assert "JNIEnv" not in root_entry
    assert "SSLTools" not in root_entry
    assert "ElfTools" not in root_entry
    assert "Libart" not in root_entry
    assert "Libssl" not in root_entry


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

    assert "tsconfig.build.json" in package_json["scripts"]["build"]
    assert package_json["scripts"]["prepack"] == "npm run build"
    assert "tsconfig.type-tests.json" in package_json["scripts"]["check"]
    assert build_config["extends"] == "./tsconfig.json"
    assert build_config["compilerOptions"]["noEmit"] is False
    assert build_config["compilerOptions"]["outDir"] == "./dist"
    assert build_config["compilerOptions"]["declaration"] is True
    assert type_test_config["extends"] == "./tsconfig.json"
    assert type_test_config["compilerOptions"]["rootDir"] == "."
    assert type_test_config["compilerOptions"]["noEmit"] is True

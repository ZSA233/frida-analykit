from __future__ import annotations

import json

from tests.support.paths import REPO_ROOT

_EXPECTED_PUBLIC_EXPORTS = {
    ".": "./dist/index.js",
    "./config": "./dist/config/index.js",
    "./bridges": "./dist/bridges/index.js",
    "./helper": "./dist/helper/index.js",
    "./process": "./dist/process/index.js",
    "./jni": "./dist/jni/index.js",
    "./ssl": "./dist/ssl/index.js",
    "./elf": "./dist/elf/index.js",
    "./elf/enhanced": "./dist/elf/enhanced/index.js",
    "./dex": "./dist/dex/index.js",
    "./native/libssl": "./dist/native/libssl/index.js",
    "./native/libart": "./dist/native/libart/index.js",
    "./native/libc": "./dist/native/libc/index.js",
    "./rpc": "./dist/rpc/index.js",
}

_EXPECTED_SIDE_EFFECTS = {
    "./dist/config/index.js",
    "./dist/bridges/index.js",
    "./dist/helper/index.js",
    "./dist/process/index.js",
    "./dist/jni/index.js",
    "./dist/ssl/index.js",
    "./dist/elf/index.js",
    "./dist/dex/index.js",
    "./dist/native/libssl/index.js",
    "./dist/native/libart/index.js",
    "./dist/native/libc/index.js",
    "./dist/rpc/index.js",
}


def test_agent_package_manifest_and_public_exports() -> None:
    package_json = json.loads((REPO_ROOT / "packages/frida-analykit-agent/package.json").read_text(encoding="utf-8"))
    package_readme = (REPO_ROOT / "packages/frida-analykit-agent/README.md").read_text(encoding="utf-8")
    package_readme_en = (REPO_ROOT / "packages/frida-analykit-agent/README_EN.md").read_text(encoding="utf-8")

    assert package_json["main"] == "./dist/index.js"
    assert package_json["types"] == "./dist/index.d.ts"
    assert {"dist/**/*", "README.md", "README_EN.md"}.issubset(set(package_json["files"]))
    assert package_json["homepage"] == "https://github.com/ZSA233/frida-analykit"
    assert "blob/main" not in package_readme
    assert "blob/main" not in package_readme_en
    assert "blob/stable/packages/frida-analykit-agent/README_EN.md" in package_readme
    assert "blob/stable/packages/frida-analykit-agent/README.md" in package_readme_en
    assert package_json["exports"]["."]["types"] == "./dist/index.d.ts"
    assert package_json["exports"]["./rpc"]["types"] == "./dist/rpc/index.d.ts"
    assert set(package_json["sideEffects"]) == _EXPECTED_SIDE_EFFECTS
    assert "./libssl" not in package_json["exports"]
    assert "./*" not in package_json["exports"]

    for export_name, export_path in _EXPECTED_PUBLIC_EXPORTS.items():
        assert package_json["exports"][export_name]["default"] == export_path


def test_agent_package_root_entry_remains_lightweight() -> None:
    root_entry = (REPO_ROOT / "packages/frida-analykit-agent/src/index.ts").read_text(encoding="utf-8")

    assert 'export { Config, LogLevel, setGlobalProperties } from "./config/index.js"' in root_entry
    assert (
        'export { help, NativePointerObject, BatchSender, ProgressNotify, LoggerState, FileHelper } '
        'from "./helper/index.js"'
    ) in root_entry
    assert 'export { proc } from "./process/index.js"' in root_entry

    for heavy_symbol in ("JNIEnv", "SSLTools", "ElfTools", "DexTools", "Libart", "Libssl", "Libc"):
        assert heavy_symbol not in root_entry


def test_agent_package_build_uses_dedicated_build_config() -> None:
    package_json = json.loads((REPO_ROOT / "packages/frida-analykit-agent/package.json").read_text(encoding="utf-8"))
    build_config = json.loads(
        (REPO_ROOT / "packages/frida-analykit-agent/tsconfig.build.json").read_text(encoding="utf-8")
    )
    type_test_config = json.loads(
        (REPO_ROOT / "packages/frida-analykit-agent/tsconfig.type-tests.json").read_text(encoding="utf-8")
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

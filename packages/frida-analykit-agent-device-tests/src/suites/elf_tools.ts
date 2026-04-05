import { ElfTools } from "@zsa233/frida-analykit-agent/elf";
import { castElfSymbolHooks } from "@zsa233/frida-analykit-agent/elf/enhanced";
import { libc } from "@zsa233/frida-analykit-agent/native/libc";

import { assertCondition, runSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runElfToolsSuite(): AgentUnitSuiteResult {
    return runSuite("elf_tools", [
        {
            name: "create_symbol_hooks_and_resolve_known_symbol",
            run: () => {
                const hooks = ElfTools.createSymbolHooks("libc.so", { observeDlsym: false });
                const resolved = hooks.resolve("__system_property_get");
                assertCondition(resolved !== null, "expected __system_property_get symbol to resolve");
                assertCondition(resolved.implPtr !== null, "expected __system_property_get impl pointer");
                return `${resolved.name}:${resolved.implPtr}`;
            },
        },
        {
            name: "core_attach_intercepts_system_property_get",
            run: () => {
                let intercepted = 0;
                const hooks = ElfTools.createSymbolHooks("libc.so", { observeDlsym: false, logTag: "elf-core-system-property-get" });
                hooks.attach("__system_property_get", function (impl: AnyFunction, name: NativePointer, value: NativePointer) {
                    intercepted += 1;
                    return impl(name, value);
                }, "int", ["pointer", "pointer"]);
                const sdk = libc.__system_property_get("ro.build.version.sdk");
                assertCondition(sdk.length > 0, "expected non-empty ro.build.version.sdk");
                assertCondition(intercepted > 0, "expected __system_property_get hook to intercept at least once");
                return sdk;
            },
        },
        {
            name: "enhanced_cast_exposes_getppid_preset",
            run: () => {
                const logTag = `elf-tools-log-${Process.id}-${Date.now().toString(16)}`;
                const hooks = ElfTools.createSymbolHooks("libc.so", { observeDlsym: false, logTag });
                const enhanced = castElfSymbolHooks(hooks);
                enhanced.getppid();
                setImmediate(() => {
                    libc.getppid();
                });
                return JSON.stringify({ logTag, symbol: "getppid" });
            },
        },
        {
            name: "dump_streams_to_python_session_dir",
            run: () => {
                const tag = `elf-tools-dump-${Process.id}-${Date.now().toString(16)}`;
                const summary = ElfTools.dumpModule("libc.so", { tag });
                const artifactKinds = summary.artifacts.map((item) => item.kind);
                const artifactKindStrings = artifactKinds as string[];
                assertCondition(summary.mode === "rpc", `expected rpc dump mode, got ${summary.mode}`);
                assertCondition(summary.dumpId.length > 0, "expected dump id");
                assertCondition(summary.totalBytes > 0, `expected positive total bytes, got ${summary.totalBytes}`);
                assertCondition(summary.relativeDumpDir.length > 0, "expected relative dump dir");
                assertCondition(summary.artifacts.length === 6, `expected 6 dump artifacts, got ${summary.artifacts.length}`);
                assertCondition(artifactKinds.includes("fixups"), "expected fixups artifact");
                assertCondition(!artifactKindStrings.includes("rebuilt"), "rebuilt artifact should not be exposed");
                return JSON.stringify({
                    tag,
                    dumpId: summary.dumpId,
                    relativeDumpDir: summary.relativeDumpDir,
                    artifacts: summary.artifacts,
                    moduleName: summary.moduleName,
                    totalBytes: summary.totalBytes,
                });
            },
        },
    ]);
}

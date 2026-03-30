import { DexTools } from "@zsa233/frida-analykit-agent/dex";

import { assertCondition, runJavaSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runDexToolsSuite(): AgentUnitSuiteResult {
    return runJavaSuite("dex_tools", [
        {
            name: "enumerate_class_loader_dex_files_returns_metadata",
            run: () => {
                const loaders = DexTools.enumerateClassLoaderDexFiles();
                assertCondition(loaders.length > 0, "expected at least one class loader");
                const firstLoader = loaders.find((item) => item.dexFiles.length > 0);
                assertCondition(firstLoader !== undefined, "expected at least one loader with dex files");
                const firstDex = firstLoader.dexFiles[0]!;
                assertCondition(firstLoader.loader_class.length > 0, "expected loader class name");
                assertCondition(firstDex.name.length > 0, "expected dex name");
                assertCondition(firstDex.size > 0, `expected positive dex size, got ${firstDex.size}`);
                assertCondition(!firstDex.base.isNull(), "expected dex base pointer");
                return `${firstLoader.loader_class}:${firstDex.name}`;
            },
        },
        {
            name: "dump_all_dex_streams_to_python_handler",
            run: () => {
                const tag = `dex-tools-${Process.id}-${Date.now().toString(16)}`;
                const summary = DexTools.dumpAllDex({
                    tag,
                    maxBatchBytes: 256 * 1024,
                    log() {},
                });
                assertCondition(summary.mode === "rpc", `expected rpc mode, got ${summary.mode}`);
                assertCondition(summary.transferId.length > 0, "expected transfer id");
                assertCondition(summary.dexCount > 0, `expected positive dex count, got ${summary.dexCount}`);
                assertCondition(summary.totalBytes > 0, `expected positive total bytes, got ${summary.totalBytes}`);
                return JSON.stringify({
                    tag,
                    transferId: summary.transferId,
                    dexCount: summary.dexCount,
                    totalBytes: summary.totalBytes,
                });
            },
        },
    ]);
}

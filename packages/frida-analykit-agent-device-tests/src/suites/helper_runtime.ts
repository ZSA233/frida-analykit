import { Config } from "@zsa233/frida-analykit-agent/config";
import { help, type MemoryProtect } from "@zsa233/frida-analykit-agent/helper";

import { assertCondition, runSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runHelperRuntimeSuite(): AgentUnitSuiteResult {
    return runSuite("helper_runtime", [
        {
            name: "fs_get_log_file_roundtrip",
            run: () => {
                const tag = `helper-runtime-${Process.id}.log`;
                const filepath = help.fs.joinPath(help.runtime.getOutputDir(), tag);
                const logfile = help.fs.getLogFile(tag, "w");
                logfile.writeLine("helper-runtime", "");
                logfile.flush();
                const content = help.fs.readText(filepath);
                assertCondition(content === "helper-runtime", `expected roundtrip file content, got ${content}`);
                return filepath;
            },
        },
        {
            name: "fs_save_uses_output_dir_for_relative_paths",
            run: () => {
                const tag = `helper-runtime-save-${Process.id}.txt`;
                const filepath = help.fs.joinPath(help.runtime.getOutputDir(), tag);
                const prevOnRpc = Config.OnRPC;
                Config.OnRPC = false;
                try {
                    help.fs.save(tag, "saved", "w", "helper_runtime");
                } finally {
                    Config.OnRPC = prevOnRpc;
                }
                const content = help.fs.readText(filepath);
                assertCondition(content === "saved", `expected saved file content, got ${content}`);
                return filepath;
            },
        },
        {
            name: "proc_and_runtime_helpers_report_process_info",
            run: () => {
                const maps = help.proc.readMaps();
                const cmdline = help.proc.readCmdline();
                const apiLevel = help.runtime.androidApiLevel();
                assertCondition(maps.length > 0, "expected /proc/self/maps to be non-empty");
                assertCondition(cmdline.length > 0, "expected /proc/self/cmdline to be non-empty");
                assertCondition(apiLevel > 0, `expected android api level > 0, got ${apiLevel}`);
                return `cmdline=${cmdline}, api=${apiLevel}`;
            },
        },
        {
            name: "mem_helpers_scan_and_make_range_readable",
            run: () => {
                const targetModule = Process.findModuleByName("libc.so") || Process.mainModule;
                let readablePages = 0;
                help.mem.withReadableRange(targetModule.base, 4, (makeReadable: () => MemoryProtect[], makeRecovery: () => MemoryProtect[]) => {
                    readablePages = makeReadable().filter((page) => page.readable).length;
                    makeRecovery();
                });
                const matches = help.mem.scan(
                    { base: targetModule.base, size: Math.min(targetModule.size, Process.pageSize) },
                    "7f 45 4c 46",
                    { limit: Process.pageSize, maxMatchNum: 1 },
                );
                assertCondition(readablePages > 0, "expected withReadableRange() to expose at least one readable page");
                assertCondition(matches.length > 0, "expected help.mem.scan() to find the ELF header");
                return `${targetModule.name}:${matches.length}`;
            },
        },
        {
            name: "runtime_batch_sender_and_progress_creation_work",
            run: () => {
                const sender = help.runtime.newBatchSender("helper_runtime");
                sender.send({ ok: true }, new Uint8Array([1]).buffer);
                const response = sender.rpcResponse();
                const progress = help.progress.create("helper_runtime");
                progress.notify({ stage: "ready" });
                progress.log("helper_runtime", "ready");
                assertCondition(response.length === 2, `expected batch sender response, got ${response.length}`);
                assertCondition(progress.tag === "helper_runtime", `expected progress tag helper_runtime, got ${progress.tag}`);
                return "runtime-ok";
            },
        },
    ]);
}

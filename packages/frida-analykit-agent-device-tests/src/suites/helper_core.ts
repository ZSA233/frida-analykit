import { Config } from "@zsa233/frida-analykit-agent/config";
import { BatchSender, LoggerState, ProgressNotify, help } from "@zsa233/frida-analykit-agent/helper";

import { assertCondition, runSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runHelperCoreSuite(): AgentUnitSuiteResult {
    return runSuite("helper_core", [
        {
            name: "logger_state_collapses_repeated_sequence",
            run: () => {
                const state = new LoggerState(2);
                state.onLog("A");
                state.onLog("B");
                state.onLog("A");
                state.onLog("B");
                const collapsed = state.onLog("C");
                assertCondition(collapsed.length === 3, `expected 3 output lines, got ${collapsed.length}`);
                assertCondition(collapsed[0] === "#2# | A", `expected collapsed prefix for A, got ${collapsed[0]}`);
                assertCondition(collapsed[1] === "#2# | B", `expected collapsed prefix for B, got ${collapsed[1]}`);
                assertCondition(collapsed[2] === "C", `expected trailing line C, got ${collapsed[2]}`);
                return collapsed.join(" | ");
            },
        },
        {
            name: "batch_sender_batches_payloads",
            run: () => {
                const sender = new BatchSender("helper_core");
                sender.send({ a: 1 }, new Uint8Array([1, 2]).buffer);
                sender.send({ b: 2 }, new Uint8Array([3]).buffer);
                const response = sender.rpcResponse();
                assertCondition(response.length === 2, `expected rpcResponse() to return message+buffer, got ${response.length}`);
                const [message, payload] = response;
                assertCondition(message.source === "helper_core", `expected source helper_core, got ${message.source}`);
                assertCondition(message.data.data_sizes.join(",") === "2,1", `expected data sizes 2,1, got ${message.data.data_sizes}`);
                assertCondition(payload.byteLength === 3, `expected payload size 3, got ${payload.byteLength}`);
                sender.clear();
                assertCondition(sender.rpcResponse().length === 0, "expected cleared batch sender to return an empty response");
                return `sizes=${message.data.data_sizes.join(",")}`;
            },
        },
        {
            name: "batch_sender_flushes_when_max_batch_bytes_is_hit",
            run: () => {
                const flushed: number[] = [];
                const sender = help.runtime.newBatchSender("helper_core", {
                    maxBatchBytes: 2,
                    sender(message, payload) {
                        flushed.push(payload.byteLength);
                        assertCondition(message.source === "helper_core", `expected helper_core source, got ${message.source}`);
                    },
                });
                sender.send({ a: 1 }, new Uint8Array([1]).buffer);
                sender.send({ b: 2 }, new Uint8Array([2, 3]).buffer);
                sender.send({ c: 3 }, new Uint8Array([4]).buffer);
                sender.flush();
                assertCondition(flushed.join(",") === "1,2,1", `expected 3 flush groups, got ${flushed.join(",")}`);
                return flushed.join(",");
            },
        },
        {
            name: "batch_sender_uses_global_batch_limit_by_default",
            run: () => {
                const prev = Config.BatchMaxBytes;
                const flushed: number[] = [];
                Config.BatchMaxBytes = 2;
                try {
                    const sender = new BatchSender("helper_core", {
                        sender(_message, payload) {
                            flushed.push(payload.byteLength);
                        },
                    });
                    sender.send({ a: 1 }, new Uint8Array([1]).buffer);
                    sender.send({ b: 2 }, new Uint8Array([2, 3]).buffer);
                    sender.send({ c: 3 }, new Uint8Array([4]).buffer);
                    sender.flush();
                } finally {
                    Config.BatchMaxBytes = prev;
                }
                assertCondition(flushed.join(",") === "1,2,1", `expected global batch limit flush groups, got ${flushed.join(",")}`);
                return flushed.join(",");
            },
        },
        {
            name: "progress_notify_supports_injected_sender",
            run: () => {
                const captured: Array<{
                    tag: string;
                    id: number;
                    step: number;
                    extra: Record<string, unknown>;
                    err?: Error;
                }> = [];
                const progress = new ProgressNotify("helper_core", (tag: string, id: number, step: number, extra: Record<string, unknown> = {}, err?: Error) => {
                    captured.push({ tag, id, step, extra, err });
                });
                progress.notify({ stage: "boot" });
                assertCondition(captured.length === 1, `expected exactly one captured payload, got ${captured.length}`);
                const payload = captured[0]!;
                assertCondition(payload.tag === "helper_core", `expected tag helper_core, got ${payload.tag}`);
                assertCondition(payload.step === 0, `expected first step 0, got ${payload.step}`);
                return String(payload.extra);
            },
        },
        {
            name: "help_aliases_point_to_grouped_facade",
            run: () => {
                assertCondition(help.$info === help.log.info, "expected help.$info to alias help.log.info");
                assertCondition(help.$error === help.log.error, "expected help.$error to alias help.log.error");
                assertCondition(help.assert === help.runtime.assert, "expected help.assert to alias help.runtime.assert");
                assertCondition(help.$send === help.runtime.send, "expected help.$send to alias help.runtime.send");
                assertCondition(help.progress.create("helper_core").tag === "helper_core", "expected help.progress.create() to build ProgressNotify");
                return "aliases-ok";
            },
        },
    ]);
}

import { Java } from "@zsa233/frida-analykit-agent";

import type { AgentUnitCase, AgentUnitCaseResult, AgentUnitSuiteResult } from "./types.js";

export function assertCondition(condition: unknown, message: string): asserts condition {
    if (!condition) {
        throw new Error(message);
    }
}

export function formatError(error: unknown): string {
    if (error instanceof Error) {
        return error.stack || error.message;
    }
    if (typeof error === "string") {
        return error;
    }
    try {
        return JSON.stringify(error);
    } catch {
        return String(error);
    }
}

export function runSuite(name: string, cases: AgentUnitCase[]): AgentUnitSuiteResult {
    const results: AgentUnitCaseResult[] = [];
    for (const item of cases) {
        try {
            const detail = item.run();
            results.push(detail ? { name: item.name, ok: true, detail } : { name: item.name, ok: true });
        } catch (error) {
            results.push({
                name: item.name,
                ok: false,
                error: formatError(error),
            });
        }
    }
    const passed = results.filter(item => item.ok).length;
    return {
        suite: name,
        passed,
        failed: results.length - passed,
        cases: results,
    };
}

export function ensureJavaAvailable(): void {
    assertCondition(Java.available, "Java bridge is unavailable in the current target process");
}

export function runJavaSuite(name: string, cases: AgentUnitCase[]): AgentUnitSuiteResult {
    ensureJavaAvailable();
    let result: AgentUnitSuiteResult | null = null;

    Java.performNow(() => {
        result = runSuite(name, cases);
    });

    return result ?? {
        suite: name,
        passed: 0,
        failed: 1,
        cases: [
            {
                name: "java_perform_now",
                ok: false,
                error: "Java.performNow did not execute",
            },
        ],
    };
}

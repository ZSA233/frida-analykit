import { AGENT_UNIT_SUITES } from "./suites/index.js";
import type { AgentUnitRpcExports, AgentUnitSuiteResult } from "./types.js";

export type { AgentUnitCaseResult, AgentUnitRpcExports, AgentUnitSuite, AgentUnitSuiteResult } from "./types.js";

export function listAgentUnitSuites(): string[] {
    return Object.keys(AGENT_UNIT_SUITES).sort();
}

export function runAgentUnitSuite(name: string): AgentUnitSuiteResult {
    const suite = AGENT_UNIT_SUITES[name];
    if (suite === undefined) {
        throw new Error(`unknown agent unit suite: ${name}`);
    }
    return suite();
}

export function installAgentUnitRpcExports(): void {
    const exportsObject = rpc.exports as AgentUnitRpcExports;
    exportsObject.listAgentUnitSuites = listAgentUnitSuites;
    exportsObject.runAgentUnitSuite = runAgentUnitSuite;
}

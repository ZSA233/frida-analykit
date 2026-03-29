export type AgentUnitCaseResult = {
    name: string;
    ok: boolean;
    detail?: string;
    error?: string;
};

export type AgentUnitSuiteResult = {
    suite: string;
    passed: number;
    failed: number;
    cases: AgentUnitCaseResult[];
};

export type AgentUnitCase = {
    name: string;
    run: () => string | void;
};

export type AgentUnitSuite = () => AgentUnitSuiteResult;

export type AgentUnitRpcExports = typeof rpc.exports & {
    listAgentUnitSuites?: () => string[];
    runAgentUnitSuite?: (name: string) => AgentUnitSuiteResult;
};

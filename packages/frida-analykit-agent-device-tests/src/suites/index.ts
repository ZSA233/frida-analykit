import type { AgentUnitSuite } from "../types.js";
import { runDexToolsSuite } from "./dex_tools.js";
import { runElfToolsSuite } from "./elf_tools.js";
import { runHelperCoreSuite } from "./helper_core.js";
import { runHelperRuntimeSuite } from "./helper_runtime.js";
import { runJniEnvWrappersSuite } from "./jni_env_wrappers.js";
import { runJniMemberFacadeArraysSuite } from "./jni_member_facade_arrays.js";
import { runJniMemberFacadeSuite } from "./jni_member_facade.js";
import { runJniMemberFacadeNonvirtualSuite } from "./jni_member_facade_nonvirtual.js";

export const AGENT_UNIT_SUITES: Record<string, AgentUnitSuite> = {
    dex_tools: runDexToolsSuite,
    elf_tools: runElfToolsSuite,
    helper_core: runHelperCoreSuite,
    helper_runtime: runHelperRuntimeSuite,
    jni_env_wrappers: runJniEnvWrappersSuite,
    jni_member_facade: runJniMemberFacadeSuite,
    jni_member_facade_arrays: runJniMemberFacadeArraysSuite,
    jni_member_facade_nonvirtual: runJniMemberFacadeNonvirtualSuite,
};

type EvalContext = Record<string, unknown>

const GLOBAL_OBJECT = globalThis as typeof globalThis & Record<string, unknown>

const BASE_CONTEXT_NAMES = [
    "Process",
    "Module",
    "Memory",
    "File",
    "hexdump",
    "ApiResolver",
    "Arm64Relocator",
    "Arm64Writer",
    "Stalker",
    "Thread",
    "Interceptor",
    "ModuleMap",
    "Frida",
    "Script",
    "Backtracer",
    "UInt64",
    "Int64",
    "Worker",
    "Object",
    "Array",
    "String",
    "Number",
    "Boolean",
    "Symbol",
    "BigInt",
    "Function",
    "Math",
    "Date",
    "RegExp",
    "Map",
    "Set",
    "WeakMap",
    "WeakSet",
    "Error",
    "TypeError",
    "SyntaxError",
    "JSON",
    "console",
    "isNaN",
    "isFinite",
    "parseInt",
    "parseFloat",
    "setTimeout",
    "clearTimeout",
    "setInterval",
    "clearInterval",
    "encodeURI",
    "decodeURI",
    "encodeURIComponent",
    "decodeURIComponent",
    "Reflect",
    "Proxy",
    "ArrayBuffer",
    "Int8Array",
    "Int16Array",
    "Int32Array",
    "Uint8Array",
    "Uint16Array",
    "Uint32Array",
    "NativePointer",
    "NativeFunction",
    "NativeCallback",
] as const

const ANALYKIT_GLOBAL_NAMES = [
    "Config",
    "LogLevel",
    "Java",
    "ObjC",
    "Swift",
    "help",
    "print",
    "printErr",
    "proc",
    "JNIEnv",
    "jobject",
    "jclass",
    "SSLTools",
    "BoringSSL",
    "ElfTools",
    "Libssl",
] as const

function pickGlobals(names: readonly string[]): EvalContext {
    const context: EvalContext = {}
    for (const name of names) {
        if (name in GLOBAL_OBJECT) {
            context[name] = GLOBAL_OBJECT[name]
        }
    }
    return context
}

function createBaseEvalContext(): EvalContext {
    // Read global bindings on every eval so later capability imports in `index.ts`
    // can extend the RPC surface without forcing `/rpc` to import those modules.
    return {
        ...pickGlobals(BASE_CONTEXT_NAMES),
        ...pickGlobals(ANALYKIT_GLOBAL_NAMES),
    }
}


export function evalWithContext(code: string, context: Record<string, unknown> = {}) {
    const mergedContext = { ...createBaseEvalContext(), ...context }
    const names = Object.keys(mergedContext)
    const values = Object.values(mergedContext)

    try {
        // REPL users usually type expressions like `Process.arch`; treat those as implicit returns.
        return Function(...names, `return (${code});`)(...values)
    } catch (error) {
        if (!(error instanceof SyntaxError)) {
            throw error
        }
        return Function(...names, code)(...values)
    }
}

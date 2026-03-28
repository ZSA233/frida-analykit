import { Java, ObjC, Swift } from "../bridges.js"
import { JNIEnv } from "../jni/env.js"
import { SSLTools } from "../net/ssl.js"
import { help } from "../helper.js"
import { Libssl } from "../lib/libssl.js"
import { proc } from "../process.js"
import { ElfTools } from "../elf/tools.js"

const BASE_EVAL_CONTEXT = {
    Java,
    Process,
    Module,
    Memory,
    ObjC,
    Swift,
    File,
    hexdump,
    ApiResolver,
    Arm64Relocator,
    Arm64Writer,
    Stalker,
    Thread,
    Interceptor,
    ModuleMap,
    Frida,
    Script,
    Backtracer,
    UInt64,
    Int64,
    Worker,

    help,
    proc,
    JNIEnv,
    SSLTools,
    ElfTools,
    Libssl,

    Object, Array, String, Number, Boolean, Symbol, BigInt, Function,
    Math, Date, RegExp, Map, Set, WeakMap, WeakSet,
    Error, TypeError, SyntaxError,
    JSON, console,
    isNaN, isFinite, parseInt, parseFloat,
    setTimeout, clearTimeout, setInterval, clearInterval,
    encodeURI, decodeURI, encodeURIComponent, decodeURIComponent,
    Reflect, Proxy,

    ArrayBuffer,
    Int8Array,
    Int16Array,
    Int32Array,
    Uint8Array,
    Uint16Array,
    Uint32Array,
    NativePointer,
    NativeFunction,
    NativeCallback,
}


export function evalWithContext(code: string, context: { [key: string]: any } = {}) {
    const mergedContext = { ...BASE_EVAL_CONTEXT, ...context }
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

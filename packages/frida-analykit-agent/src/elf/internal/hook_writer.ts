import { nativeFunctionOptions } from "../../internal/frida/native-function.js"
import type { ElfModuleX } from "../module.js"
import type { Sym } from "../struct.js"
import type { ElfSymbolHookOptions, ElfSymbolHookResult } from "../types.js"

type HookWriterContext = {
    module: ElfModuleX
    keepAlive: Record<string, NativePointer>
    lazySymbols: Record<string, Sym>
}

function requirePointer(value: NativePointer | null | undefined, message: string): NativePointer {
    if (value === null || value === undefined || value.isNull()) {
        throw new Error(message)
    }
    return value
}

function createLazySymbol(name: string, implPtr: NativePointer | null = null): Sym {
    return {
        name,
        relocPtr: null,
        hook: null,
        implPtr,
        linked: false,
        st_name: 0,
        st_info: 0,
        st_other: 0,
        st_shndx: 0,
        st_value: implPtr,
        st_size: 0,
    }
}

export function expandVariadicArgTypes(
    argTypes: NativeFunctionArgumentType[] | [],
    variadicRepeat = 5,
): NativeFunctionArgumentType[] | [] {
    const values = [...argTypes] as NativeFunctionArgumentType[]
    const variadicIndex = values.indexOf("..." as NativeFunctionArgumentType)
    if (variadicIndex === -1 || variadicRepeat <= 0) {
        return values
    }
    return [
        ...values.slice(0, variadicIndex),
        ...Array(variadicRepeat).fill(values.slice(variadicIndex + 1)).flat(),
    ]
}

function createNativeHookCallback(
    hookName: string,
    fn: AnyFunction,
    retType: NativeFunctionReturnType,
    argTypes: NativeFunctionArgumentType[] | [],
    abi: NativeABI | undefined,
    getImplementationHandle: () => NativePointer,
): NativePointer {
    let implementation: AnyFunction | null = null
    const callbackArgTypes = argTypes.filter((item) => item !== "...") as NativeCallbackArgumentType[] | []
    const wrapper = function (...args: unknown[]) {
        if (implementation === null) {
            implementation = new NativeFunction(
                getImplementationHandle(),
                retType,
                argTypes,
                nativeFunctionOptions,
            )
        }
        return fn(implementation, ...args)
    }
    const callback = new NativeCallback(wrapper, retType, callbackArgTypes, abi)
    return callback
}

export function installElfSymbolHook(
    context: HookWriterContext,
    hookName: string,
    fn: AnyFunction,
    retType: NativeFunctionReturnType,
    argTypes: NativeFunctionArgumentType[] | [],
    options: ElfSymbolHookOptions = {},
): ElfSymbolHookResult {
    const expandedArgTypes = expandVariadicArgTypes(argTypes, options.variadicRepeat)
    const symbol = context.module.findSymbol(hookName)

    if (symbol?.implPtr && !symbol.implPtr.isNull()) {
        // Prefer implementation hooks when the symbol is already resolved. A relocation-only
        // patch would miss direct NativeFunction calls to the symbol implementation.
        let originalHandle: NativePointer | null = null
        const callback = createNativeHookCallback(
            hookName,
            fn,
            retType,
            expandedArgTypes,
            options.abi,
            () => requirePointer(originalHandle, `[ElfSymbolHooks] original trampoline missing for ${hookName}`),
        )
        const trampoline = Interceptor.replaceFast(symbol.implPtr, callback)
        if (trampoline.isNull()) {
            throw new Error(`[ElfSymbolHooks] failed to install replaceFast hook for ${hookName}`)
        }
        originalHandle = trampoline
        context.keepAlive[hookName] = callback
        symbol.hook = callback
        Interceptor.flush()
        return callback
    }

    if (symbol?.relocPtr && symbol.st_value) {
        return context.module.attachSymbol(
            hookName,
            fn,
            retType,
            expandedArgTypes as NativeFunctionArgumentType[] | [],
            options.abi,
        )
    }

    const lazySymbol = symbol || createLazySymbol(hookName)
    const callback = createNativeHookCallback(
        hookName,
        fn,
        retType,
        expandedArgTypes,
        options.abi,
        () => requirePointer(lazySymbol.implPtr, `[ElfSymbolHooks] unresolved symbol ${hookName}`),
    )
    lazySymbol.hook = callback
    context.keepAlive[hookName] = callback
    if (!symbol) {
        context.lazySymbols[hookName] = lazySymbol
    }
    return callback
}

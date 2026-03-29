import { Java } from "../../bridges.js";
import { nativeFunctionOptions } from "../../consts.js";
import { NativePointerObject } from "../../helper.js";
import { IndirectRefKind } from "./struct.js";
import type { jmethodID } from "./refs.js";

export interface JavaLangClass {
    readonly handle: NativePointer;
    readonly getName: NativePointer;
    readonly getSimpleName: NativePointer;
    readonly getGenericSuperclass: NativePointer;
    readonly getDeclaredConstructors: NativePointer;
    readonly getDeclaredMethods: NativePointer;
    readonly getDeclaredFields: NativePointer;
    readonly isArray: NativePointer;
    readonly isPrimitive: NativePointer;
    readonly isInterface: NativePointer;
    readonly getComponentType: NativePointer;
}

export interface JavaLangObject {
    readonly handle: NativePointer;
    readonly toString: NativePointer;
    readonly getClass: NativePointer;
}

export interface JavaLangReflectMethod {
    readonly getName: NativePointer;
    readonly getGenericParameterTypes: NativePointer;
    readonly getParameterTypes: NativePointer;
    getReturnType: jmethodID;
    readonly getGenericReturnType: NativePointer;
    readonly getGenericExceptionTypes: NativePointer;
    readonly getModifiers: NativePointer;
    readonly isVarArgs: NativePointer;
}

export interface JavaLangReflectField {
    readonly getName: NativePointer;
    readonly getType: NativePointer;
    readonly getGenericType: NativePointer;
    readonly getModifiers: NativePointer;
    readonly toString: NativePointer;
}

export interface JavaLangReflectConstructor {
    readonly getGenericParameterTypes: NativePointer;
}

export interface JavaLangReflectTypeVariable {
    readonly handle: NativePointer;
    readonly getName: NativePointer;
    readonly getBounds: NativePointer;
    readonly getGenericDeclaration: NativePointer;
}

export interface JavaLangReflectWildcardType {
    readonly handle: NativePointer;
    readonly getLowerBounds: NativePointer;
    readonly getUpperBounds: NativePointer;
}

export interface JavaLangReflectGenericArrayType {
    readonly handle: NativePointer;
    readonly getGenericComponentType: NativePointer;
}

export interface JavaLangReflectParameterizedType {
    readonly handle: NativePointer;
    readonly getActualTypeArguments: NativePointer;
    readonly getRawType: NativePointer;
    readonly getOwnerType: NativePointer;
}

export interface JavaLangString {
    readonly handle: NativePointer;
}

export interface ExtendedJavaEnv extends Java.Env {
    javaLangClass(): JavaLangClass;
    javaLangObject(): JavaLangObject;
    javaLangReflectMethod(): JavaLangReflectMethod;
    javaLangReflectField(): JavaLangReflectField;
    javaLangReflectConstructor(): JavaLangReflectConstructor;
    javaLangReflectTypeVariable(): JavaLangReflectTypeVariable;
    javaLangReflectWildcardType(): JavaLangReflectWildcardType;
    javaLangReflectGenericArrayType(): JavaLangReflectGenericArrayType;
    javaLangReflectParameterizedType(): JavaLangReflectParameterizedType;
    javaLangString(): JavaLangString;
}

export type JniValueConstructor<RetType> = { new(obj: NativePointer, opt?: object): RetType };

export type JniMethod<RetType> = ((...args: unknown[]) => RetType) & {
    $handle: NativePointer | undefined;
};

type NativeFuncCache = {
    handle: NativePointer;
    impl: AnyFunction;
};

type JniReturnType = NativeFunctionReturnType | "bool";
type JniArgumentType = NativeFunctionArgumentType | "...";
type ResolvedJniArgument = {
    type: NativeFunctionArgumentType;
    value: NativeFunctionArgumentValue;
};
type PrimitiveWrapper = {
    toBool?: () => boolean;
    toByte?: () => number;
    toChar?: () => number;
    toShort?: () => number;
    toInt?: () => number;
    toLong?: () => number;
    toFloat?: () => number;
    toDouble?: () => number;
};

function clz(value: number): number {
    const normalized = value >>> 0;
    return normalized === 0 ? 32 : 32 - normalized.toString(2).length;
}

function minimumBitsToStore(value: number): number {
    return (value === 0 ? -1 : (32 - 1 - clz(value))) + 1;
}

export const JNI_REF_KIND_BITS = minimumBitsToStore(IndirectRefKind.kLastKind);
export const JNI_REF_KIND_MASK = (1 << JNI_REF_KIND_BITS) - 1;

// In Frida, types listed after "..." become the repeated type for every variadic argument.
// JNI Call*Method/NewObject varargs may carry promoted primitives, so these signatures must stop at "...".
export const callMethodVariadicArgTypes: JniArgumentType[] = ["pointer", "pointer", "pointer", "..."];
export const callNonvirtualMethodVariadicArgTypes: JniArgumentType[] = [
    "pointer",
    "pointer",
    "pointer",
    "pointer",
    "...",
];

function normalizeFixedJniArgument(value: unknown): unknown {
    if (!(value instanceof NativePointerObject)) {
        return value;
    }
    // Fixed-arity JNI APIs such as Set*Field take real primitive values, not opaque wrapper handles.
    // Normalize primitive wrappers here so callers can pass either JS scalars or existing j* wrappers.
    const primitiveValue = value as unknown as PrimitiveWrapper;
    if (typeof primitiveValue.toBool === "function") {
        return primitiveValue.toBool() ? 1 : 0;
    }
    if (typeof primitiveValue.toByte === "function") {
        return primitiveValue.toByte();
    }
    if (typeof primitiveValue.toChar === "function") {
        return primitiveValue.toChar();
    }
    if (typeof primitiveValue.toShort === "function") {
        return primitiveValue.toShort();
    }
    if (typeof primitiveValue.toInt === "function") {
        return primitiveValue.toInt();
    }
    if (typeof primitiveValue.toLong === "function") {
        return primitiveValue.toLong();
    }
    if (typeof primitiveValue.toFloat === "function") {
        return primitiveValue.toFloat();
    }
    if (typeof primitiveValue.toDouble === "function") {
        return primitiveValue.toDouble();
    }
    return value.$handle;
}

function resolveJniVariadicArgument(value: unknown): ResolvedJniArgument {
    if (value === null || value === undefined) {
        return {
            type: "pointer",
            value: NULL,
        };
    }
    if (value instanceof NativePointerObject) {
        const primitiveValue = value as unknown as PrimitiveWrapper;
        if (typeof primitiveValue.toBool === "function") {
            return { type: "int", value: primitiveValue.toBool() ? 1 : 0 };
        }
        if (typeof primitiveValue.toByte === "function") {
            return { type: "int", value: primitiveValue.toByte() };
        }
        if (typeof primitiveValue.toChar === "function") {
            return { type: "int", value: primitiveValue.toChar() };
        }
        if (typeof primitiveValue.toShort === "function") {
            return { type: "int", value: primitiveValue.toShort() };
        }
        if (typeof primitiveValue.toInt === "function") {
            return { type: "int", value: primitiveValue.toInt() };
        }
        if (typeof primitiveValue.toLong === "function") {
            return { type: "int64", value: primitiveValue.toLong() };
        }
        if (typeof primitiveValue.toFloat === "function") {
            return { type: "double", value: primitiveValue.toFloat() };
        }
        if (typeof primitiveValue.toDouble === "function") {
            return { type: "double", value: primitiveValue.toDouble() };
        }
        return {
            type: "pointer",
            value: value.$handle,
        };
    }
    if (value instanceof NativePointer) {
        return { type: "pointer", value };
    }
    if (value instanceof Int64) {
        return { type: "int64", value };
    }
    if (value instanceof UInt64) {
        return { type: "uint64", value };
    }
    if (typeof value === "boolean") {
        return { type: "int", value: value ? 1 : 0 };
    }
    if (typeof value === "number") {
        if (Number.isInteger(value)) {
            if (value >= -0x80000000 && value <= 0x7fffffff) {
                return { type: "int", value };
            }
            return { type: "int64", value };
        }
        return { type: "double", value };
    }
    throw new Error(`unsupported JNI variadic argument: ${value}`);
}

export function getThreadFromEnv(env: ExtendedJavaEnv): NativePointer {
    return env.handle.add(Process.pointerSize).readPointer();
}

export class JniEnvBase {
    private static readonly ptrSize = Process.pointerSize;
    private readonly _vm?: Java.VM;

    constructor(vm?: Java.VM) {
        this._vm = vm;
    }

    get $env(): ExtendedJavaEnv {
        return this.$vm.getEnv() as ExtendedJavaEnv;
    }

    get $vm(): Java.VM {
        return this._vm ?? Java.vm;
    }

    get $thread(): NativePointer {
        return this.$env.handle.add(JniEnvBase.ptrSize).readPointer();
    }

    $proxy<RetType>(
        wrapFunc: AnyFunction,
        retType: JniReturnType,
        argTypes: JniArgumentType[],
        index: number,
        constructor: JniValueConstructor<RetType> | null = null,
        optBuilder?: (...args: unknown[]) => object,
    ): JniMethod<RetType> {
        let cache: NativeFuncCache | null = null;
        let handle: NativePointer | null = null;
        const variadicIndex = argTypes.indexOf("...");
        const variadicCaches = new Map<string, AnyFunction>();

        const getHandle = (): NativePointer => {
            if (handle === null) {
                const env = this.$env;
                const vtable = env.handle.readPointer();
                handle = vtable.add(index * JniEnvBase.ptrSize).readPointer();
            }
            return handle!;
        };

        const getCache = (resolvedArgTypes: NativeFunctionArgumentType[] | null = null): NativeFuncCache => {
            const nativeHandle = getHandle();
            if (variadicIndex === -1) {
                if (cache === null) {
                    cache = {
                        handle: nativeHandle,
                        impl: new NativeFunction(nativeHandle, retType, argTypes, nativeFunctionOptions),
                    };
                }
                return cache;
            }

            const actualArgTypes = resolvedArgTypes ?? [];
            const cacheKey = actualArgTypes.join(",");
            let impl = variadicCaches.get(cacheKey);
            if (impl === undefined) {
                impl = new NativeFunction(nativeHandle, retType, actualArgTypes, nativeFunctionOptions);
                variadicCaches.set(cacheKey, impl);
            }
            return {
                handle: nativeHandle,
                impl,
            };
        };

        const func = (...args: unknown[]): RetType => {
            const env = this.$env;
            let resolvedArgs = args.map(normalizeFixedJniArgument);
            let resolvedArgTypes: NativeFunctionArgumentType[] | null = null;

            if (variadicIndex !== -1) {
                const fixedArgCount = variadicIndex - 1;
                const fixedArgs = args.slice(0, fixedArgCount).map(normalizeFixedJniArgument);
                const variadicArgs = args.slice(fixedArgCount).map(resolveJniVariadicArgument);
                resolvedArgs = fixedArgs.concat(variadicArgs.map(item => item.value));
                resolvedArgTypes = argTypes
                    .slice(0, variadicIndex)
                    .concat(variadicArgs.map(item => item.type)) as NativeFunctionArgumentType[];
            }

            const { impl } = getCache(resolvedArgTypes);
            const result = wrapFunc.apply(env, [impl, ...resolvedArgs]);
            if (constructor === null) {
                return result;
            }
            const options = optBuilder?.(...args) ?? {};
            return new constructor(result as unknown as NativePointer, options);
        };

        Object.defineProperty(func, "$handle", {
            get: () => getHandle(),
        });

        return func as JniMethod<RetType>;
    }

    $symbol<RetType>(
        wrapFunc: AnyFunction,
        retType: JniReturnType,
        argTypes: JniArgumentType[],
        symbol: string,
        constructor: JniValueConstructor<RetType> | null = null,
    ): JniMethod<RetType> {
        let cache: NativeFuncCache | null = null;

        const getCache = (): NativeFuncCache => {
            if (cache === null) {
                const fallbackFinder = (name: string): NativePointer | null => {
                    const { module } = Java.api;
                    return module.findExportByName(name) ?? module.findSymbolByName(name);
                };
                const handle = Java.api.find?.(symbol) ?? fallbackFinder(symbol);
                if (handle === null) {
                    throw new Error(`symbol[${symbol}] does not exist in art/dalvik`);
                }
                cache = {
                    handle,
                    impl: new NativeFunction(handle, retType, argTypes, nativeFunctionOptions),
                };
            }
            return cache;
        };

        const func = (...args: unknown[]): RetType => {
            const env = this.$env;
            const { impl } = getCache();
            const normalizedArgs = args.map(value => value instanceof NativePointerObject ? value.$handle : value);
            const result = wrapFunc.apply(env, [impl, ...normalizedArgs]);
            if (constructor === null) {
                return result;
            }
            return new constructor(result as unknown as NativePointer);
        };

        Object.defineProperty(func, "$handle", {
            get: () => getCache().handle,
        });

        return func as JniMethod<RetType>;
    }
}

export function proxyCallMethod<RetType>(
    env: JniEnvBase,
    slot: number,
        constructor: JniValueConstructor<RetType> | null = null,
    {
        retType = "pointer",
        argTypes = ["pointer", "pointer", "pointer", "pointer"],
    }: {
        retType?: JniReturnType;
        argTypes?: JniArgumentType[];
    } = {},
): JniMethod<RetType> {
    return env.$proxy(
        function (this: ExtendedJavaEnv, impl: AnyFunction, ...args: unknown[]): RetType {
            return impl(this.handle, ...args) as RetType;
        },
        retType,
        argTypes,
        slot,
        constructor,
    );
}

export function proxyCallNonvirtualMethod<RetType>(
    env: JniEnvBase,
    slot: number,
        constructor: JniValueConstructor<RetType> | null = null,
    {
        retType = "pointer",
        argTypes = ["pointer", "pointer", "pointer", "pointer", "pointer"],
    }: {
        retType?: JniReturnType;
        argTypes?: JniArgumentType[];
    } = {},
): JniMethod<RetType> {
    return proxyCallMethod(env, slot, constructor, { retType, argTypes });
}

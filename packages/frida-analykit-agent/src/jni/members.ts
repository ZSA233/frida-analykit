import type { JniCallArgument } from "./call_methods.js";
import { JNIEnv } from "./env.js";
import {
    jboolean,
    jbooleanArray,
    jbyte,
    jbyteArray,
    jchar,
    jcharArray,
    jclass,
    jdouble,
    jdoubleArray,
    jfieldID,
    jfloat,
    jfloatArray,
    jint,
    jintArray,
    jlong,
    jlongArray,
    jmethodID,
    jobject,
    jobjectArray,
    jshort,
    jshortArray,
    jthrowable,
    jvoid,
} from "./refs.js";
import type { JniFieldSetterValue } from "./runtime_fields.js";
import {
    getInstanceCallMethodName,
    getInstanceFieldGetMethodName,
    getInstanceFieldSetMethodName,
    getNonvirtualCallMethodName,
    getStaticCallMethodName,
    getStaticFieldGetMethodName,
    getStaticFieldSetMethodName,
    parseFieldDescriptor,
    parseMethodDescriptor,
    type JniTypeDescriptorInfo,
} from "./signatures.js";
import type { jstring } from "./strings.js";

type JniEnvMethod = (...args: any[]) => any;

const METHOD_ID_CACHE = new Map<string, jmethodID>();
const FIELD_ID_CACHE = new Map<string, jfieldID>();

export type JniMemberHostKind = "instance" | "class";
export type JniAnyObject = jobject<JniMemberHostKind>;
export type JniMemberTarget = JniAnyObject | NativePointerValue;

export type JniNonVoidPrimitiveValue =
    | jboolean
    | jbyte
    | jchar
    | jshort
    | jint
    | jlong
    | jfloat
    | jdouble;

export type JniObjectLikeValue =
    | jobject
    | jclass
    | jthrowable
    | jstring
    | jobjectArray
    | jbooleanArray
    | jbyteArray
    | jcharArray
    | jshortArray
    | jintArray
    | jlongArray
    | jfloatArray
    | jdoubleArray;

export type JniFieldValue = JniNonVoidPrimitiveValue | JniObjectLikeValue;
export type JniMethodValue = JniFieldValue | jvoid;

export interface JniBoundInstanceMethod<Ret extends JniMethodValue = JniMethodValue> {
    readonly $id: jmethodID;
    call(...args: JniCallArgument[]): Ret;
    withLocal<Result>(use: (value: Ret) => Result, ...args: JniCallArgument[]): Result;
}

export interface JniUnboundInstanceMethod<Ret extends JniMethodValue = JniMethodValue> {
    readonly $id: jmethodID;
    call(target: JniMemberTarget, ...args: JniCallArgument[]): Ret;
    withLocal<Result>(
        target: JniMemberTarget,
        use: (value: Ret) => Result,
        ...args: JniCallArgument[]
    ): Result;
}

export interface JniBoundStaticMethod<Ret extends JniMethodValue = JniMethodValue> {
    readonly $id: jmethodID;
    call(...args: JniCallArgument[]): Ret;
    withLocal<Result>(use: (value: Ret) => Result, ...args: JniCallArgument[]): Result;
}

export interface JniBoundNonvirtualMethod<Ret extends JniMethodValue = JniMethodValue> {
    readonly $id: jmethodID;
    readonly $declaringClass: jclass;
    call(...args: JniCallArgument[]): Ret;
    withLocal<Result>(use: (value: Ret) => Result, ...args: JniCallArgument[]): Result;
}

export interface JniUnboundNonvirtualMethod<Ret extends JniMethodValue = JniMethodValue> {
    readonly $id: jmethodID;
    readonly $declaringClass: jclass;
    call(target: JniMemberTarget, ...args: JniCallArgument[]): Ret;
    withLocal<Result>(
        target: JniMemberTarget,
        use: (value: Ret) => Result,
        ...args: JniCallArgument[]
    ): Result;
}

export interface JniBoundInstanceField<Value extends JniFieldValue = JniFieldValue> {
    readonly $id: jfieldID;
    get(): Value;
    set(value: JniFieldSetterValue<Value>): void;
    withLocal<Result>(use: (value: Value) => Result): Result;
}

export interface JniUnboundInstanceField<Value extends JniFieldValue = JniFieldValue> {
    readonly $id: jfieldID;
    get(target: JniMemberTarget): Value;
    set(target: JniMemberTarget, value: JniFieldSetterValue<Value>): void;
    withLocal<Result>(target: JniMemberTarget, use: (value: Value) => Result): Result;
}

export interface JniBoundStaticField<Value extends JniFieldValue = JniFieldValue> {
    readonly $id: jfieldID;
    get(): Value;
    set(value: JniFieldSetterValue<Value>): void;
    withLocal<Result>(use: (value: Value) => Result): Result;
}

export interface JniConstructorAccessor<Ret extends jobject = jobject> {
    readonly $id: jmethodID;
    newInstance(...args: JniCallArgument[]): Ret;
    withLocal<Result>(use: (value: Ret) => Result, ...args: JniCallArgument[]): Result;
}

export type JniInstanceMethodAccessorFor<
    Kind extends JniMemberHostKind,
    Ret extends JniMethodValue = JniMethodValue,
> = Kind extends "class" ? JniUnboundInstanceMethod<Ret> : JniBoundInstanceMethod<Ret>;

export type JniInstanceFieldAccessorFor<
    Kind extends JniMemberHostKind,
    Value extends JniFieldValue = JniFieldValue,
> = Kind extends "class" ? JniUnboundInstanceField<Value> : JniBoundInstanceField<Value>;

function getEnvMethod(name: string): JniEnvMethod {
    return (JNIEnv as unknown as Record<string, JniEnvMethod>)[name];
}

function withLocalValue<Value, Result>(value: Value, use: (value: Value) => Result): Result {
    if (!(value instanceof jobject)) {
        return use(value);
    }
    try {
        return use(value);
    } finally {
        value.$unref();
    }
}

function requireUnboundMethodTarget(args: unknown[]): [JniMemberTarget, ...JniCallArgument[]] {
    if (args.length === 0) {
        throw new Error("unbound JNI method accessor requires an explicit target object");
    }
    return args as [JniMemberTarget, ...JniCallArgument[]];
}

function requireUnboundFieldTarget(args: unknown[]): JniMemberTarget {
    if (args.length === 0) {
        throw new Error("unbound JNI field accessor requires an explicit target object");
    }
    return args[0] as JniMemberTarget;
}

function requireUnboundFieldSetArgs<Value>(args: unknown[]): [JniMemberTarget, JniFieldSetterValue<Value>] {
    if (args.length < 2) {
        throw new Error("unbound JNI field accessor requires an explicit target object and value");
    }
    return args as [JniMemberTarget, JniFieldSetterValue<Value>];
}

function requireUnboundWithLocalArgs<Result, Value>(
    args: unknown[],
): [JniMemberTarget, (value: Value) => Result] {
    if (args.length < 2) {
        throw new Error("unbound JNI accessor withLocal() requires an explicit target object and callback");
    }
    return args as [JniMemberTarget, (value: Value) => Result];
}

function requireNoBoundArgs(args: unknown[], message: string): void {
    if (args.length !== 0) {
        throw new Error(message);
    }
}

function requireBoundValueArg<Value>(args: unknown[], message: string): JniFieldSetterValue<Value> {
    if (args.length !== 1) {
        throw new Error(message);
    }
    return args[0] as JniFieldSetterValue<Value>;
}

function requireBoundCallbackArg<Result, Value>(args: unknown[], message: string): (value: Value) => Result {
    if (args.length !== 1 || typeof args[0] !== "function") {
        throw new Error(message);
    }
    return args[0] as (value: Value) => Result;
}

function memberCacheKey(
    clazz: jclass,
    kind: "method" | "field" | "constructor",
    isStatic: boolean,
    name: string,
    sig: string,
): string {
    return `${clazz.$handle.toString()}:${kind}:${isStatic ? "static" : "instance"}:${name}:${sig}`;
}

function wrapObjectLikeValue(value: jobject<JniMemberHostKind>, typeInfo: JniTypeDescriptorInfo): JniObjectLikeValue {
    if (typeInfo.kind === "array") {
        const options = value.$unwrap();
        if (typeInfo.descriptor.length === 2) {
            switch (typeInfo.descriptor[1]) {
                case "Z":
                    return new jbooleanArray(value.$handle, options);
                case "B":
                    return new jbyteArray(value.$handle, options);
                case "C":
                    return new jcharArray(value.$handle, options);
                case "S":
                    return new jshortArray(value.$handle, options);
                case "I":
                    return new jintArray(value.$handle, options);
                case "J":
                    return new jlongArray(value.$handle, options);
                case "F":
                    return new jfloatArray(value.$handle, options);
                case "D":
                    return new jdoubleArray(value.$handle, options);
            }
        }
        return new jobjectArray(value.$handle, options);
    }

    switch (typeInfo.descriptor) {
        case "Ljava/lang/String;":
            return value.$jstring;
        case "Ljava/lang/Class;":
            return value.$jclass;
        case "Ljava/lang/Throwable;":
            return new jthrowable(value.$handle, value.$unwrap());
        default:
            return value;
    }
}

function wrapTypedValue<Value extends JniMethodValue | JniFieldValue>(
    value: Value,
    typeInfo: JniTypeDescriptorInfo,
): Value {
    if (!(value instanceof jobject) || !typeInfo.isObjectLike) {
        return value;
    }
    return wrapObjectLikeValue(value, typeInfo) as Value;
}

function normalizeFieldSetValue(typeInfo: JniTypeDescriptorInfo, value: JniFieldSetterValue): JniFieldSetterValue {
    if (typeInfo.isObjectLike && (value === null || value === undefined)) {
        return NULL;
    }
    return value;
}

export function lookupMethodIdFor(clazz: jclass, name: string, sig: string): jmethodID {
    const key = memberCacheKey(clazz, "method", false, name, sig);
    let cached = METHOD_ID_CACHE.get(key);
    if (cached === undefined) {
        cached = JNIEnv.GetMethodID(clazz, name, sig);
        METHOD_ID_CACHE.set(key, cached);
    }
    return cached;
}

export function lookupStaticMethodIdFor(clazz: jclass, name: string, sig: string): jmethodID {
    const key = memberCacheKey(clazz, "method", true, name, sig);
    let cached = METHOD_ID_CACHE.get(key);
    if (cached === undefined) {
        cached = JNIEnv.GetStaticMethodID(clazz, name, sig);
        METHOD_ID_CACHE.set(key, cached);
    }
    return cached;
}

export function lookupConstructorIdFor(clazz: jclass, sig: string): jmethodID {
    const key = memberCacheKey(clazz, "constructor", false, "<init>", sig);
    let cached = METHOD_ID_CACHE.get(key);
    if (cached === undefined) {
        cached = JNIEnv.GetMethodID(clazz, "<init>", sig);
        METHOD_ID_CACHE.set(key, cached);
    }
    return cached;
}

export function lookupFieldIdFor(clazz: jclass, name: string, sig: string): jfieldID {
    const key = memberCacheKey(clazz, "field", false, name, sig);
    let cached = FIELD_ID_CACHE.get(key);
    if (cached === undefined) {
        cached = JNIEnv.GetFieldID(clazz, name, sig);
        FIELD_ID_CACHE.set(key, cached);
    }
    return cached;
}

export function lookupStaticFieldIdFor(clazz: jclass, name: string, sig: string): jfieldID {
    const key = memberCacheKey(clazz, "field", true, name, sig);
    let cached = FIELD_ID_CACHE.get(key);
    if (cached === undefined) {
        cached = JNIEnv.GetStaticFieldID(clazz, name, sig);
        FIELD_ID_CACHE.set(key, cached);
    }
    return cached;
}

export function createBoundInstanceMethod<Ret extends JniMethodValue = JniMethodValue>(
    target: JniAnyObject,
    name: string,
    sig: string,
): JniBoundInstanceMethod<Ret> {
    const parsed = parseMethodDescriptor(sig);
    const methodId = lookupMethodIdFor(target.$class, name, sig);
    const methodName = getInstanceCallMethodName(sig);

    const call = (...args: JniCallArgument[]): Ret => {
        const result = getEnvMethod(methodName)(target, methodId, ...args) as JniMethodValue;
        return wrapTypedValue(result, parsed.returnType) as Ret;
    };

    return {
        $id: methodId,
        call,
        withLocal<Result>(...args: unknown[]): Result {
            if (typeof args[0] !== "function") {
                throw new Error("bound JNI method accessor is already bound to a target; use withLocal(use, ...args)");
            }
            const [use, ...callArgs] = args as [(value: Ret) => Result, ...JniCallArgument[]];
            return withLocalValue(call(...callArgs), use);
        },
    };
}

export function createUnboundInstanceMethod<Ret extends JniMethodValue = JniMethodValue>(
    clazz: jclass,
    name: string,
    sig: string,
): JniUnboundInstanceMethod<Ret> {
    const parsed = parseMethodDescriptor(sig);
    const methodId = lookupMethodIdFor(clazz, name, sig);
    const methodName = getInstanceCallMethodName(sig);

    const call = (...args: unknown[]): Ret => {
        const [target, ...callArgs] = requireUnboundMethodTarget(args);
        const result = getEnvMethod(methodName)(target, methodId, ...callArgs) as JniMethodValue;
        return wrapTypedValue(result, parsed.returnType) as Ret;
    };

    return {
        $id: methodId,
        call,
        withLocal<Result>(target: JniMemberTarget, use: (value: Ret) => Result, ...callArgs: JniCallArgument[]): Result {
            // Keep this runtime guard for `any` / plain-JS callers that bypass the type layer.
            if (arguments.length < 2) {
                throw new Error("unbound JNI method accessor withLocal() requires an explicit target object and callback");
            }
            return withLocalValue(call(target, ...callArgs), use);
        },
    };
}

export function createBoundStaticMethod<Ret extends JniMethodValue = JniMethodValue>(
    clazz: jclass,
    name: string,
    sig: string,
): JniBoundStaticMethod<Ret> {
    const parsed = parseMethodDescriptor(sig);
    const methodId = lookupStaticMethodIdFor(clazz, name, sig);
    const methodName = getStaticCallMethodName(sig);

    const call = (...args: JniCallArgument[]): Ret => {
        const result = getEnvMethod(methodName)(clazz, methodId, ...args) as JniMethodValue;
        return wrapTypedValue(result, parsed.returnType) as Ret;
    };

    return {
        $id: methodId,
        call,
        withLocal<Result>(use: (value: Ret) => Result, ...args: JniCallArgument[]): Result {
            return withLocalValue(call(...args), use);
        },
    };
}

export function createBoundNonvirtualMethod<Ret extends JniMethodValue = JniMethodValue>(
    target: JniAnyObject,
    clazz: jclass,
    name: string,
    sig: string,
): JniBoundNonvirtualMethod<Ret> {
    const parsed = parseMethodDescriptor(sig);
    const methodId = lookupMethodIdFor(clazz, name, sig);
    const methodName = getNonvirtualCallMethodName(sig);

    const call = (...args: JniCallArgument[]): Ret => {
        const result = getEnvMethod(methodName)(target, clazz, methodId, ...args) as JniMethodValue;
        return wrapTypedValue(result, parsed.returnType) as Ret;
    };

    return {
        $id: methodId,
        $declaringClass: clazz,
        call,
        withLocal<Result>(use: (value: Ret) => Result, ...args: JniCallArgument[]): Result {
            return withLocalValue(call(...args), use);
        },
    };
}

export function createUnboundNonvirtualMethod<Ret extends JniMethodValue = JniMethodValue>(
    clazz: jclass,
    name: string,
    sig: string,
): JniUnboundNonvirtualMethod<Ret> {
    const parsed = parseMethodDescriptor(sig);
    const methodId = lookupMethodIdFor(clazz, name, sig);
    const methodName = getNonvirtualCallMethodName(sig);

    const call = (target: JniMemberTarget, ...args: JniCallArgument[]): Ret => {
        const result = getEnvMethod(methodName)(target, clazz, methodId, ...args) as JniMethodValue;
        return wrapTypedValue(result, parsed.returnType) as Ret;
    };

    return {
        $id: methodId,
        $declaringClass: clazz,
        call,
        withLocal<Result>(
            target: JniMemberTarget,
            use: (value: Ret) => Result,
            ...args: JniCallArgument[]
        ): Result {
            return withLocalValue(call(target, ...args), use);
        },
    };
}

export function createBoundInstanceField<Value extends JniFieldValue = JniFieldValue>(
    target: JniAnyObject,
    name: string,
    sig: string,
): JniBoundInstanceField<Value> {
    const parsed = parseFieldDescriptor(sig);
    const fieldId = lookupFieldIdFor(target.$class, name, sig);
    const getterName = getInstanceFieldGetMethodName(sig);
    const setterName = getInstanceFieldSetMethodName(sig);

    const get = (): Value => {
        const result = getEnvMethod(getterName)(target, fieldId) as JniFieldValue;
        return wrapTypedValue(result, parsed) as Value;
    };

    return {
        $id: fieldId,
        get(...args: unknown[]): Value {
            // Keep these guards for `any` / plain-JS callers after the public accessor types were narrowed.
            requireNoBoundArgs(args, "bound JNI field accessor is already bound to a target; use get()");
            return get();
        },
        set(...args: unknown[]): void {
            const value = requireBoundValueArg<Value>(args, "bound JNI field accessor is already bound to a target; use set(value)");
            // Keep this runtime normalization so bound field setters still accept scalar JS inputs.
            getEnvMethod(setterName)(target, fieldId, normalizeFieldSetValue(parsed, value));
        },
        withLocal<Result>(...args: unknown[]): Result {
            const use = requireBoundCallbackArg<Result, Value>(
                args,
                "bound JNI field accessor is already bound to a target; use withLocal(use)",
            );
            return withLocalValue(get(), use);
        },
    };
}

export function createUnboundInstanceField<Value extends JniFieldValue = JniFieldValue>(
    clazz: jclass,
    name: string,
    sig: string,
): JniUnboundInstanceField<Value> {
    const parsed = parseFieldDescriptor(sig);
    const fieldId = lookupFieldIdFor(clazz, name, sig);
    const getterName = getInstanceFieldGetMethodName(sig);
    const setterName = getInstanceFieldSetMethodName(sig);

    const get = (target: JniMemberTarget): Value => {
        const result = getEnvMethod(getterName)(target, fieldId) as JniFieldValue;
        return wrapTypedValue(result, parsed) as Value;
    };

    return {
        $id: fieldId,
        get(...args: unknown[]): Value {
            return get(requireUnboundFieldTarget(args));
        },
        set(...args: unknown[]): void {
            const [target, value] = requireUnboundFieldSetArgs<Value>(args);
            getEnvMethod(setterName)(target, fieldId, normalizeFieldSetValue(parsed, value));
        },
        withLocal<Result>(...args: unknown[]): Result {
            const [target, use] = requireUnboundWithLocalArgs<Result, Value>(args);
            return withLocalValue(get(target), use);
        },
    };
}

export function createBoundStaticField<Value extends JniFieldValue = JniFieldValue>(
    clazz: jclass,
    name: string,
    sig: string,
): JniBoundStaticField<Value> {
    const parsed = parseFieldDescriptor(sig);
    const fieldId = lookupStaticFieldIdFor(clazz, name, sig);
    const getterName = getStaticFieldGetMethodName(sig);
    const setterName = getStaticFieldSetMethodName(sig);

    const get = (): Value => {
        const result = getEnvMethod(getterName)(clazz, fieldId) as JniFieldValue;
        return wrapTypedValue(result, parsed) as Value;
    };

    return {
        $id: fieldId,
        get(...args: unknown[]): Value {
            requireNoBoundArgs(args, "bound JNI static field accessor is already bound to a class; use get()");
            return get();
        },
        set(...args: unknown[]): void {
            const value = requireBoundValueArg<Value>(
                args,
                "bound JNI static field accessor is already bound to a class; use set(value)",
            );
            getEnvMethod(setterName)(clazz, fieldId, normalizeFieldSetValue(parsed, value));
        },
        withLocal<Result>(...args: unknown[]): Result {
            const use = requireBoundCallbackArg<Result, Value>(
                args,
                "bound JNI static field accessor is already bound to a class; use withLocal(use)",
            );
            return withLocalValue(get(), use);
        },
    };
}

export function createInstanceMethodAccessor<THostKind extends JniMemberHostKind, Ret extends JniMethodValue = JniMethodValue>(
    host: jobject<THostKind>,
    name: string,
    sig: string,
): JniInstanceMethodAccessorFor<THostKind, Ret> {
    // Keep runtime inheritance simple and route the public type split through one factory point instead.
    if (host instanceof jclass) {
        return createUnboundInstanceMethod<Ret>(host, name, sig) as JniInstanceMethodAccessorFor<THostKind, Ret>;
    }
    return createBoundInstanceMethod<Ret>(host, name, sig) as JniInstanceMethodAccessorFor<THostKind, Ret>;
}

export function createInstanceFieldAccessor<THostKind extends JniMemberHostKind, Value extends JniFieldValue = JniFieldValue>(
    host: jobject<THostKind>,
    name: string,
    sig: string,
): JniInstanceFieldAccessorFor<THostKind, Value> {
    // This mirrors `createInstanceMethodAccessor()` so `jclass extends jobject` can stay a runtime detail.
    if (host instanceof jclass) {
        return createUnboundInstanceField<Value>(host, name, sig) as JniInstanceFieldAccessorFor<THostKind, Value>;
    }
    return createBoundInstanceField<Value>(host, name, sig) as JniInstanceFieldAccessorFor<THostKind, Value>;
}

export function createConstructorAccessor<Ret extends jobject = jobject>(
    clazz: jclass,
    sig: string,
): JniConstructorAccessor<Ret> {
    const parsed = parseMethodDescriptor(sig);
    if (!parsed.returnType.isVoid) {
        throw new Error(`constructor signature must return void: ${sig}`);
    }
    const methodId = lookupConstructorIdFor(clazz, sig);

    const newInstance = (...args: JniCallArgument[]): Ret => JNIEnv.NewObject(clazz, methodId, ...args) as Ret;

    return {
        $id: methodId,
        newInstance,
        withLocal<Result>(use: (value: Ret) => Result, ...args: JniCallArgument[]): Result {
            return withLocalValue(newInstance(...args), use);
        },
    };
}

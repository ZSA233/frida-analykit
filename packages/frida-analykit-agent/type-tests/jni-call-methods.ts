import type {
    JniCallArgument,
    JniCallMethods,
    JniInstanceArrayMethod,
    JniInstanceVariadicMethod,
    JniNonvirtualVariadicMethod,
    JniStaticArrayMethod,
    JniStaticVariadicMethod,
} from "../src/capabilities/jni/call_methods.js";
import type { JniEnv } from "../src/capabilities/jni/env.js";
import type { jbyte, jclass, jdouble, jfloat, jlong, jmethodID, jobject, jvalue } from "../src/capabilities/jni/refs.js";

type Assert<T extends true> = T;

type IsEqual<A, B> =
    (<T>() => T extends A ? 1 : 2) extends
    (<T>() => T extends B ? 1 : 2)
        ? (<T>() => T extends B ? 1 : 2) extends
            (<T>() => T extends A ? 1 : 2)
            ? true
            : false
        : false;

type CallByteArgs = Parameters<Extract<JniEnv["CallByteMethod"], (...args: never[]) => unknown>>;
type CallFloatArgs = Parameters<Extract<JniEnv["CallFloatMethod"], (...args: never[]) => unknown>>;
type CallStaticObjectMethodAArgs = Parameters<Extract<JniEnv["CallStaticObjectMethodA"], (...args: never[]) => unknown>>;
type CallStaticDoubleArgs = Parameters<Extract<JniEnv["CallStaticDoubleMethod"], (...args: never[]) => unknown>>;
type CallNonvirtualLongArgs = Parameters<Extract<JniEnv["CallNonvirtualLongMethod"], (...args: never[]) => unknown>>;

type _callByteHoverSignature = Assert<IsEqual<
    CallByteArgs,
    [jobject<"instance" | "class"> | NativePointerValue, jmethodID | NativePointerValue, ...JniCallArgument[]]
>>;

type _callFloatHoverSignature = Assert<IsEqual<
    CallFloatArgs,
    [jobject<"instance" | "class"> | NativePointerValue, jmethodID | NativePointerValue, ...JniCallArgument[]]
>>;

type _callStaticObjectMethodAHoverSignature = Assert<IsEqual<
    CallStaticObjectMethodAArgs,
    [jclass | NativePointerValue, jmethodID | NativePointerValue, jvalue | NativePointerValue]
>>;

type _callStaticDoubleHoverSignature = Assert<IsEqual<
    CallStaticDoubleArgs,
    [jclass | NativePointerValue, jmethodID | NativePointerValue, ...JniCallArgument[]]
>>;

type _callNonvirtualLongHoverSignature = Assert<IsEqual<
    CallNonvirtualLongArgs,
    [jobject<"instance" | "class"> | NativePointerValue, jclass | NativePointerValue, jmethodID | NativePointerValue, ...JniCallArgument[]]
>>;

declare const methods: JniCallMethods;
declare const env: JniEnv;
declare const obj: jobject;
declare const clazz: jclass;
declare const methodId: jmethodID;
declare const jvalueArgs: jvalue;

const callByteMethod: JniInstanceVariadicMethod<jbyte> = methods.CallByteMethod;
const callFloatMethod: JniInstanceVariadicMethod<jfloat> = env.CallFloatMethod;
const callStaticObjectMethodA: JniStaticArrayMethod<jobject> = env.CallStaticObjectMethodA;
const callStaticDoubleMethod: JniStaticVariadicMethod<jdouble> = env.CallStaticDoubleMethod;
const callNonvirtualLongMethod: JniNonvirtualVariadicMethod<jlong> = env.CallNonvirtualLongMethod;

const byteResult: jbyte = callByteMethod(obj, methodId, 7);
const floatResult: jfloat = callFloatMethod(obj, methodId, 1.5);
const staticObjectResult: jobject = callStaticObjectMethodA(clazz, methodId, jvalueArgs);
const staticDoubleResult: jdouble = callStaticDoubleMethod(clazz, methodId, 2.5);
const nonvirtualLongResult: jlong = callNonvirtualLongMethod(obj, clazz, methodId, 1);

void byteResult;
void floatResult;
void staticObjectResult;
void staticDoubleResult;
void nonvirtualLongResult;

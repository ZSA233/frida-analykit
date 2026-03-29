import type { NativePointerObject } from "../helper.js";
import {
    callMethodVariadicArgTypes,
    callNonvirtualMethodVariadicArgTypes,
    JniEnvBase,
    proxyCallMethod,
    proxyCallNonvirtualMethod,
} from "./factory.js";
import {
    jboolean,
    jbyte,
    jchar,
    jdouble,
    jfloat,
    jint,
    jlong,
    jobject,
    jshort,
    jvoid,
} from "./refs.js";
import type { jclass, jmethodID, jvalue } from "./refs.js";
import { JNI_VT } from "./struct.js";

type JniPublicMethod<Fn extends (...args: any[]) => unknown> = Fn & {
    $handle: NativePointer | undefined;
};

export type JniCallArgument =
    | NativePointerObject
    | NativePointerValue
    | Int64
    | UInt64
    | number
    | boolean
    | null
    | undefined;

export type JniInstanceVariadicMethod<Ret> = JniPublicMethod<
    (
        obj: jobject<"instance" | "class"> | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        ...args: JniCallArgument[]
    ) => Ret
>;

export type JniInstanceVaListMethod<Ret> = JniPublicMethod<
    (
        obj: jobject<"instance" | "class"> | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        args: NativePointerValue,
    ) => Ret
>;

export type JniInstanceArrayMethod<Ret> = JniPublicMethod<
    (
        obj: jobject<"instance" | "class"> | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        args: jvalue | NativePointerValue,
    ) => Ret
>;

export type JniNonvirtualVariadicMethod<Ret> = JniPublicMethod<
    (
        obj: jobject<"instance" | "class"> | NativePointerValue,
        clazz: jclass | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        ...args: JniCallArgument[]
    ) => Ret
>;

export type JniNonvirtualVaListMethod<Ret> = JniPublicMethod<
    (
        obj: jobject<"instance" | "class"> | NativePointerValue,
        clazz: jclass | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        args: NativePointerValue,
    ) => Ret
>;

export type JniNonvirtualArrayMethod<Ret> = JniPublicMethod<
    (
        obj: jobject<"instance" | "class"> | NativePointerValue,
        clazz: jclass | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        args: jvalue | NativePointerValue,
    ) => Ret
>;

export type JniStaticVariadicMethod<Ret> = JniPublicMethod<
    (
        clazz: jclass | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        ...args: JniCallArgument[]
    ) => Ret
>;

export type JniStaticVaListMethod<Ret> = JniPublicMethod<
    (
        clazz: jclass | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        args: NativePointerValue,
    ) => Ret
>;

export type JniStaticArrayMethod<Ret> = JniPublicMethod<
    (
        clazz: jclass | NativePointerValue,
        methodId: jmethodID | NativePointerValue,
        args: jvalue | NativePointerValue,
    ) => Ret
>;

export interface JniCallMethods {
    /** jobject CallObjectMethod(jobject obj, jmethodID methodID, ...args) */
    CallObjectMethod: JniInstanceVariadicMethod<jobject>;
    /** jobject CallObjectMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallObjectMethodV: JniInstanceVaListMethod<jobject>;
    /** jobject CallObjectMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallObjectMethodA: JniInstanceArrayMethod<jobject>;

    /** jboolean CallBooleanMethod(jobject obj, jmethodID methodID, ...args) */
    CallBooleanMethod: JniInstanceVariadicMethod<jboolean>;
    /** jboolean CallBooleanMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallBooleanMethodV: JniInstanceVaListMethod<jboolean>;
    /** jboolean CallBooleanMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallBooleanMethodA: JniInstanceArrayMethod<jboolean>;

    /** jbyte CallByteMethod(jobject obj, jmethodID methodID, ...args) */
    CallByteMethod: JniInstanceVariadicMethod<jbyte>;
    /** jbyte CallByteMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallByteMethodV: JniInstanceVaListMethod<jbyte>;
    /** jbyte CallByteMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallByteMethodA: JniInstanceArrayMethod<jbyte>;

    /** jchar CallCharMethod(jobject obj, jmethodID methodID, ...args) */
    CallCharMethod: JniInstanceVariadicMethod<jchar>;
    /** jchar CallCharMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallCharMethodV: JniInstanceVaListMethod<jchar>;
    /** jchar CallCharMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallCharMethodA: JniInstanceArrayMethod<jchar>;

    /** jshort CallShortMethod(jobject obj, jmethodID methodID, ...args) */
    CallShortMethod: JniInstanceVariadicMethod<jshort>;
    /** jshort CallShortMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallShortMethodV: JniInstanceVaListMethod<jshort>;
    /** jshort CallShortMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallShortMethodA: JniInstanceArrayMethod<jshort>;

    /** jint CallIntMethod(jobject obj, jmethodID methodID, ...args) */
    CallIntMethod: JniInstanceVariadicMethod<jint>;
    /** jint CallIntMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallIntMethodV: JniInstanceVaListMethod<jint>;
    /** jint CallIntMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallIntMethodA: JniInstanceArrayMethod<jint>;

    /** jlong CallLongMethod(jobject obj, jmethodID methodID, ...args) */
    CallLongMethod: JniInstanceVariadicMethod<jlong>;
    /** jlong CallLongMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallLongMethodV: JniInstanceVaListMethod<jlong>;
    /** jlong CallLongMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallLongMethodA: JniInstanceArrayMethod<jlong>;

    /** jfloat CallFloatMethod(jobject obj, jmethodID methodID, ...args) */
    CallFloatMethod: JniInstanceVariadicMethod<jfloat>;
    /** jfloat CallFloatMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallFloatMethodV: JniInstanceVaListMethod<jfloat>;
    /** jfloat CallFloatMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallFloatMethodA: JniInstanceArrayMethod<jfloat>;

    /** jdouble CallDoubleMethod(jobject obj, jmethodID methodID, ...args) */
    CallDoubleMethod: JniInstanceVariadicMethod<jdouble>;
    /** jdouble CallDoubleMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallDoubleMethodV: JniInstanceVaListMethod<jdouble>;
    /** jdouble CallDoubleMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallDoubleMethodA: JniInstanceArrayMethod<jdouble>;

    /** void CallVoidMethod(jobject obj, jmethodID methodID, ...args) */
    CallVoidMethod: JniInstanceVariadicMethod<jvoid>;
    /** void CallVoidMethodV(jobject obj, jmethodID methodID, va_list args) */
    CallVoidMethodV: JniInstanceVaListMethod<jvoid>;
    /** void CallVoidMethodA(jobject obj, jmethodID methodID, jvalue* args) */
    CallVoidMethodA: JniInstanceArrayMethod<jvoid>;

    /** jobject CallNonvirtualObjectMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualObjectMethod: JniNonvirtualVariadicMethod<jobject>;
    /** jobject CallNonvirtualObjectMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualObjectMethodV: JniNonvirtualVaListMethod<jobject>;
    /** jobject CallNonvirtualObjectMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualObjectMethodA: JniNonvirtualArrayMethod<jobject>;

    /** jboolean CallNonvirtualBooleanMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualBooleanMethod: JniNonvirtualVariadicMethod<jboolean>;
    /** jboolean CallNonvirtualBooleanMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualBooleanMethodV: JniNonvirtualVaListMethod<jboolean>;
    /** jboolean CallNonvirtualBooleanMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualBooleanMethodA: JniNonvirtualArrayMethod<jboolean>;

    /** jbyte CallNonvirtualByteMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualByteMethod: JniNonvirtualVariadicMethod<jbyte>;
    /** jbyte CallNonvirtualByteMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualByteMethodV: JniNonvirtualVaListMethod<jbyte>;
    /** jbyte CallNonvirtualByteMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualByteMethodA: JniNonvirtualArrayMethod<jbyte>;

    /** jchar CallNonvirtualCharMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualCharMethod: JniNonvirtualVariadicMethod<jchar>;
    /** jchar CallNonvirtualCharMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualCharMethodV: JniNonvirtualVaListMethod<jchar>;
    /** jchar CallNonvirtualCharMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualCharMethodA: JniNonvirtualArrayMethod<jchar>;

    /** jshort CallNonvirtualShortMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualShortMethod: JniNonvirtualVariadicMethod<jshort>;
    /** jshort CallNonvirtualShortMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualShortMethodV: JniNonvirtualVaListMethod<jshort>;
    /** jshort CallNonvirtualShortMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualShortMethodA: JniNonvirtualArrayMethod<jshort>;

    /** jint CallNonvirtualIntMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualIntMethod: JniNonvirtualVariadicMethod<jint>;
    /** jint CallNonvirtualIntMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualIntMethodV: JniNonvirtualVaListMethod<jint>;
    /** jint CallNonvirtualIntMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualIntMethodA: JniNonvirtualArrayMethod<jint>;

    /** jlong CallNonvirtualLongMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualLongMethod: JniNonvirtualVariadicMethod<jlong>;
    /** jlong CallNonvirtualLongMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualLongMethodV: JniNonvirtualVaListMethod<jlong>;
    /** jlong CallNonvirtualLongMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualLongMethodA: JniNonvirtualArrayMethod<jlong>;

    /** jfloat CallNonvirtualFloatMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualFloatMethod: JniNonvirtualVariadicMethod<jfloat>;
    /** jfloat CallNonvirtualFloatMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualFloatMethodV: JniNonvirtualVaListMethod<jfloat>;
    /** jfloat CallNonvirtualFloatMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualFloatMethodA: JniNonvirtualArrayMethod<jfloat>;

    /** jdouble CallNonvirtualDoubleMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualDoubleMethod: JniNonvirtualVariadicMethod<jdouble>;
    /** jdouble CallNonvirtualDoubleMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualDoubleMethodV: JniNonvirtualVaListMethod<jdouble>;
    /** jdouble CallNonvirtualDoubleMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualDoubleMethodA: JniNonvirtualArrayMethod<jdouble>;

    /** void CallNonvirtualVoidMethod(jobject obj, jclass clazz, jmethodID methodID, ...args) */
    CallNonvirtualVoidMethod: JniNonvirtualVariadicMethod<jvoid>;
    /** void CallNonvirtualVoidMethodV(jobject obj, jclass clazz, jmethodID methodID, va_list args) */
    CallNonvirtualVoidMethodV: JniNonvirtualVaListMethod<jvoid>;
    /** void CallNonvirtualVoidMethodA(jobject obj, jclass clazz, jmethodID methodID, jvalue* args) */
    CallNonvirtualVoidMethodA: JniNonvirtualArrayMethod<jvoid>;

    /** jobject CallStaticObjectMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticObjectMethod: JniStaticVariadicMethod<jobject>;
    /** jobject CallStaticObjectMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticObjectMethodV: JniStaticVaListMethod<jobject>;
    /** jobject CallStaticObjectMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticObjectMethodA: JniStaticArrayMethod<jobject>;

    /** jboolean CallStaticBooleanMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticBooleanMethod: JniStaticVariadicMethod<jboolean>;
    /** jboolean CallStaticBooleanMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticBooleanMethodV: JniStaticVaListMethod<jboolean>;
    /** jboolean CallStaticBooleanMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticBooleanMethodA: JniStaticArrayMethod<jboolean>;

    /** jbyte CallStaticByteMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticByteMethod: JniStaticVariadicMethod<jbyte>;
    /** jbyte CallStaticByteMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticByteMethodV: JniStaticVaListMethod<jbyte>;
    /** jbyte CallStaticByteMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticByteMethodA: JniStaticArrayMethod<jbyte>;

    /** jchar CallStaticCharMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticCharMethod: JniStaticVariadicMethod<jchar>;
    /** jchar CallStaticCharMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticCharMethodV: JniStaticVaListMethod<jchar>;
    /** jchar CallStaticCharMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticCharMethodA: JniStaticArrayMethod<jchar>;

    /** jshort CallStaticShortMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticShortMethod: JniStaticVariadicMethod<jshort>;
    /** jshort CallStaticShortMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticShortMethodV: JniStaticVaListMethod<jshort>;
    /** jshort CallStaticShortMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticShortMethodA: JniStaticArrayMethod<jshort>;

    /** jint CallStaticIntMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticIntMethod: JniStaticVariadicMethod<jint>;
    /** jint CallStaticIntMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticIntMethodV: JniStaticVaListMethod<jint>;
    /** jint CallStaticIntMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticIntMethodA: JniStaticArrayMethod<jint>;

    /** jlong CallStaticLongMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticLongMethod: JniStaticVariadicMethod<jlong>;
    /** jlong CallStaticLongMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticLongMethodV: JniStaticVaListMethod<jlong>;
    /** jlong CallStaticLongMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticLongMethodA: JniStaticArrayMethod<jlong>;

    /** jfloat CallStaticFloatMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticFloatMethod: JniStaticVariadicMethod<jfloat>;
    /** jfloat CallStaticFloatMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticFloatMethodV: JniStaticVaListMethod<jfloat>;
    /** jfloat CallStaticFloatMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticFloatMethodA: JniStaticArrayMethod<jfloat>;

    /** jdouble CallStaticDoubleMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticDoubleMethod: JniStaticVariadicMethod<jdouble>;
    /** jdouble CallStaticDoubleMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticDoubleMethodV: JniStaticVaListMethod<jdouble>;
    /** jdouble CallStaticDoubleMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticDoubleMethodA: JniStaticArrayMethod<jdouble>;

    /** void CallStaticVoidMethod(jclass clazz, jmethodID methodID, ...args) */
    CallStaticVoidMethod: JniStaticVariadicMethod<jvoid>;
    /** void CallStaticVoidMethodV(jclass clazz, jmethodID methodID, va_list args) */
    CallStaticVoidMethodV: JniStaticVaListMethod<jvoid>;
    /** void CallStaticVoidMethodA(jclass clazz, jmethodID methodID, jvalue* args) */
    CallStaticVoidMethodA: JniStaticArrayMethod<jvoid>;
}

export function createCallMethods(base: JniEnvBase): JniCallMethods {
    const methods = {
        CallObjectMethod: proxyCallMethod(base, JNI_VT.CallObjectMethod, jobject, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallObjectMethodV: proxyCallMethod(base, JNI_VT.CallObjectMethodV, jobject),
        CallObjectMethodA: proxyCallMethod(base, JNI_VT.CallObjectMethodA, jobject),

        CallBooleanMethod: proxyCallMethod(base, JNI_VT.CallBooleanMethod, jboolean, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallBooleanMethodV: proxyCallMethod(base, JNI_VT.CallBooleanMethodV, jboolean),
        CallBooleanMethodA: proxyCallMethod(base, JNI_VT.CallBooleanMethodA, jboolean),

        CallByteMethod: proxyCallMethod(base, JNI_VT.CallByteMethod, jbyte, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallByteMethodV: proxyCallMethod(base, JNI_VT.CallByteMethodV, jbyte),
        CallByteMethodA: proxyCallMethod(base, JNI_VT.CallByteMethodA, jbyte),

        CallCharMethod: proxyCallMethod(base, JNI_VT.CallCharMethod, jchar, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallCharMethodV: proxyCallMethod(base, JNI_VT.CallCharMethodV, jchar),
        CallCharMethodA: proxyCallMethod(base, JNI_VT.CallCharMethodA, jchar),

        CallShortMethod: proxyCallMethod(base, JNI_VT.CallShortMethod, jshort, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallShortMethodV: proxyCallMethod(base, JNI_VT.CallShortMethodV, jshort),
        CallShortMethodA: proxyCallMethod(base, JNI_VT.CallShortMethodA, jshort),

        CallIntMethod: proxyCallMethod(base, JNI_VT.CallIntMethod, jint, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallIntMethodV: proxyCallMethod(base, JNI_VT.CallIntMethodV, jint),
        CallIntMethodA: proxyCallMethod(base, JNI_VT.CallIntMethodA, jint),

        CallLongMethod: proxyCallMethod<jlong>(base, JNI_VT.CallLongMethod, jlong, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallLongMethodV: proxyCallMethod<jlong>(base, JNI_VT.CallLongMethodV, jlong),
        CallLongMethodA: proxyCallMethod<jlong>(base, JNI_VT.CallLongMethodA, jlong),

        CallFloatMethod: proxyCallMethod(base, JNI_VT.CallFloatMethod, jfloat, {
            retType: "float",
            argTypes: callMethodVariadicArgTypes,
        }),
        CallFloatMethodV: proxyCallMethod(base, JNI_VT.CallFloatMethodV, jfloat, { retType: "float" }),
        CallFloatMethodA: proxyCallMethod(base, JNI_VT.CallFloatMethodA, jfloat, { retType: "float" }),

        CallDoubleMethod: proxyCallMethod(base, JNI_VT.CallDoubleMethod, jdouble, {
            retType: "double",
            argTypes: callMethodVariadicArgTypes,
        }),
        CallDoubleMethodV: proxyCallMethod(base, JNI_VT.CallDoubleMethodV, jdouble, { retType: "double" }),
        CallDoubleMethodA: proxyCallMethod(base, JNI_VT.CallDoubleMethodA, jdouble, { retType: "double" }),

        CallVoidMethod: proxyCallMethod(base, JNI_VT.CallVoidMethod, jvoid, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallVoidMethodV: proxyCallMethod(base, JNI_VT.CallVoidMethodV, jvoid),
        CallVoidMethodA: proxyCallMethod(base, JNI_VT.CallVoidMethodA, jvoid),

        CallNonvirtualObjectMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualObjectMethod, jobject, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualObjectMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualObjectMethodV, jobject),
        CallNonvirtualObjectMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualObjectMethodA, jobject),

        CallNonvirtualBooleanMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualBooleanMethod, jboolean, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualBooleanMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualBooleanMethodV, jboolean),
        CallNonvirtualBooleanMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualBooleanMethodA, jboolean),

        CallNonvirtualByteMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualByteMethod, jbyte, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualByteMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualByteMethodV, jbyte),
        CallNonvirtualByteMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualByteMethodA, jbyte),

        CallNonvirtualCharMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualCharMethod, jchar, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualCharMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualCharMethodV, jchar),
        CallNonvirtualCharMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualCharMethodA, jchar),

        CallNonvirtualShortMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualShortMethod, jshort, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualShortMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualShortMethodV, jshort),
        CallNonvirtualShortMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualShortMethodA, jshort),

        CallNonvirtualIntMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualIntMethod, jint, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualIntMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualIntMethodV, jint),
        CallNonvirtualIntMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualIntMethodA, jint),

        CallNonvirtualLongMethod: proxyCallNonvirtualMethod<jlong>(base, JNI_VT.CallNonvirtualLongMethod, jlong, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualLongMethodV: proxyCallNonvirtualMethod<jlong>(base, JNI_VT.CallNonvirtualLongMethodV, jlong),
        CallNonvirtualLongMethodA: proxyCallNonvirtualMethod<jlong>(base, JNI_VT.CallNonvirtualLongMethodA, jlong),

        CallNonvirtualFloatMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualFloatMethod, jfloat, {
            retType: "float",
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualFloatMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualFloatMethodV, jfloat, { retType: "float" }),
        CallNonvirtualFloatMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualFloatMethodA, jfloat, { retType: "float" }),

        CallNonvirtualDoubleMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualDoubleMethod, jdouble, {
            retType: "double",
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualDoubleMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualDoubleMethodV, jdouble, { retType: "double" }),
        CallNonvirtualDoubleMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualDoubleMethodA, jdouble, { retType: "double" }),

        CallNonvirtualVoidMethod: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualVoidMethod, jvoid, {
            argTypes: callNonvirtualMethodVariadicArgTypes,
        }),
        CallNonvirtualVoidMethodV: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualVoidMethodV, jvoid),
        CallNonvirtualVoidMethodA: proxyCallNonvirtualMethod(base, JNI_VT.CallNonvirtualVoidMethodA, jvoid),

        CallStaticObjectMethod: proxyCallMethod(base, JNI_VT.CallStaticObjectMethod, jobject, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticObjectMethodV: proxyCallMethod(base, JNI_VT.CallStaticObjectMethodV, jobject),
        CallStaticObjectMethodA: proxyCallMethod(base, JNI_VT.CallStaticObjectMethodA, jobject),

        CallStaticBooleanMethod: proxyCallMethod(base, JNI_VT.CallStaticBooleanMethod, jboolean, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticBooleanMethodV: proxyCallMethod(base, JNI_VT.CallStaticBooleanMethodV, jboolean),
        CallStaticBooleanMethodA: proxyCallMethod(base, JNI_VT.CallStaticBooleanMethodA, jboolean),

        CallStaticByteMethod: proxyCallMethod(base, JNI_VT.CallStaticByteMethod, jbyte, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticByteMethodV: proxyCallMethod(base, JNI_VT.CallStaticByteMethodV, jbyte),
        CallStaticByteMethodA: proxyCallMethod(base, JNI_VT.CallStaticByteMethodA, jbyte),

        CallStaticCharMethod: proxyCallMethod(base, JNI_VT.CallStaticCharMethod, jchar, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticCharMethodV: proxyCallMethod(base, JNI_VT.CallStaticCharMethodV, jchar),
        CallStaticCharMethodA: proxyCallMethod(base, JNI_VT.CallStaticCharMethodA, jchar),

        CallStaticShortMethod: proxyCallMethod(base, JNI_VT.CallStaticShortMethod, jshort, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticShortMethodV: proxyCallMethod(base, JNI_VT.CallStaticShortMethodV, jshort),
        CallStaticShortMethodA: proxyCallMethod(base, JNI_VT.CallStaticShortMethodA, jshort),

        CallStaticIntMethod: proxyCallMethod(base, JNI_VT.CallStaticIntMethod, jint, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticIntMethodV: proxyCallMethod(base, JNI_VT.CallStaticIntMethodV, jint),
        CallStaticIntMethodA: proxyCallMethod(base, JNI_VT.CallStaticIntMethodA, jint),

        CallStaticLongMethod: proxyCallMethod<jlong>(base, JNI_VT.CallStaticLongMethod, jlong, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticLongMethodV: proxyCallMethod<jlong>(base, JNI_VT.CallStaticLongMethodV, jlong),
        CallStaticLongMethodA: proxyCallMethod<jlong>(base, JNI_VT.CallStaticLongMethodA, jlong),

        CallStaticFloatMethod: proxyCallMethod(base, JNI_VT.CallStaticFloatMethod, jfloat, {
            retType: "float",
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticFloatMethodV: proxyCallMethod(base, JNI_VT.CallStaticFloatMethodV, jfloat, { retType: "float" }),
        CallStaticFloatMethodA: proxyCallMethod(base, JNI_VT.CallStaticFloatMethodA, jfloat, { retType: "float" }),

        CallStaticDoubleMethod: proxyCallMethod(base, JNI_VT.CallStaticDoubleMethod, jdouble, {
            retType: "double",
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticDoubleMethodV: proxyCallMethod(base, JNI_VT.CallStaticDoubleMethodV, jdouble, { retType: "double" }),
        CallStaticDoubleMethodA: proxyCallMethod(base, JNI_VT.CallStaticDoubleMethodA, jdouble, { retType: "double" }),

        CallStaticVoidMethod: proxyCallMethod(base, JNI_VT.CallStaticVoidMethod, jvoid, {
            argTypes: callMethodVariadicArgTypes,
        }),
        CallStaticVoidMethodV: proxyCallMethod(base, JNI_VT.CallStaticVoidMethodV, jvoid),
        CallStaticVoidMethodA: proxyCallMethod(base, JNI_VT.CallStaticVoidMethodA, jvoid),
    } satisfies JniCallMethods;

    return methods;
}

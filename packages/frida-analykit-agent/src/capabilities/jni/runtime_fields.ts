import { NativePointerObject } from "../../helper.js";
import { JniEnvBase } from "./factory.js";
import {
    jboolean,
    jbyte,
    jchar,
    jclass,
    jdouble,
    jfieldID,
    jfloat,
    jint,
    jlong,
    jobject,
    jshort,
    type JFieldIDTypeArg,
} from "./refs.js";
import { JNI_VT } from "./struct.js";

type JniPublicMethod<Fn extends (...args: any[]) => unknown> = Fn & {
    $handle: NativePointer | undefined;
};

export type JniClassReference = jclass | NativePointerValue;
export type JniObjectReference = jobject<"instance" | "class"> | NativePointerValue;
export type JniFieldIdReference = jfieldID | NativePointerValue;

export type JniPrimitiveFieldInput =
    | jboolean
    | jbyte
    | jchar
    | jshort
    | jint
    | jlong
    | jfloat
    | jdouble
    | boolean
    | number
    | Int64
    | UInt64;

export type JniObjectFieldInput = JniObjectReference | null | undefined;
export type JniFieldSetterValue<Value = unknown> = Value | JniPrimitiveFieldInput | JniObjectFieldInput;

export type JniClassMemberLookupMethod<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        name: string,
        sig: string,
    ) => Ret
>;

export type JniInstanceFieldMethod<Ret> = JniPublicMethod<
    (
        obj: JniObjectReference,
        fieldId: JniFieldIdReference,
    ) => Ret
>;

export type JniStaticFieldMethod<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        fieldId: JniFieldIdReference,
    ) => Ret
>;

export type JniInstanceFieldSetterMethod<Value> = JniPublicMethod<
    (
        obj: JniObjectReference,
        fieldId: JniFieldIdReference,
        value: Value,
    ) => void
>;

export type JniStaticFieldSetterMethod<Value> = JniPublicMethod<
    (
        clazz: JniClassReference,
        fieldId: JniFieldIdReference,
        value: Value,
    ) => void
>;

export interface JniRuntimeFieldMethods {
    /** jfieldID GetFieldID(jclass clazz, const char* name, const char* sig) */
    GetFieldID: JniClassMemberLookupMethod<jfieldID>;
    /** jfieldID GetStaticFieldID(jclass clazz, const char* name, const char* sig) */
    GetStaticFieldID: JniClassMemberLookupMethod<jfieldID>;

    /** jobject GetObjectField(jobject obj, jfieldID fieldID) */
    GetObjectField: JniInstanceFieldMethod<jobject>;
    /** jboolean GetBooleanField(jobject obj, jfieldID fieldID) */
    GetBooleanField: JniInstanceFieldMethod<jboolean>;
    /** jbyte GetByteField(jobject obj, jfieldID fieldID) */
    GetByteField: JniInstanceFieldMethod<jbyte>;
    /** jchar GetCharField(jobject obj, jfieldID fieldID) */
    GetCharField: JniInstanceFieldMethod<jchar>;
    /** jshort GetShortField(jobject obj, jfieldID fieldID) */
    GetShortField: JniInstanceFieldMethod<jshort>;
    /** jint GetIntField(jobject obj, jfieldID fieldID) */
    GetIntField: JniInstanceFieldMethod<jint>;
    /** jlong GetLongField(jobject obj, jfieldID fieldID) */
    GetLongField: JniInstanceFieldMethod<jlong>;
    /** jfloat GetFloatField(jobject obj, jfieldID fieldID) */
    GetFloatField: JniInstanceFieldMethod<jfloat>;
    /** jdouble GetDoubleField(jobject obj, jfieldID fieldID) */
    GetDoubleField: JniInstanceFieldMethod<jdouble>;

    /** void SetObjectField(jobject obj, jfieldID fieldID, jobject value) */
    SetObjectField: JniInstanceFieldSetterMethod<JniObjectFieldInput>;
    /** void SetBooleanField(jobject obj, jfieldID fieldID, jboolean value) */
    SetBooleanField: JniInstanceFieldSetterMethod<jboolean | boolean | number>;
    /** void SetByteField(jobject obj, jfieldID fieldID, jbyte value) */
    SetByteField: JniInstanceFieldSetterMethod<jbyte | number>;
    /** void SetCharField(jobject obj, jfieldID fieldID, jchar value) */
    SetCharField: JniInstanceFieldSetterMethod<jchar | number>;
    /** void SetShortField(jobject obj, jfieldID fieldID, jshort value) */
    SetShortField: JniInstanceFieldSetterMethod<jshort | number>;
    /** void SetIntField(jobject obj, jfieldID fieldID, jint value) */
    SetIntField: JniInstanceFieldSetterMethod<jint | number>;
    /** void SetLongField(jobject obj, jfieldID fieldID, jlong value) */
    SetLongField: JniInstanceFieldSetterMethod<jlong | number | Int64 | UInt64>;
    /** void SetFloatField(jobject obj, jfieldID fieldID, jfloat value) */
    SetFloatField: JniInstanceFieldSetterMethod<jfloat | number>;
    /** void SetDoubleField(jobject obj, jfieldID fieldID, jdouble value) */
    SetDoubleField: JniInstanceFieldSetterMethod<jdouble | number>;

    /** jobject GetStaticObjectField(jclass clazz, jfieldID fieldID) */
    GetStaticObjectField: JniStaticFieldMethod<jobject>;
    /** jboolean GetStaticBooleanField(jclass clazz, jfieldID fieldID) */
    GetStaticBooleanField: JniStaticFieldMethod<jboolean>;
    /** jbyte GetStaticByteField(jclass clazz, jfieldID fieldID) */
    GetStaticByteField: JniStaticFieldMethod<jbyte>;
    /** jchar GetStaticCharField(jclass clazz, jfieldID fieldID) */
    GetStaticCharField: JniStaticFieldMethod<jchar>;
    /** jshort GetStaticShortField(jclass clazz, jfieldID fieldID) */
    GetStaticShortField: JniStaticFieldMethod<jshort>;
    /** jint GetStaticIntField(jclass clazz, jfieldID fieldID) */
    GetStaticIntField: JniStaticFieldMethod<jint>;
    /** jlong GetStaticLongField(jclass clazz, jfieldID fieldID) */
    GetStaticLongField: JniStaticFieldMethod<jlong>;
    /** jfloat GetStaticFloatField(jclass clazz, jfieldID fieldID) */
    GetStaticFloatField: JniStaticFieldMethod<jfloat>;
    /** jdouble GetStaticDoubleField(jclass clazz, jfieldID fieldID) */
    GetStaticDoubleField: JniStaticFieldMethod<jdouble>;

    /** void SetStaticObjectField(jclass clazz, jfieldID fieldID, jobject value) */
    SetStaticObjectField: JniStaticFieldSetterMethod<JniObjectFieldInput>;
    /** void SetStaticBooleanField(jclass clazz, jfieldID fieldID, jboolean value) */
    SetStaticBooleanField: JniStaticFieldSetterMethod<jboolean | boolean | number>;
    /** void SetStaticByteField(jclass clazz, jfieldID fieldID, jbyte value) */
    SetStaticByteField: JniStaticFieldSetterMethod<jbyte | number>;
    /** void SetStaticCharField(jclass clazz, jfieldID fieldID, jchar value) */
    SetStaticCharField: JniStaticFieldSetterMethod<jchar | number>;
    /** void SetStaticShortField(jclass clazz, jfieldID fieldID, jshort value) */
    SetStaticShortField: JniStaticFieldSetterMethod<jshort | number>;
    /** void SetStaticIntField(jclass clazz, jfieldID fieldID, jint value) */
    SetStaticIntField: JniStaticFieldSetterMethod<jint | number>;
    /** void SetStaticLongField(jclass clazz, jfieldID fieldID, jlong value) */
    SetStaticLongField: JniStaticFieldSetterMethod<jlong | number | Int64 | UInt64>;
    /** void SetStaticFloatField(jclass clazz, jfieldID fieldID, jfloat value) */
    SetStaticFloatField: JniStaticFieldSetterMethod<jfloat | number>;
    /** void SetStaticDoubleField(jclass clazz, jfieldID fieldID, jdouble value) */
    SetStaticDoubleField: JniStaticFieldSetterMethod<jdouble | number>;
}

export function unwrapNativeHandle(value: NativePointerObject | NativePointerValue): NativePointer {
    if (value instanceof NativePointerObject) {
        return value.$handle;
    }
    if (value instanceof NativePointer) {
        return value;
    }
    return ptr(value as never);
}

function wrapFieldOwnerClass(clazz: JniClassReference, isStatic: boolean): jclass {
    const handle = unwrapNativeHandle(clazz);
    return new jclass(handle, { isStatic });
}

function buildFieldIdOptions(clazz: JniClassReference, isStatic: boolean): JFieldIDTypeArg {
    // jfieldID is an opaque token, but caching the declaring class/static bit keeps later facades context-aware.
    return {
        ownerClass: wrapFieldOwnerClass(clazz, isStatic),
        isStatic,
    };
}

export function createRuntimeFieldMethods(base: JniEnvBase): JniRuntimeFieldMethods {
    const methods = {
        GetFieldID: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer, name: string, sig: string): jfieldID {
                return impl(base.$env.handle, javaClass, Memory.allocUtf8String(name), Memory.allocUtf8String(sig));
            },
            "pointer",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.GetFieldID,
            jfieldID,
            clazz => buildFieldIdOptions(clazz as JniClassReference, false),
        ),
        GetStaticFieldID: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer, name: string, sig: string): jfieldID {
                return impl(base.$env.handle, javaClass, Memory.allocUtf8String(name), Memory.allocUtf8String(sig));
            },
            "pointer",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.GetStaticFieldID,
            jfieldID,
            clazz => buildFieldIdOptions(clazz as JniClassReference, true),
        ),
        GetObjectField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jobject {
                return impl(base.$env.handle, obj, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetObjectField,
            jobject,
        ),
        GetBooleanField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jboolean {
                return impl(base.$env.handle, obj, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetBooleanField,
            jboolean,
        ),
        GetByteField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jbyte {
                return impl(base.$env.handle, obj, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetByteField,
            jbyte,
        ),
        GetCharField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jchar {
                return impl(base.$env.handle, obj, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetCharField,
            jchar,
        ),
        GetShortField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jshort {
                return impl(base.$env.handle, obj, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetShortField,
            jshort,
        ),
        GetIntField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jint {
                return impl(base.$env.handle, obj, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetIntField,
            jint,
        ),
        GetLongField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jlong {
                return impl(base.$env.handle, obj, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetLongField,
            jlong,
        ),
        GetFloatField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jfloat {
                return impl(base.$env.handle, obj, fieldId);
            },
            "float",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetFloatField,
            jfloat,
        ),
        GetDoubleField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer): jdouble {
                return impl(base.$env.handle, obj, fieldId);
            },
            "double",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetDoubleField,
            jdouble,
        ),
        SetObjectField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: NativePointer): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.SetObjectField,
        ),
        SetBooleanField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetBooleanField,
        ),
        SetByteField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetByteField,
        ),
        SetCharField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetCharField,
        ),
        SetShortField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetShortField,
        ),
        SetIntField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetIntField,
        ),
        SetLongField: base.$proxy(
            function (
                impl: AnyFunction,
                obj: NativePointer,
                fieldId: NativePointer,
                value: number | Int64 | UInt64,
            ): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int64"],
            JNI_VT.SetLongField,
        ),
        SetFloatField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "float"],
            JNI_VT.SetFloatField,
        ),
        SetDoubleField: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, obj, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "double"],
            JNI_VT.SetDoubleField,
        ),

        GetStaticObjectField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jobject {
                return impl(base.$env.handle, cls, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticObjectField,
            jobject,
        ),
        GetStaticBooleanField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jboolean {
                return impl(base.$env.handle, cls, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticBooleanField,
            jboolean,
        ),
        GetStaticByteField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jbyte {
                return impl(base.$env.handle, cls, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticByteField,
            jbyte,
        ),
        GetStaticCharField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jchar {
                return impl(base.$env.handle, cls, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticCharField,
            jchar,
        ),
        GetStaticShortField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jshort {
                return impl(base.$env.handle, cls, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticShortField,
            jshort,
        ),
        GetStaticIntField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jint {
                return impl(base.$env.handle, cls, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticIntField,
            jint,
        ),
        GetStaticLongField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jlong {
                return impl(base.$env.handle, cls, fieldId);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticLongField,
            jlong,
        ),
        GetStaticFloatField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jfloat {
                return impl(base.$env.handle, cls, fieldId);
            },
            "float",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticFloatField,
            jfloat,
        ),
        GetStaticDoubleField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer): jdouble {
                return impl(base.$env.handle, cls, fieldId);
            },
            "double",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStaticDoubleField,
            jdouble,
        ),
        SetStaticObjectField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: NativePointer): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.SetStaticObjectField,
        ),
        SetStaticBooleanField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetStaticBooleanField,
        ),
        SetStaticByteField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetStaticByteField,
        ),
        SetStaticCharField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetStaticCharField,
        ),
        SetStaticShortField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetStaticShortField,
        ),
        SetStaticIntField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.SetStaticIntField,
        ),
        SetStaticLongField: base.$proxy(
            function (
                impl: AnyFunction,
                cls: NativePointer,
                fieldId: NativePointer,
                value: number | Int64 | UInt64,
            ): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "int64"],
            JNI_VT.SetStaticLongField,
        ),
        SetStaticFloatField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "float"],
            JNI_VT.SetStaticFloatField,
        ),
        SetStaticDoubleField: base.$proxy(
            function (impl: AnyFunction, cls: NativePointer, fieldId: NativePointer, value: number): void {
                impl(base.$env.handle, cls, fieldId, value);
            },
            "void",
            ["pointer", "pointer", "pointer", "double"],
            JNI_VT.SetStaticDoubleField,
        ),
    } satisfies JniRuntimeFieldMethods;

    return methods;
}

import { help } from "../../helper.js";
import type { JniCallArgument } from "./call_methods.js";
import {
    type ExtendedJavaEnv,
    getThreadFromEnv,
    JniEnvBase,
    type JniValueConstructor,
} from "./factory.js";
import {
    jboolean,
    jbooleanArray,
    jbooleanArrayElements,
    jbyte,
    jbyteArray,
    jbyteArrayElements,
    jchar,
    jcharArray,
    jcharArrayElements,
    jclass,
    jdouble,
    jdoubleArray,
    jdoubleArrayElements,
    jfloat,
    jfloatArray,
    jfloatArrayElements,
    jint,
    jintArray,
    jintArrayElements,
    jlong,
    jlongArray,
    jlongArrayElements,
    jmethodID,
    jobject,
    jobjectArray,
    jshort,
    jshortArray,
    jshortArrayElements,
    jthrowable,
    MirrorObject,
    type jvalue,
} from "./refs.js";
import {
    createRuntimeFieldMethods,
    type JniClassMemberLookupMethod,
    type JniClassReference,
    type JniObjectReference,
    type JniRuntimeFieldMethods,
    unwrapNativeHandle,
} from "./runtime_fields.js";
import { JNI_VT } from "./struct.js";
import type { jstring } from "./strings.js";

export type {
    JniClassMemberLookupMethod,
    JniClassReference,
    JniFieldIdReference,
    JniFieldSetterValue,
    JniInstanceFieldMethod,
    JniInstanceFieldSetterMethod,
    JniObjectFieldInput,
    JniObjectReference,
    JniPrimitiveFieldInput,
    JniRuntimeFieldMethods,
    JniStaticFieldMethod,
    JniStaticFieldSetterMethod,
} from "./runtime_fields.js";

const NativePointerCtor = NativePointer as unknown as JniValueConstructor<NativePointer>;

type JniPublicMethod<Fn extends (...args: any[]) => unknown> = Fn & {
    $handle: NativePointer | undefined;
};

export type JniMethodIdReference = jmethodID | NativePointerValue;
export type JniStringReference = jstring | NativePointerValue;
export type JniThrowableReference = jthrowable | NativePointerValue;
export type JniObjectArrayReference = jobjectArray | NativePointerValue;
export type JniPrimitiveArrayReference =
    | jbooleanArray
    | jbyteArray
    | jcharArray
    | jdoubleArray
    | jfloatArray
    | jintArray
    | jlongArray
    | jshortArray
    | NativePointerValue;
export type JniArrayReference = JniObjectArrayReference | JniPrimitiveArrayReference;
export type JniPrimitiveArrayElementsReference =
    | jbooleanArrayElements
    | jbyteArrayElements
    | jcharArrayElements
    | jdoubleArrayElements
    | jfloatArrayElements
    | jintArrayElements
    | jlongArrayElements
    | jshortArrayElements
    | NativePointerValue;
export type JniArtThreadReference = JniObjectReference | null | undefined;
export type JniSizeArgument = number | Int64 | UInt64 | NativePointerValue;

export type JniFindClassMethod<Ret> = JniPublicMethod<(name: string) => Ret>;

export type JniReflectedMethodLookup<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        methodId: JniMethodIdReference,
        isStatic: boolean,
    ) => Ret
>;

export type JniClassMethod<Ret> = JniPublicMethod<(clazz: JniClassReference) => Ret>;

export type JniObjectMethod<Ret> = JniPublicMethod<(obj: JniObjectReference) => Ret>;

export type JniNewObjectVariadicMethod<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        methodId: JniMethodIdReference,
        ...args: JniCallArgument[]
    ) => Ret
>;

export type JniNewObjectVaListMethod<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        methodId: JniMethodIdReference,
        args: NativePointerValue,
    ) => Ret
>;

export type JniNewObjectArrayMethod<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        methodId: JniMethodIdReference,
        args: jvalue | NativePointerValue,
    ) => Ret
>;

export type JniStringAcquireMethod = JniPublicMethod<(javaString: JniStringReference) => NativePointer>;
export type JniStringLengthMethod = JniPublicMethod<(javaString: JniStringReference) => jint>;
export type JniStringReleaseMethod = JniPublicMethod<
    (
        javaString: JniStringReference,
        chars: NativePointerValue,
    ) => void
>;
export type JniStringCriticalMethod = JniPublicMethod<(javaString: JniStringReference) => NativePointer>;

export type JniArrayLengthMethod = JniPublicMethod<(javaArray: JniArrayReference) => jint>;

export type JniObjectArrayElementMethod<Ret> = JniPublicMethod<
    (
        javaArray: JniObjectArrayReference,
        index: number,
    ) => Ret
>;

export type JniArrayElementsAcquireMethod<ArrayRef, Ret> = JniPublicMethod<
    (
        javaArray: ArrayRef | NativePointerValue,
    ) => Ret
>;

export type JniArrayElementsReleaseMethod<ArrayRef, Elements> = JniPublicMethod<
    (
        array: ArrayRef | NativePointerValue,
        elements: Elements | NativePointerValue,
        mode: number,
    ) => void
>;

export type JniObjectArrayElementsHelper = (javaArray: JniObjectArrayReference) => jobjectArray;

export type JniThrowableMethod<Ret> = JniPublicMethod<(javaException: JniThrowableReference) => Ret>;
export type JniThrowNewMethod<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        msg: string,
    ) => Ret
>;
export type JniNoArgMethod<Ret> = JniPublicMethod<() => Ret>;
export type JniMessageMethod<Ret> = JniPublicMethod<(msg: string) => Ret>;
export type JniCapacityMethod<Ret> = JniPublicMethod<(capacity: number) => Ret>;
export type JniIsSameObjectMethod = JniPublicMethod<
    (
        obj1: JniObjectReference,
        obj2: JniObjectReference,
    ) => boolean
>;

export type JniRegisterNativesMethod<Ret> = JniPublicMethod<
    (
        clazz: JniClassReference,
        methods: NativePointerValue,
        methodCount: number,
    ) => Ret
>;

export type JniDecodeGlobalMethod = JniPublicMethod<(obj: JniObjectReference) => MirrorObject>;
export type JniDecodeJObjectMethod = JniPublicMethod<
    (
        thread: JniArtThreadReference,
        obj: JniObjectReference,
    ) => MirrorObject
>;
export type JniAddGlobalRefMethod = JniPublicMethod<
    (
        thread: JniArtThreadReference,
        obj: JniObjectReference,
    ) => jobject
>;

export type JniIndirectReferenceTableNewMethod = JniPublicMethod<
    (
        self: NativePointerValue,
        maxCount: JniSizeArgument,
        desiredKind: NativePointerValue,
        resizable: NativePointerValue,
        errorMsg: NativePointerValue,
    ) => NativePointer
>;

export type JniIndirectReferenceTableDeleteMethod = JniPublicMethod<(self: NativePointerValue) => void>;

export type JniIndirectReferenceTableResizeMethod = JniPublicMethod<
    (
        newSize: JniSizeArgument,
        errorMsg: NativePointerValue,
    ) => boolean
>;

export interface JniRuntimeMethods extends JniRuntimeFieldMethods {
    /** jclass FindClass(const char* name) */
    FindClass: JniFindClassMethod<jclass>;
    /** jobject ToReflectedMethod(jclass clazz, jmethodID methodID, jboolean isStatic) */
    ToReflectedMethod: JniReflectedMethodLookup<jobject>;
    /** jclass GetSuperclass(jclass clazz) */
    GetSuperclass: JniClassMethod<jclass>;
    /** jobject NewObject(jclass clazz, jmethodID methodID, ...args) */
    NewObject: JniNewObjectVariadicMethod<jobject>;
    /** jobject NewObjectV(jclass clazz, jmethodID methodID, va_list args) */
    NewObjectV: JniNewObjectVaListMethod<jobject>;
    /** jobject NewObjectA(jclass clazz, jmethodID methodID, jvalue* args) */
    NewObjectA: JniNewObjectArrayMethod<jobject>;
    /** jclass GetObjectClass(jobject obj) */
    GetObjectClass: JniObjectMethod<jclass>;
    /** jmethodID GetMethodID(jclass clazz, const char* name, const char* sig) */
    GetMethodID: JniClassMemberLookupMethod<jmethodID>;
    /** jmethodID GetStaticMethodID(jclass clazz, const char* name, const char* sig) */
    GetStaticMethodID: JniClassMemberLookupMethod<jmethodID>;

    /** const jchar* GetStringChars(jstring str, jboolean* isCopy) */
    GetStringChars: JniStringAcquireMethod;
    /** jsize GetStringLength(jstring str) */
    GetStringLength: JniStringLengthMethod;
    /** void ReleaseStringChars(jstring str, const jchar* chars) */
    ReleaseStringChars: JniStringReleaseMethod;
    /** const char* GetStringUTFChars(jstring str, jboolean* isCopy) */
    GetStringUTFChars: JniStringAcquireMethod;
    /** jsize GetStringUTFLength(jstring str) */
    GetStringUTFLength: JniStringLengthMethod;
    /** void ReleaseStringUTFChars(jstring str, const char* chars) */
    ReleaseStringUTFChars: JniStringReleaseMethod;

    /** jsize GetArrayLength(jarray array) */
    GetArrayLength: JniArrayLengthMethod;
    /** jobject GetObjectArrayElement(jobjectArray array, jsize index) */
    GetObjectArrayElement: JniObjectArrayElementMethod<jobject>;
    /** Helper: wrap jobjectArray ref for indexed element access */
    makeObjectArrayElements: JniObjectArrayElementsHelper;
    /** jboolean* GetBooleanArrayElements(jbooleanArray array, jboolean* isCopy) */
    GetBooleanArrayElements: JniArrayElementsAcquireMethod<jbooleanArray, jbooleanArrayElements>;
    /** jbyte* GetByteArrayElements(jbyteArray array, jboolean* isCopy) */
    GetByteArrayElements: JniArrayElementsAcquireMethod<jbyteArray, jbyteArrayElements>;
    /** jchar* GetCharArrayElements(jcharArray array, jboolean* isCopy) */
    GetCharArrayElements: JniArrayElementsAcquireMethod<jcharArray, jcharArrayElements>;
    /** jdouble* GetDoubleArrayElements(jdoubleArray array, jboolean* isCopy) */
    GetDoubleArrayElements: JniArrayElementsAcquireMethod<jdoubleArray, jdoubleArrayElements>;
    /** jfloat* GetFloatArrayElements(jfloatArray array, jboolean* isCopy) */
    GetFloatArrayElements: JniArrayElementsAcquireMethod<jfloatArray, jfloatArrayElements>;
    /** jint* GetIntArrayElements(jintArray array, jboolean* isCopy) */
    GetIntArrayElements: JniArrayElementsAcquireMethod<jintArray, jintArrayElements>;
    /** jlong* GetLongArrayElements(jlongArray array, jboolean* isCopy) */
    GetLongArrayElements: JniArrayElementsAcquireMethod<jlongArray, jlongArrayElements>;
    /** jshort* GetShortArrayElements(jshortArray array, jboolean* isCopy) */
    GetShortArrayElements: JniArrayElementsAcquireMethod<jshortArray, jshortArrayElements>;

    /** void ReleaseBooleanArrayElements(jbooleanArray array, jboolean* elems, jint mode) */
    ReleaseBooleanArrayElements: JniArrayElementsReleaseMethod<jbooleanArray, jbooleanArrayElements>;
    /** void ReleaseByteArrayElements(jbyteArray array, jbyte* elems, jint mode) */
    ReleaseByteArrayElements: JniArrayElementsReleaseMethod<jbyteArray, jbyteArrayElements>;
    /** void ReleaseCharArrayElements(jcharArray array, jchar* elems, jint mode) */
    ReleaseCharArrayElements: JniArrayElementsReleaseMethod<jcharArray, jcharArrayElements>;
    /** void ReleaseFloatArrayElements(jfloatArray array, jfloat* elems, jint mode) */
    ReleaseFloatArrayElements: JniArrayElementsReleaseMethod<jfloatArray, jfloatArrayElements>;
    /** void ReleaseDoubleArrayElements(jdoubleArray array, jdouble* elems, jint mode) */
    ReleaseDoubleArrayElements: JniArrayElementsReleaseMethod<jdoubleArray, jdoubleArrayElements>;
    /** void ReleaseIntArrayElements(jintArray array, jint* elems, jint mode) */
    ReleaseIntArrayElements: JniArrayElementsReleaseMethod<jintArray, jintArrayElements>;
    /** void ReleaseLongArrayElements(jlongArray array, jlong* elems, jint mode) */
    ReleaseLongArrayElements: JniArrayElementsReleaseMethod<jlongArray, jlongArrayElements>;
    /** void ReleaseShortArrayElements(jshortArray array, jshort* elems, jint mode) */
    ReleaseShortArrayElements: JniArrayElementsReleaseMethod<jshortArray, jshortArrayElements>;

    /** const jchar* GetStringCritical(jstring str, jboolean* isCopy) */
    GetStringCritical: JniStringCriticalMethod;
    /** void ReleaseStringCritical(jstring str, const jchar* chars) */
    ReleaseStringCritical: JniStringReleaseMethod;
    /** jint Throw(jthrowable exception) */
    Throw: JniThrowableMethod<jint>;
    /** jint ThrowNew(jclass clazz, const char* msg) */
    ThrowNew: JniThrowNewMethod<jint>;
    /** jthrowable ExceptionOccurred() */
    ExceptionOccurred: JniNoArgMethod<jthrowable>;
    /** void ExceptionDescribe() */
    ExceptionDescribe: JniNoArgMethod<void>;
    /** void ExceptionClear() */
    ExceptionClear: JniNoArgMethod<void>;
    /** jboolean ExceptionCheck() */
    ExceptionCheck: JniNoArgMethod<boolean>;
    /** void FatalError(const char* msg) */
    FatalError: JniMessageMethod<void>;

    /** jint PushLocalFrame(jint capacity) */
    PushLocalFrame: JniCapacityMethod<jint>;
    /** jobject PopLocalFrame(jobject result) */
    PopLocalFrame: JniPublicMethod<(javaSurvivor: JniObjectReference) => jobject>;

    /** jobject NewGlobalRef(jobject obj) */
    NewGlobalRef: JniObjectMethod<jobject>;
    /** jboolean IsSameObject(jobject obj1, jobject obj2) */
    IsSameObject: JniIsSameObjectMethod;
    /** jobject NewLocalRef(jobject obj) */
    NewLocalRef: JniObjectMethod<jobject>;
    /** void DeleteGlobalRef(jobject globalRef) */
    DeleteGlobalRef: JniPublicMethod<(obj: JniObjectReference) => void>;
    /** void DeleteLocalRef(jobject localRef) */
    DeleteLocalRef: JniPublicMethod<(obj: JniObjectReference) => void>;
    /** void DeleteWeakGlobalRef(jweak weakRef) */
    DeleteWeakGlobalRef: JniPublicMethod<(obj: JniObjectReference) => void>;
    /** jint RegisterNatives(jclass clazz, JNINativeMethod* methods, jint count) */
    RegisterNatives: JniRegisterNativesMethod<jint>;
    /** jint UnregisterNatives(jclass clazz) */
    UnregisterNatives: JniClassMethod<jint>;

    /** mirror::Object* DecodeGlobal(jobject ref) */
    DecodeGlobal: JniDecodeGlobalMethod;
    /** mirror::Object* DecodeJObject(Thread* thread, jobject obj) */
    DecodeJObject: JniDecodeJObjectMethod;
    /** jobject AddGlobalRef(Thread* thread, jobject obj) */
    AddGlobalRef: JniAddGlobalRefMethod;
    /** void* IndirectReferenceTable::IndirectReferenceTable(...) */
    IndirectReferenceTable_$new: JniIndirectReferenceTableNewMethod;
    /** void IndirectReferenceTable::~IndirectReferenceTable() */
    IndirectReferenceTable_$del: JniIndirectReferenceTableDeleteMethod;
    /** bool IndirectReferenceTable::Resize(size_t newSize, std::string* errorMsg) */
    IndirectReferenceTable_Resize: JniIndirectReferenceTableResizeMethod;
}

export function createRuntimeMethods(base: JniEnvBase): JniRuntimeMethods {
    const methods = {
        ...createRuntimeFieldMethods(base),
        FindClass: base.$proxy(
            function (impl: AnyFunction, name: string): jclass {
                const result = impl(base.$env.handle, Memory.allocUtf8String(name));
                base.$env.throwIfExceptionPending();
                return result;
            },
            "pointer",
            ["pointer", "pointer"],
            JNI_VT.FindClass,
            jclass,
        ),
        ToReflectedMethod: base.$proxy(
            function (impl: AnyFunction, klass: NativePointer, methodId: NativePointer, isStatic: boolean): jobject {
                return impl(base.$env.handle, klass, methodId, isStatic ? 1 : 0);
            },
            "pointer",
            ["pointer", "pointer", "pointer", "uint8"],
            JNI_VT.ToReflectedMethod,
            jobject,
            (_klass, _methodId, isStatic) => ({ isStatic }),
        ),
        GetSuperclass: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer): jclass {
                return impl(base.$env.handle, javaClass);
            },
            "pointer",
            ["pointer", "pointer"],
            JNI_VT.GetSuperclass,
            jclass,
        ),
        NewObject: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer, methodId: NativePointer, ...args: unknown[]): jobject {
                return impl(base.$env.handle, javaClass, methodId, ...args);
            },
            "pointer",
            ["pointer", "pointer", "pointer", "..."],
            JNI_VT.NewObject,
            jobject,
        ),
        NewObjectV: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer, methodId: NativePointer, args: NativePointer): jobject {
                return impl(base.$env.handle, javaClass, methodId, args);
            },
            "pointer",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.NewObjectV,
            jobject,
        ),
        NewObjectA: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer, methodId: NativePointer, args: NativePointer): jobject {
                return impl(base.$env.handle, javaClass, methodId, args);
            },
            "pointer",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.NewObjectA,
            jobject,
        ),
        GetObjectClass: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer): jclass {
                return impl(base.$env.handle, obj);
            },
            "pointer",
            ["pointer", "pointer"],
            JNI_VT.GetObjectClass,
            jclass,
        ),
        GetMethodID: base.$proxy(
            function (impl: AnyFunction, klass: NativePointer, name: string, sig: string): jmethodID {
                return impl(base.$env.handle, klass, Memory.allocUtf8String(name), Memory.allocUtf8String(sig));
            },
            "pointer",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.GetMethodID,
            jmethodID,
        ),
        GetStaticMethodID: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer, name: string, sig: string): jmethodID {
                return impl(base.$env.handle, javaClass, Memory.allocUtf8String(name), Memory.allocUtf8String(sig));
            },
            "pointer",
            ["pointer", "pointer", "pointer", "pointer"],
            JNI_VT.GetStaticMethodID,
            jmethodID,
        ),

        GetStringChars: base.$proxy(
            function (impl: AnyFunction, str: NativePointer): NativePointer {
                return impl(base.$env.handle, str, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStringChars,
            NativePointerCtor,
        ),
        GetStringLength: base.$proxy(
            function (impl: AnyFunction, javaString: NativePointer): jint {
                return impl(base.$env.handle, javaString);
            },
            "int",
            ["pointer", "pointer"],
            JNI_VT.GetStringLength,
            jint,
        ),
        ReleaseStringChars: base.$proxy(
            function (impl: AnyFunction, javaString: NativePointer, chars: NativePointer): void {
                impl(base.$env.handle, javaString, chars);
            },
            "void",
            ["pointer", "pointer", "pointer"],
            JNI_VT.ReleaseStringChars,
        ),
        GetStringUTFChars: base.$proxy(
            function (impl: AnyFunction, str: NativePointer): NativePointer {
                return impl(base.$env.handle, str, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStringUTFChars,
            NativePointerCtor,
        ),
        GetStringUTFLength: base.$proxy(
            function (impl: AnyFunction, javaString: NativePointer): jint {
                return impl(base.$env.handle, javaString);
            },
            "int",
            ["pointer", "pointer"],
            JNI_VT.GetStringUTFLength,
            jint,
        ),
        ReleaseStringUTFChars: base.$proxy(
            function (impl: AnyFunction, javaString: NativePointer, chars: NativePointer): void {
                impl(base.$env.handle, javaString, chars);
            },
            "void",
            ["pointer", "pointer", "pointer"],
            JNI_VT.ReleaseStringUTFChars,
        ),

        GetArrayLength: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jint {
                return impl(base.$env.handle, javaArray);
            },
            "int",
            ["pointer", "pointer"],
            JNI_VT.GetArrayLength,
            jint,
        ),
        GetObjectArrayElement: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer, index: number): jobject {
                return impl(base.$env.handle, javaArray, index);
            },
            "pointer",
            ["pointer", "pointer", "int"],
            JNI_VT.GetObjectArrayElement,
            jobject,
        ),

        makeObjectArrayElements(javaArray: JniObjectArrayReference): jobjectArray {
            return new jobjectArray(unwrapNativeHandle(javaArray));
        },

        GetBooleanArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jbooleanArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetBooleanArrayElements,
            jbooleanArrayElements,
        ),
        GetByteArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jbyteArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetByteArrayElements,
            jbyteArrayElements,
        ),
        GetCharArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jcharArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetCharArrayElements,
            jcharArrayElements,
        ),
        GetDoubleArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jdoubleArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetDoubleArrayElements,
            jdoubleArrayElements,
        ),
        GetFloatArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jfloatArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetFloatArrayElements,
            jfloatArrayElements,
        ),
        GetIntArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jintArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetIntArrayElements,
            jintArrayElements,
        ),
        GetLongArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jlongArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetLongArrayElements,
            jlongArrayElements,
        ),
        GetShortArrayElements: base.$proxy(
            function (impl: AnyFunction, javaArray: NativePointer): jshortArrayElements {
                return impl(base.$env.handle, javaArray, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetShortArrayElements,
            jshortArrayElements,
        ),

        ReleaseBooleanArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseBooleanArrayElements,
        ),
        ReleaseByteArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseByteArrayElements,
        ),
        ReleaseCharArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseCharArrayElements,
        ),
        ReleaseFloatArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseFloatArrayElements,
        ),
        ReleaseDoubleArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseDoubleArrayElements,
        ),
        ReleaseIntArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseIntArrayElements,
        ),
        ReleaseLongArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseLongArrayElements,
        ),
        ReleaseShortArrayElements: base.$proxy(
            function (impl: AnyFunction, array: NativePointer, elements: NativePointer, mode: number): void {
                impl(base.$env.handle, array, elements, mode);
            },
            "void",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.ReleaseShortArrayElements,
        ),

        GetStringCritical: base.$proxy(
            // GetStringCritical may pin the backing string, so callers must release it promptly.
            function (impl: AnyFunction, str: NativePointer): NativePointer {
                return impl(base.$env.handle, str, NULL);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.GetStringCritical,
            NativePointerCtor,
        ),
        ReleaseStringCritical: base.$proxy(
            function (impl: AnyFunction, javaString: NativePointer, chars: NativePointer): void {
                impl(base.$env.handle, javaString, chars);
            },
            "void",
            ["pointer", "pointer", "pointer"],
            JNI_VT.ReleaseStringCritical,
        ),
        Throw: base.$proxy(
            function (impl: AnyFunction, javaException: NativePointer): jint {
                return impl(base.$env.handle, javaException);
            },
            "int",
            ["pointer", "pointer"],
            JNI_VT.Throw,
            jint,
        ),
        ThrowNew: base.$proxy(
            function (impl: AnyFunction, klass: NativePointer, msg: string): jint {
                help.$error(`[ThrowNew]c[${klass}], msg[${msg}]`);
                return impl(base.$env.handle, klass, Memory.allocUtf8String(msg));
            },
            "int",
            ["pointer", "pointer", "pointer"],
            JNI_VT.ThrowNew,
            jint,
        ),
        ExceptionOccurred: base.$proxy(
            function (impl: AnyFunction): jthrowable {
                return impl(base.$env.handle);
            },
            "pointer",
            ["pointer"],
            JNI_VT.ExceptionOccurred,
            jthrowable,
        ),
        ExceptionDescribe: base.$proxy(
            function (impl: AnyFunction): void {
                impl(base.$env.handle);
            },
            "void",
            ["pointer"],
            JNI_VT.ExceptionDescribe,
        ),
        ExceptionClear: base.$proxy(
            function (impl: AnyFunction): void {
                impl(base.$env.handle);
            },
            "void",
            ["pointer"],
            JNI_VT.ExceptionClear,
        ),
        ExceptionCheck: base.$proxy(
            function (impl: AnyFunction): boolean {
                return impl(base.$env.handle).toUInt32() !== 0;
            },
            "pointer",
            ["pointer"],
            JNI_VT.ExceptionCheck,
        ),
        FatalError: base.$proxy(
            function (impl: AnyFunction, msg: string): void {
                impl(base.$env.handle, Memory.allocUtf8String(msg));
            },
            "void",
            ["pointer", "pointer"],
            JNI_VT.FatalError,
        ),

        PushLocalFrame: base.$proxy(
            function (impl: AnyFunction, capacity: number): jint {
                return impl(base.$env.handle, capacity);
            },
            "int",
            ["pointer", "int"],
            JNI_VT.PushLocalFrame,
            jint,
        ),
        PopLocalFrame: base.$proxy(
            function (impl: AnyFunction, javaSurvivor: NativePointer): jobject {
                return impl(base.$env.handle, javaSurvivor);
            },
            "pointer",
            ["pointer", "pointer"],
            JNI_VT.PopLocalFrame,
            jobject,
        ),

        NewGlobalRef: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer): jobject {
                return impl(base.$env.handle, obj);
            },
            "pointer",
            ["pointer", "pointer"],
            JNI_VT.NewGlobalRef,
            jobject,
        ),
        IsSameObject: base.$proxy(
            function (impl: AnyFunction, obj1: NativePointer, obj2: NativePointer): boolean {
                return impl(base.$env.handle, obj1, obj2) !== 0;
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            JNI_VT.IsSameObject,
        ),
        NewLocalRef: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer): jobject {
                return impl(base.$env.handle, obj);
            },
            "pointer",
            ["pointer", "pointer"],
            JNI_VT.NewLocalRef,
            jobject,
        ),

        DeleteGlobalRef: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer): void {
                impl(base.$env.handle, obj);
            },
            "void",
            ["pointer", "pointer"],
            JNI_VT.DeleteGlobalRef,
        ),
        DeleteLocalRef: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer): void {
                impl(base.$env.handle, obj);
            },
            "void",
            ["pointer", "pointer"],
            JNI_VT.DeleteLocalRef,
        ),
        DeleteWeakGlobalRef: base.$proxy(
            function (impl: AnyFunction, obj: NativePointer): void {
                impl(base.$env.handle, obj);
            },
            "void",
            ["pointer", "pointer"],
            JNI_VT.DeleteWeakGlobalRef,
        ),
        RegisterNatives: base.$proxy(
            function (
                impl: AnyFunction,
                javaClass: NativePointer,
                methods: NativePointer,
                methodCount: number,
            ): jint {
                return impl(base.$env.handle, javaClass, methods, methodCount);
            },
            "int",
            ["pointer", "pointer", "pointer", "int"],
            JNI_VT.RegisterNatives,
            jint,
        ),
        UnregisterNatives: base.$proxy(
            function (impl: AnyFunction, javaClass: NativePointer): jint {
                return impl(base.$env.handle, javaClass);
            },
            "int",
            ["pointer", "pointer"],
            JNI_VT.UnregisterNatives,
            jint,
        ),

        DecodeGlobal: base.$symbol(
            function (this: ExtendedJavaEnv, impl: AnyFunction, obj: NativePointer): MirrorObject {
                return impl(base.$env.vm.handle, obj);
            },
            "pointer",
            ["pointer", "pointer"],
            "_ZN3art9JavaVMExt12DecodeGlobalEPv",
            MirrorObject,
        ),
        DecodeJObject: base.$symbol(
            function (
                this: ExtendedJavaEnv,
                impl: AnyFunction,
                thread: NativePointer | null = null,
                obj: NativePointer,
            ): MirrorObject {
                return impl(thread ?? getThreadFromEnv(this), obj);
            },
            "pointer",
            ["pointer", "pointer"],
            "_ZNK3art6Thread13DecodeJObjectEP8_jobject",
            MirrorObject,
        ),
        AddGlobalRef: base.$symbol(
            function (
                this: ExtendedJavaEnv,
                impl: AnyFunction,
                thread: NativePointer | null = null,
                obj: NativePointer,
            ): jobject {
                return impl(base.$env.vm.handle, thread ?? getThreadFromEnv(base.$env), obj);
            },
            "pointer",
            ["pointer", "pointer", "pointer"],
            "_ZN3art9JavaVMExt12AddGlobalRefEPNS_6ThreadENS_6ObjPtrINS_6mirror6ObjectEEE",
            jobject,
        ),
        IndirectReferenceTable_$new: base.$symbol(
            function (
                impl: AnyFunction,
                self: NativePointer,
                maxCount: NativePointer,
                desiredKind: NativePointer,
                resizable: NativePointer,
                errorMsg: NativePointer,
            ): NativePointer {
                return impl(self, maxCount, desiredKind, resizable, errorMsg);
            },
            "pointer",
            ["pointer", "size_t", "pointer", "pointer", "pointer"],
            "_ZN3art22IndirectReferenceTableC2EmNS_15IndirectRefKindENS0_17ResizableCapacityEPNSt3__112basic_stringIcNS3_11char_traitsIcEENS3_9allocatorIcEEEE",
            NativePointerCtor,
        ),
        IndirectReferenceTable_$del: base.$symbol(
            function (impl: AnyFunction, self: NativePointer): void {
                impl(self);
            },
            "void",
            ["pointer"],
            "_ZN3art22IndirectReferenceTableD2Ev",
        ),
        IndirectReferenceTable_Resize: base.$symbol(
            function (impl: AnyFunction, newSize: NativePointer, errorMsg: NativePointer): boolean {
                return impl(newSize, errorMsg);
            },
            "bool",
            ["size_t", "pointer"],
            "_ZN3art22IndirectReferenceTable6ResizeEmPNSt3__112basic_stringIcNS1_11char_traitsIcEENS1_9allocatorIcEEEE",
        ),
    } satisfies JniRuntimeMethods;

    return methods;
}

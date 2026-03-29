import type { JniCallArgument } from "../src/jni/call_methods.js";
import type { JniEnv } from "../src/jni/env.js";
import type {
    JniClassMemberLookupMethod,
    JniDecodeJObjectMethod,
    JniInstanceFieldMethod,
    JniObjectReference,
    JniRuntimeMethods,
    JniStringReleaseMethod,
} from "../src/jni/runtime_methods.js";
import type {
    jclass,
    jfieldID,
    jint,
    jintArray,
    jintArrayElements,
    jmethodID,
    jobject,
    MirrorObject,
} from "../src/jni/refs.js";
import type { jstring } from "../src/jni/strings.js";

type Assert<T extends true> = T;

type IsEqual<A, B> =
    (<T>() => T extends A ? 1 : 2) extends
    (<T>() => T extends B ? 1 : 2)
        ? (<T>() => T extends B ? 1 : 2) extends
            (<T>() => T extends A ? 1 : 2)
            ? true
            : false
        : false;

type GetFieldIDArgs = Parameters<Extract<JniEnv["GetFieldID"], (...args: never[]) => unknown>>;
type GetStaticFieldIDArgs = Parameters<Extract<JniEnv["GetStaticFieldID"], (...args: never[]) => unknown>>;
type GetIntFieldArgs = Parameters<Extract<JniEnv["GetIntField"], (...args: never[]) => unknown>>;
type GetIntArrayElementsArgs = Parameters<Extract<JniEnv["GetIntArrayElements"], (...args: never[]) => unknown>>;
type NewObjectArgs = Parameters<Extract<JniEnv["NewObject"], (...args: never[]) => unknown>>;
type GetStringCriticalArgs = Parameters<Extract<JniEnv["GetStringCritical"], (...args: never[]) => unknown>>;
type ReleaseStringCriticalArgs = Parameters<Extract<JniEnv["ReleaseStringCritical"], (...args: never[]) => unknown>>;
type ReleaseStringUTFCharsArgs = Parameters<Extract<JniEnv["ReleaseStringUTFChars"], (...args: never[]) => unknown>>;
type DecodeJObjectArgs = Parameters<Extract<JniEnv["DecodeJObject"], (...args: never[]) => unknown>>;

type _getFieldIDHoverSignature = Assert<IsEqual<
    GetFieldIDArgs,
    [jclass | NativePointerValue, string, string]
>>;

type _getStaticFieldIDHoverSignature = Assert<IsEqual<
    GetStaticFieldIDArgs,
    [jclass | NativePointerValue, string, string]
>>;

type _getIntFieldHoverSignature = Assert<IsEqual<
    GetIntFieldArgs,
    [JniObjectReference, jfieldID | NativePointerValue]
>>;

type _getIntArrayElementsHoverSignature = Assert<IsEqual<
    GetIntArrayElementsArgs,
    [jintArray | NativePointerValue]
>>;

type _newObjectHoverSignature = Assert<IsEqual<
    NewObjectArgs,
    [jclass | NativePointerValue, jmethodID | NativePointerValue, ...JniCallArgument[]]
>>;

type _getStringCriticalHoverSignature = Assert<IsEqual<
    GetStringCriticalArgs,
    [jstring | NativePointerValue]
>>;

type _releaseStringCriticalHoverSignature = Assert<IsEqual<
    ReleaseStringCriticalArgs,
    [jstring | NativePointerValue, NativePointerValue]
>>;

type _releaseStringUtfCharsHoverSignature = Assert<IsEqual<
    ReleaseStringUTFCharsArgs,
    [jstring | NativePointerValue, NativePointerValue]
>>;

type _decodeJObjectHoverSignature = Assert<IsEqual<
    DecodeJObjectArgs,
    [JniObjectReference | null | undefined, JniObjectReference]
>>;

declare const methods: JniRuntimeMethods;
declare const env: JniEnv;
declare const clazz: jclass;
declare const obj: jobject;
declare const methodId: jmethodID;
declare const javaString: jstring;
declare const intArray: jintArray;

const getFieldId: JniClassMemberLookupMethod<jfieldID> = methods.GetFieldID;
const getIntField: JniInstanceFieldMethod<jint> = env.GetIntField;
const releaseStringUtfChars: JniStringReleaseMethod = env.ReleaseStringUTFChars;
const decodeJObject: JniDecodeJObjectMethod = env.DecodeJObject;

const fieldId: jfieldID = getFieldId(clazz, "value", "I");
const fieldValue: jint = getIntField(obj, fieldId);
const createdObject: jobject = env.NewObject(clazz, methodId, 1, true);
const utfChars: NativePointer = env.GetStringUTFChars(javaString);
const criticalChars: NativePointer = env.GetStringCritical(javaString);
const intElements: jintArrayElements = env.GetIntArrayElements(intArray);
const decodedObject: MirrorObject = decodeJObject(null, obj);

env.ReleaseStringCritical(javaString, criticalChars);
releaseStringUtfChars(javaString, utfChars);

void fieldValue;
void createdObject;
void intElements;
void decodedObject;

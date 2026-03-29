import type {
    JniBoundInstanceField,
    JniBoundInstanceMethod,
    JniBoundStaticField,
    JniBoundStaticMethod,
    JniConstructorAccessor,
    JniUnboundInstanceField,
    JniUnboundInstanceMethod,
} from "../src/capabilities/jni/members.js";
import type {
    jclass,
    jintArray,
    jintArrayElements,
    jfieldID,
    jint,
    jmethodID,
    jobject,
    jobjectArray,
} from "../src/capabilities/jni/refs.js";
import type { jstring } from "../src/capabilities/jni/strings.js";

declare const obj: jobject;
declare const clazz: jclass;
declare const separator: jstring;

const boundMethod: JniBoundInstanceMethod<jstring> = obj.$method<jstring>("toString", "()Ljava/lang/String;");
const boundText: jstring = boundMethod.call();
const boundScopedText: string = boundMethod.withLocal(value => value.toString());
const boundDirectText: jstring = obj.$call<jstring>("toString", "()Ljava/lang/String;");
const boundMethodId: jmethodID = obj.$methodIdFor("toString", "()Ljava/lang/String;");

const unboundMethod: JniUnboundInstanceMethod<jstring> = clazz.$method<jstring>("toString", "()Ljava/lang/String;");
const unboundText: jstring = unboundMethod.call(obj);
const unboundScopedText: string = unboundMethod.withLocal(obj, value => value.toString());
const unboundDirectText: jstring = clazz.$call<jstring>(obj, "toString", "()Ljava/lang/String;");
const classSelfText: jstring = clazz.$call<jstring>("toString", "()Ljava/lang/String;");
const unboundMethodId: jmethodID = clazz.$methodIdFor("toString", "()Ljava/lang/String;");

const staticMethod: JniBoundStaticMethod<jobject> = clazz.$staticMethod<jobject>("valueOf", "(I)Ljava/lang/Object;");
const staticValue: jobject = staticMethod.call(1);
const staticDirectValue: jobject = clazz.$staticCall<jobject>("valueOf", "(I)Ljava/lang/Object;", 1);
const staticMethodId: jmethodID = clazz.$staticMethodIdFor("valueOf", "(I)Ljava/lang/Object;");

const boundField: JniBoundInstanceField<jint> = obj.$field<jint>("value", "I");
const boundFieldValue: jint = boundField.get();
boundField.set(1);
boundField.set(boundFieldValue);
const boundScopedFieldValue: number = boundField.withLocal(value => value.toInt());
const boundDirectFieldValue: jint = obj.$getField<jint>("value", "I");
obj.$setField<jint>("value", "I", 2);
const boundFieldId: jfieldID = obj.$fieldIdFor("value", "I");
const boundPrimitiveArray: jintArray = obj.$call<jintArray>("toIntArray", "()[I");
const boundPrimitiveElements: jintArrayElements = boundPrimitiveArray.$elements();
const boundObjectArray: jobjectArray = obj.$call<jobjectArray>("split", "(Ljava/lang/String;)[Ljava/lang/String;", separator);
const boundObjectArrayLength: number = boundObjectArray.$length;

const unboundField: JniUnboundInstanceField<jint> = clazz.$field<jint>("value", "I");
const unboundFieldValue: jint = unboundField.get(obj);
unboundField.set(obj, 3);
const unboundScopedFieldValue: number = unboundField.withLocal(obj, value => value.toInt());
const unboundDirectFieldValue: jint = clazz.$getField<jint>(obj, "value", "I");
clazz.$setField<jint>(obj, "value", "I", 4);
const classSelfFieldValue: jint = clazz.$getField<jint>("value", "I");
clazz.$setField<jint>("value", "I", 5);
const unboundFieldId: jfieldID = clazz.$fieldIdFor("value", "I");

const staticField: JniBoundStaticField<jint> = clazz.$staticField<jint>("MAX_VALUE", "I");
const staticFieldValue: jint = staticField.get();
staticField.set(5);
const staticScopedFieldValue: number = staticField.withLocal(value => value.toInt());
const staticDirectFieldValue: jint = clazz.$getStaticField<jint>("MAX_VALUE", "I");
clazz.$setStaticField<jint>("MAX_VALUE", "I", 6);
const staticFieldId: jfieldID = clazz.$staticFieldIdFor("MAX_VALUE", "I");

const constructorAccessor: JniConstructorAccessor<jobject> = clazz.$constructor<jobject>("(I)V");
const constructed: jobject = constructorAccessor.newInstance(1);
const constructedDirect: jobject = clazz.$new<jobject>("(I)V", 2);

// @ts-expect-error $method() now returns a facade accessor, not a low-level jmethodID lookup.
const legacyMethodId: jmethodID = obj.$method("toString", "()Ljava/lang/String;");
// @ts-expect-error unbound instance method accessors still require an explicit target object.
const invalidUnboundCall: jstring = unboundMethod.call();
// @ts-expect-error unbound instance method accessors still require an explicit target object for withLocal().
const invalidUnboundWithLocal = unboundMethod.withLocal(value => value.toString());
// @ts-expect-error bound instance method accessors must not accept an extra target object.
const invalidBoundWithLocal = boundMethod.withLocal(obj, value => value.toString());
// @ts-expect-error unbound instance field accessors still require an explicit target object.
const invalidUnboundFieldGet: jint = unboundField.get();
// @ts-expect-error unbound instance field accessors still require an explicit target object and value.
unboundField.set(1);
// @ts-expect-error unbound instance field accessors still require an explicit target object for withLocal().
const invalidUnboundFieldWithLocal = unboundField.withLocal(value => value.toInt());
// @ts-expect-error bound instance field accessors must not accept an extra target object.
const invalidBoundFieldGet: jint = boundField.get(obj);
// @ts-expect-error bound instance field accessors must not accept an extra target object.
boundField.set(obj, 1);
// @ts-expect-error bound instance field accessors must not accept an extra target object for withLocal().
const invalidBoundFieldWithLocal = boundField.withLocal(obj, value => value.toInt());
// @ts-expect-error bound static field accessors must not accept an explicit clazz argument.
const invalidStaticFieldGet: jint = staticField.get(clazz);
// @ts-expect-error bound static field accessors must not accept an explicit clazz argument.
staticField.set(clazz, 1);
// @ts-expect-error bound static field accessors must not accept an explicit clazz argument for withLocal().
const invalidStaticFieldWithLocal = staticField.withLocal(clazz, value => value.toInt());

void boundText;
void boundScopedText;
void boundDirectText;
void boundMethodId;
void boundPrimitiveElements;
void boundObjectArrayLength;
void unboundText;
void unboundScopedText;
void unboundDirectText;
void classSelfText;
void unboundMethodId;
void staticValue;
void staticDirectValue;
void staticMethodId;
void boundScopedFieldValue;
void boundDirectFieldValue;
void boundFieldId;
void unboundFieldValue;
void unboundScopedFieldValue;
void unboundDirectFieldValue;
void classSelfFieldValue;
void unboundFieldId;
void staticFieldValue;
void staticScopedFieldValue;
void staticDirectFieldValue;
void staticFieldId;
void constructed;
void constructedDirect;
void legacyMethodId;
void invalidUnboundCall;
void invalidUnboundWithLocal;
void invalidBoundWithLocal;
void invalidUnboundFieldGet;
void invalidUnboundFieldWithLocal;
void invalidBoundFieldGet;
void invalidBoundFieldWithLocal;
void invalidStaticFieldGet;
void invalidStaticFieldWithLocal;

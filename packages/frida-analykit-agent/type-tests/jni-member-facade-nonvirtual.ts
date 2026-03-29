import type {
    JniBoundNonvirtualMethod,
    JniUnboundNonvirtualMethod,
} from "../src/jni/members.js";
import type {
    jclass,
    jmethodID,
    jobject,
} from "../src/jni/refs.js";
import type { jstring } from "../src/jni/strings.js";

declare const obj: jobject;
declare const clazz: jclass;
declare const objectClass: jclass;

const boundNonvirtualMethod: JniBoundNonvirtualMethod<jstring> =
    obj.$nonvirtualMethod<jstring>(objectClass, "toString", "()Ljava/lang/String;");
const boundNonvirtualText: jstring = boundNonvirtualMethod.call();
const boundNonvirtualDirectText: jstring = obj.$nonvirtualCall<jstring>(
    objectClass,
    "toString",
    "()Ljava/lang/String;",
);
const boundNonvirtualMethodId: jmethodID = boundNonvirtualMethod.$id;
const boundDeclaringClass: jclass = boundNonvirtualMethod.$declaringClass;

const unboundNonvirtualMethod: JniUnboundNonvirtualMethod<jstring> =
    clazz.$nonvirtualMethod<jstring>("toString", "()Ljava/lang/String;");
const unboundNonvirtualText: jstring = unboundNonvirtualMethod.call(obj);
const unboundNonvirtualDirectText: jstring = clazz.$nonvirtualCall<jstring>(
    obj,
    "toString",
    "()Ljava/lang/String;",
);
const unboundNonvirtualMethodId: jmethodID = clazz.$methodIdFor("toString", "()Ljava/lang/String;");
const unboundDeclaringClass: jclass = unboundNonvirtualMethod.$declaringClass;

void boundNonvirtualText;
void boundNonvirtualDirectText;
void boundNonvirtualMethodId;
void boundDeclaringClass;
void unboundNonvirtualText;
void unboundNonvirtualDirectText;
void unboundNonvirtualMethodId;
void unboundDeclaringClass;

import { NativePointerObject } from "../../helper.js";
import type { JniCallArgument } from "./call_methods.js";
import { JNI_REF_KIND_MASK } from "./factory.js";
import {
    createBoundInstanceField,
    createBoundInstanceMethod,
    createInstanceFieldAccessor,
    createInstanceMethodAccessor,
    createBoundNonvirtualMethod,
    createBoundStaticField,
    createBoundStaticMethod,
    createConstructorAccessor,
    createUnboundNonvirtualMethod,
    type JniBoundNonvirtualMethod,
    type JniBoundStaticField,
    type JniBoundStaticMethod,
    type JniConstructorAccessor,
    type JniFieldValue,
    type JniInstanceFieldAccessorFor,
    type JniInstanceMethodAccessorFor,
    type JniMethodValue,
    type JniMemberHostKind,
    type JniUnboundNonvirtualMethod,
    lookupFieldIdFor,
    lookupMethodIdFor,
    lookupStaticFieldIdFor,
    lookupStaticMethodIdFor,
} from "./members.js";
import type { JniFieldSetterValue } from "./runtime_fields.js";
import { IndirectRefKind } from "./struct.js";
import { JNIEnv } from "./env.js";
import type { jstring } from "./strings.js";

export class MirrorObject extends NativePointerObject {}

export interface JObjectTypeArg {
    parent?: jobject<JniMemberHostKind> | null;
    isStatic?: boolean;
}

export interface JFieldIDTypeArg {
    ownerClass?: jclass | null;
    isStatic?: boolean;
}

type JStringFactory = (handle: NativePointer, options?: JObjectTypeArg) => jstring;

let createJString: JStringFactory | null = null;

export function registerJStringFactory(factory: JStringFactory): void {
    createJString = factory;
}

function wrapJString(handle: NativePointer, options: JObjectTypeArg): jstring {
    if (createJString === null) {
        throw new Error("jstring factory is not initialized");
    }
    return createJString(handle, options);
}

function normalizeJClassHandle(value: jclass | NativePointerValue): jclass {
    return value instanceof jclass ? value : new jclass(ptr(value as never));
}

export class jobject<THostKind extends JniMemberHostKind = "instance"> extends NativePointerObject {
    protected _parent: jobject<JniMemberHostKind> | null;
    protected _class: jclass | undefined;
    protected _isStatic: boolean;
    protected _deleted = false;

    constructor(
        handle: NativePointer,
        {
            parent = null,
            isStatic = parent?._isStatic ?? false,
        }: JObjectTypeArg = {},
    ) {
        super(handle);
        this._parent = parent;
        this._isStatic = isStatic;
    }

    $unwrap(): JObjectTypeArg {
        return {
            isStatic: this._isStatic,
            parent: this._parent,
        };
    }

    $toString(): string {
        const result = JNIEnv.CallObjectMethod(this, JNIEnv.javaLangObject().toString);
        const utf16 = result.$jstring.toUTF16String();
        const text = utf16.toString();
        utf16.release();
        result.$unref();
        return text;
    }

    get $IndirectRefKind(): number {
        return Number(this.$handle.and(JNI_REF_KIND_MASK));
    }

    $bind(options: JObjectTypeArg): this {
        const Constructor = this.constructor as { new(handle: NativePointer, opt?: JObjectTypeArg): jobject<THostKind> };
        return new Constructor(this.$handle, { ...this.$unwrap(), ...options }) as this;
    }

    get $class(): jclass {
        if (this._class !== undefined) {
            return this._class;
        }
        const cls = JNIEnv.GetObjectClass(this.$handle)
            .$globalRef()
            .$jclass.$bind({ parent: this, isStatic: this._isStatic });
        this._class = cls;
        return cls;
    }

    $method<Ret extends JniMethodValue = JniMethodValue>(
        name: string,
        sig: string,
    ): JniInstanceMethodAccessorFor<THostKind, Ret> {
        return createInstanceMethodAccessor<THostKind, Ret>(this, name, sig);
    }

    $call<Ret extends JniMethodValue = JniMethodValue>(name: string, sig: string, ...args: JniCallArgument[]): Ret {
        return createBoundInstanceMethod<Ret>(this, name, sig).call(...args);
    }

    $nonvirtualMethod<Ret extends JniMethodValue = JniMethodValue>(
        clazz: jclass | NativePointerValue,
        name: string,
        sig: string,
    ): JniBoundNonvirtualMethod<Ret> {
        return createBoundNonvirtualMethod(this, normalizeJClassHandle(clazz), name, sig);
    }

    $nonvirtualCall<Ret extends JniMethodValue = JniMethodValue>(
        clazz: jclass | NativePointerValue,
        name: string,
        sig: string,
        ...args: JniCallArgument[]
    ): Ret {
        return this.$nonvirtualMethod<Ret>(clazz, name, sig).call(...args);
    }

    $field<Value extends JniFieldValue = JniFieldValue>(
        name: string,
        sig: string,
    ): JniInstanceFieldAccessorFor<THostKind, Value> {
        return createInstanceFieldAccessor<THostKind, Value>(this, name, sig);
    }

    $getField<Value extends JniFieldValue = JniFieldValue>(name: string, sig: string): Value {
        return createBoundInstanceField<Value>(this, name, sig).get();
    }

    $setField<Value extends JniFieldValue = JniFieldValue>(
        name: string,
        sig: string,
        value: JniFieldSetterValue<Value>,
    ): void {
        createBoundInstanceField<Value>(this, name, sig).set(value);
    }

    $methodIdFor(name: string, sig: string): jmethodID {
        return lookupMethodIdFor(this.$class, name, sig);
    }

    $fieldIdFor(name: string, sig: string): jfieldID {
        return lookupFieldIdFor(this.$class, name, sig);
    }

    $methodID(methodId: jmethodID | NativePointerValue): jobject {
        return JNIEnv.ToReflectedMethod(this.$class, methodId, this._isStatic).$bind({ parent: this });
    }

    $getName(): string {
        const handle = this;
        const javaLang = this._parent === null ? JNIEnv.javaLangClass() : JNIEnv.javaLangReflectMethod();
        const result = JNIEnv.CallObjectMethod(handle, javaLang.getName);
        const utf16 = result.$jstring.toUTF16String();
        const text = utf16.toString();
        utf16.release();
        result.$unref();
        return text;
    }

    get $jstring(): jstring {
        return wrapJString(this.$handle, this.$unwrap());
    }

    get $jobject(): jobject {
        return new jobject(this.$handle, this.$unwrap());
    }

    get $jclass(): jclass {
        return new jclass(this.$handle, this.$unwrap());
    }

    get $jfieldID(): jfieldID {
        return new jfieldID(this.$handle);
    }

    get $jint(): jint {
        return new jint(this.$handle);
    }

    get $jfloat(): jfloat {
        return new jfloat(this.$handle);
    }

    get $jdouble(): jdouble {
        return new jdouble(this.$handle);
    }

    get $jbyte(): jbyte {
        return new jbyte(this.$handle);
    }

    get $jchar(): jchar {
        return new jchar(this.$handle);
    }

    get $jlong(): jlong {
        return new jlong(this.$handle);
    }

    get $jshort(): jshort {
        return new jshort(this.$handle);
    }

    get $jboolean(): jboolean {
        return new jboolean(this.$handle);
    }

    get $jobjectArray(): jobjectArray {
        return new jobjectArray(this.$handle, this.$unwrap());
    }

    get $jbooleanArray(): jbooleanArray {
        return new jbooleanArray(this.$handle, this.$unwrap());
    }

    get $jbyteArray(): jbyteArray {
        return new jbyteArray(this.$handle, this.$unwrap());
    }

    get $jcharArray(): jcharArray {
        return new jcharArray(this.$handle, this.$unwrap());
    }

    get $jshortArray(): jshortArray {
        return new jshortArray(this.$handle, this.$unwrap());
    }

    get $jintArray(): jintArray {
        return new jintArray(this.$handle, this.$unwrap());
    }

    get $jlongArray(): jlongArray {
        return new jlongArray(this.$handle, this.$unwrap());
    }

    get $jfloatArray(): jfloatArray {
        return new jfloatArray(this.$handle, this.$unwrap());
    }

    get $jdoubleArray(): jdoubleArray {
        return new jdoubleArray(this.$handle, this.$unwrap());
    }

    $decode(thread: jobject | NativePointer | null = null): MirrorObject {
        return JNIEnv.DecodeJObject(thread, this);
    }

    $unref(): boolean | undefined {
        if (this._deleted) {
            return true;
        }
        this._deleted = true;
        switch (this.$IndirectRefKind) {
            case IndirectRefKind.kHandleScopeOrInvalid:
            case IndirectRefKind.kLocal:
                JNIEnv.DeleteLocalRef(this);
                break;
            case IndirectRefKind.kGlobal:
                JNIEnv.DeleteGlobalRef(this);
                break;
            case IndirectRefKind.kWeakGlobal:
                JNIEnv.DeleteWeakGlobalRef(this);
                break;
        }
        return undefined;
    }

    $globalRef(): jobject<THostKind> {
        if (this.$IndirectRefKind === IndirectRefKind.kGlobal) {
            return this;
        }
        const globalRef = JNIEnv.NewGlobalRef(this) as jobject<THostKind>;
        const handle = ptr(globalRef.$handle.toString());
        Script.bindWeak(globalRef.$handle, () => {
            JNIEnv.DeleteGlobalRef(handle);
        });
        this.$unref();
        return globalRef;
    }

    toString(): string {
        return `<jobject: ${this.$handle}>[${this.$IndirectRefKind}]`;
    }
}

export class jmethod extends jobject {
    constructor(handle: NativePointer, options: JObjectTypeArg = {}) {
        super(handle, { parent: options.parent ?? new jobject(NULL), isStatic: options.isStatic });
    }

    toString(): string {
        return `<jmethod: ${this.$handle}>[${this.$IndirectRefKind}]`;
    }
}

export class jclass extends jobject<"class"> {
    constructor(handle: NativePointer, { isStatic = false }: JObjectTypeArg = {}) {
        super(handle, { isStatic });
    }

    toString(): string {
        return `<jclass: ${this.$handle}>[${this.$IndirectRefKind}]`;
    }

    $methodID(methodId: jmethodID | NativePointerValue): jobject {
        return JNIEnv.ToReflectedMethod(this, methodId, this._isStatic).$bind({ parent: this });
    }

    $nonvirtualMethod<Ret extends JniMethodValue = JniMethodValue>(
        clazz: jclass | NativePointerValue,
        name: string,
        sig: string,
    ): JniBoundNonvirtualMethod<Ret>;
    $nonvirtualMethod<Ret extends JniMethodValue = JniMethodValue>(
        name: string,
        sig: string,
    ): JniUnboundNonvirtualMethod<Ret>;
    $nonvirtualMethod<Ret extends JniMethodValue = JniMethodValue>(
        ...args: unknown[]
    ): JniBoundNonvirtualMethod<Ret> | JniUnboundNonvirtualMethod<Ret> {
        if (args.length === 2) {
            const [name, sig] = args as [string, string];
            return createUnboundNonvirtualMethod(this, name, sig);
        }
        const [clazz, name, sig] = args as [jclass | NativePointerValue, string, string];
        return createBoundNonvirtualMethod(this, normalizeJClassHandle(clazz), name, sig);
    }

    $call<Ret extends JniMethodValue = JniMethodValue>(name: string, sig: string, ...args: JniCallArgument[]): Ret;
    $call<Ret extends JniMethodValue = JniMethodValue>(
        target: jobject | jclass | NativePointerValue,
        name: string,
        sig: string,
        ...args: JniCallArgument[]
    ): Ret;
    $call<Ret extends JniMethodValue = JniMethodValue>(...args: unknown[]): Ret {
        if (typeof args[0] === "string") {
            const [name, sig, ...callArgs] = args as [string, string, ...JniCallArgument[]];
            return createBoundInstanceMethod<Ret>(this, name, sig).call(...callArgs);
        }
        const [target, name, sig, ...callArgs] = args as [jobject | jclass | NativePointerValue, string, string, ...JniCallArgument[]];
        return this.$method<Ret>(name, sig).call(target, ...callArgs);
    }

    $nonvirtualCall<Ret extends JniMethodValue = JniMethodValue>(
        clazz: jclass | NativePointerValue,
        name: string,
        sig: string,
        ...args: JniCallArgument[]
    ): Ret;
    $nonvirtualCall<Ret extends JniMethodValue = JniMethodValue>(
        target: jobject | jclass | NativePointerValue,
        name: string,
        sig: string,
        ...args: JniCallArgument[]
    ): Ret;
    $nonvirtualCall<Ret extends JniMethodValue = JniMethodValue>(...args: unknown[]): Ret {
        const [first, name, sig, ...callArgs] = args as [
            jclass | jobject | NativePointerValue,
            string,
            string,
            ...JniCallArgument[]
        ];
        if (first instanceof jclass) {
            return this.$nonvirtualMethod<Ret>(first, name, sig).call(...callArgs);
        }
        return this.$nonvirtualMethod<Ret>(name, sig).call(first as jobject | jclass | NativePointerValue, ...callArgs);
    }

    $getField<Value extends JniFieldValue = JniFieldValue>(name: string, sig: string): Value;
    $getField<Value extends JniFieldValue = JniFieldValue>(
        target: jobject | jclass | NativePointerValue,
        name: string,
        sig: string,
    ): Value;
    $getField<Value extends JniFieldValue = JniFieldValue>(...args: unknown[]): Value {
        if (typeof args[0] === "string") {
            const [name, sig] = args as [string, string];
            return createBoundInstanceField<Value>(this, name, sig).get();
        }
        const [target, name, sig] = args as [jobject | jclass | NativePointerValue, string, string];
        return this.$field<Value>(name, sig).get(target);
    }

    $setField<Value extends JniFieldValue = JniFieldValue>(
        name: string,
        sig: string,
        value: JniFieldSetterValue<Value>,
    ): void;
    $setField<Value extends JniFieldValue = JniFieldValue>(
        target: jobject | jclass | NativePointerValue,
        name: string,
        sig: string,
        value: JniFieldSetterValue<Value>,
    ): void;
    $setField<Value extends JniFieldValue = JniFieldValue>(...args: unknown[]): void {
        if (typeof args[0] === "string") {
            const [name, sig, value] = args as [string, string, JniFieldSetterValue<Value>];
            createBoundInstanceField<Value>(this, name, sig).set(value);
            return;
        }
        const [target, name, sig, value] = args as [
            jobject | jclass | NativePointerValue,
            string,
            string,
            JniFieldSetterValue<Value>,
        ];
        this.$field<Value>(name, sig).set(target, value);
    }

    $staticMethod<Ret extends JniMethodValue = JniMethodValue>(name: string, sig: string): JniBoundStaticMethod<Ret> {
        return createBoundStaticMethod(this, name, sig);
    }

    $staticCall<Ret extends JniMethodValue = JniMethodValue>(
        name: string,
        sig: string,
        ...args: JniCallArgument[]
    ): Ret {
        return this.$staticMethod<Ret>(name, sig).call(...args);
    }

    $staticField<Value extends JniFieldValue = JniFieldValue>(name: string, sig: string): JniBoundStaticField<Value> {
        return createBoundStaticField(this, name, sig);
    }

    $getStaticField<Value extends JniFieldValue = JniFieldValue>(name: string, sig: string): Value {
        return this.$staticField<Value>(name, sig).get();
    }

    $setStaticField<Value extends JniFieldValue = JniFieldValue>(
        name: string,
        sig: string,
        value: JniFieldSetterValue<Value>,
    ): void {
        this.$staticField<Value>(name, sig).set(value);
    }

    $constructor<Ret extends jobject = jobject>(sig: string): JniConstructorAccessor<Ret> {
        return createConstructorAccessor(this, sig);
    }

    $new<Ret extends jobject = jobject>(sig: string, ...args: JniCallArgument[]): Ret {
        return this.$constructor<Ret>(sig).newInstance(...args);
    }

    $staticMethodIdFor(name: string, sig: string): jmethodID {
        return lookupStaticMethodIdFor(this, name, sig);
    }

    $methodIdFor(name: string, sig: string): jmethodID {
        return lookupMethodIdFor(this, name, sig);
    }

    $staticFieldIdFor(name: string, sig: string): jfieldID {
        return lookupStaticFieldIdFor(this, name, sig);
    }

    $fieldIdFor(name: string, sig: string): jfieldID {
        return lookupFieldIdFor(this, name, sig);
    }

    $toString(): string {
        if (JNIEnv.ExceptionCheck()) {
            return "";
        }
        if (this.$handle.isNull() || JNIEnv.IsSameObject(this, NULL)) {
            return "";
        }
        const result = JNIEnv.CallObjectMethod(this, JNIEnv.javaLangObject().toString);
        const utf16 = result.$jstring.toUTF16String();
        const text = utf16.toString();
        utf16.release();
        result.$unref();
        return text;
    }

    $getName(): string {
        const handle = this._parent ?? this;
        const result = JNIEnv.CallObjectMethod(handle, JNIEnv.javaLangClass().getName);
        const utf16 = result.$jstring.toUTF16String();
        const text = utf16.toString();
        utf16.release();
        result.$unref();
        return text;
    }
}

export class jmethodID extends jobject {
    $getName(): string {
        const result = JNIEnv.CallObjectMethod(this._parent!, JNIEnv.javaLangReflectMethod().getName);
        const utf16 = result.$jstring.toUTF16String();
        const text = utf16.toString();
        utf16.release();
        result.$unref();
        return text;
    }

    toString(): string {
        return `<jmethodID: ${this.$handle}>[${this.$IndirectRefKind}]`;
    }
}

export class jfieldID extends NativePointerObject {
    private readonly _ownerClass: jclass | null;
    private readonly _isStatic: boolean;

    constructor(
        handle: NativePointer,
        {
            ownerClass = null,
            isStatic = false,
        }: JFieldIDTypeArg = {},
    ) {
        super(handle);
        this._ownerClass = ownerClass;
        this._isStatic = isStatic;
    }

    $unwrap(): JFieldIDTypeArg {
        return {
            ownerClass: this._ownerClass,
            isStatic: this._isStatic,
        };
    }

    $bind(options: JFieldIDTypeArg): this {
        const Constructor = this.constructor as { new(handle: NativePointer, opt?: JFieldIDTypeArg): jfieldID };
        return new Constructor(this.$handle, { ...this.$unwrap(), ...options }) as this;
    }

    get $ownerClass(): jclass | null {
        return this._ownerClass;
    }

    get $isStatic(): boolean {
        return this._isStatic;
    }

    toString(): string {
        return `<jfieldID: ${this.$handle}>`;
    }
}

export class jboolean extends NativePointerObject {
    toBool(): boolean {
        return this.$handle.and(0xff).toInt32() !== 0;
    }

    toString(): string {
        return `<jboolean: ${this.$handle}>`;
    }
}

export class jbyte extends NativePointerObject {
    toByte(): number {
        // JNI returns low-width integers in a wider register on some ABIs, so only the low byte is stable.
        return this.$handle.shl(56).shr(56).toInt32();
    }

    toString(): string {
        return `<jbyte: ${this.$handle}>`;
    }
}

export class jchar extends NativePointerObject {
    toChar(): number {
        return this.$handle.and(0xffff).toInt32();
    }

    toString(): string {
        return `<jchar: ${this.$handle}>`;
    }
}

export class jdouble extends NativePointerObject {
    constructor(handle: NativePointer | number) {
        super(handle as NativePointer);
    }

    toDouble(): number {
        const handle = this.$handle as NativePointer | number;
        return typeof handle === "number" ? handle : Number(handle);
    }

    toString(): string {
        return `<jdouble: ${this.$handle}>`;
    }
}

export class jfloat extends NativePointerObject {
    constructor(handle: NativePointer | number) {
        super(handle as NativePointer);
    }

    toFloat(): number {
        const handle = this.$handle as NativePointer | number;
        return typeof handle === "number" ? handle : Number(handle);
    }

    toString(): string {
        return `<jfloat: ${this.$handle}>`;
    }
}

export class jint extends NativePointerObject {
    toInt(): number {
        const handle = this.$handle as NativePointer | number;
        return typeof handle === "number" ? handle | 0 : handle.toInt32();
    }

    toString(): string {
        return `<jint: ${this.$handle}>`;
    }
}

export class jlong extends NativePointerObject {
    toLong(): number {
        return Number(this.$handle);
    }

    toString(): string {
        return `<jlong: ${this.$handle}>`;
    }
}

export class jshort extends NativePointerObject {
    toShort(): number {
        return this.$handle.shl(48).shr(48).toInt32();
    }

    toString(): string {
        return `<jshort: ${this.$handle}>`;
    }
}

export class jvoid extends NativePointerObject {
    toString(): string {
        return `<jvoid: ${this.$handle}>`;
    }
}

export class jthrowable extends jobject {
    toString(): string {
        return `<jthrowable: ${this.$handle}>`;
    }
}

export class jvalue {
    private readonly _handle: NativePointer;

    constructor(handle: NativePointer) {
        this._handle = handle;
    }

    $index(offset: number): NativePointer {
        return this._handle.add(offset * Process.pointerSize).readPointer();
    }

    jobject(offset: number): jobject {
        return new jobject(this.$index(offset));
    }

    jstring(offset: number): jstring {
        return wrapJString(this.$index(offset), {});
    }

    toString(): string {
        return `<jvalue: ${this._handle}>`;
    }
}

export abstract class jarray extends jobject {
    get $length(): number {
        return JNIEnv.GetArrayLength(this as never).toInt();
    }
}

abstract class jprimitiveArrayElements<T> extends NativePointerObject {
    protected abstract readonly _pointerSize: number;
    protected abstract $readElement(pointer: NativePointer): T;

    $index(index: number): T {
        return this.$readElement(this.$handle.add(index * this._pointerSize));
    }
}

abstract class jprimitiveArray<TElements extends jprimitiveArrayElements<unknown>> extends jarray {
    protected abstract $getElements(): TElements;
    protected abstract $releaseElements(elements: TElements, mode: number): void;

    $elements(): TElements {
        return this.$getElements();
    }

    withElements<Result>(use: (elements: TElements) => Result, mode = 0): Result {
        const elements = this.$elements();
        try {
            return use(elements);
        } finally {
            this.$releaseElements(elements, mode);
        }
    }
}

export class jobjectArray extends jarray {
    $index(index: number): jobject {
        return JNIEnv.GetObjectArrayElement(this, index);
    }
}

export class jbooleanArrayElements extends jprimitiveArrayElements<jboolean> {
    protected readonly _pointerSize = 1;

    protected $readElement(pointer: NativePointer): jboolean {
        return new jboolean(ptr(pointer.readU8() as never));
    }
}

export class jbyteArrayElements extends jprimitiveArrayElements<jbyte> {
    protected readonly _pointerSize = 1;

    protected $readElement(pointer: NativePointer): jbyte {
        return new jbyte(ptr(pointer.readS8() as never));
    }
}

export class jcharArrayElements extends jprimitiveArrayElements<jchar> {
    protected readonly _pointerSize = 2;

    protected $readElement(pointer: NativePointer): jchar {
        return new jchar(ptr(pointer.readU16() as never));
    }
}

export class jdoubleArrayElements extends jprimitiveArrayElements<jdouble> {
    protected readonly _pointerSize = 8;

    protected $readElement(pointer: NativePointer): jdouble {
        return new jdouble(pointer.readDouble());
    }
}

export class jfloatArrayElements extends jprimitiveArrayElements<jfloat> {
    protected readonly _pointerSize = 4;

    protected $readElement(pointer: NativePointer): jfloat {
        return new jfloat(pointer.readFloat());
    }
}

export class jintArrayElements extends jprimitiveArrayElements<jint> {
    protected readonly _pointerSize = 4;

    protected $readElement(pointer: NativePointer): jint {
        return new jint(ptr(pointer.readS32() as never));
    }
}

export class jlongArrayElements extends jprimitiveArrayElements<jlong> {
    protected readonly _pointerSize = 8;

    protected $readElement(pointer: NativePointer): jlong {
        return new jlong(ptr(pointer.readS64() as never));
    }
}

export class jshortArrayElements extends jprimitiveArrayElements<jshort> {
    protected readonly _pointerSize = 2;

    protected $readElement(pointer: NativePointer): jshort {
        return new jshort(ptr(pointer.readS16() as never));
    }
}

export class jbooleanArray extends jprimitiveArray<jbooleanArrayElements> {
    protected $getElements(): jbooleanArrayElements {
        return JNIEnv.GetBooleanArrayElements(this);
    }

    protected $releaseElements(elements: jbooleanArrayElements, mode: number): void {
        JNIEnv.ReleaseBooleanArrayElements(this, elements, mode);
    }
}

export class jbyteArray extends jprimitiveArray<jbyteArrayElements> {
    protected $getElements(): jbyteArrayElements {
        return JNIEnv.GetByteArrayElements(this);
    }

    protected $releaseElements(elements: jbyteArrayElements, mode: number): void {
        JNIEnv.ReleaseByteArrayElements(this, elements, mode);
    }
}

export class jcharArray extends jprimitiveArray<jcharArrayElements> {
    protected $getElements(): jcharArrayElements {
        return JNIEnv.GetCharArrayElements(this);
    }

    protected $releaseElements(elements: jcharArrayElements, mode: number): void {
        JNIEnv.ReleaseCharArrayElements(this, elements, mode);
    }
}

export class jdoubleArray extends jprimitiveArray<jdoubleArrayElements> {
    protected $getElements(): jdoubleArrayElements {
        return JNIEnv.GetDoubleArrayElements(this);
    }

    protected $releaseElements(elements: jdoubleArrayElements, mode: number): void {
        JNIEnv.ReleaseDoubleArrayElements(this, elements, mode);
    }
}

export class jfloatArray extends jprimitiveArray<jfloatArrayElements> {
    protected $getElements(): jfloatArrayElements {
        return JNIEnv.GetFloatArrayElements(this);
    }

    protected $releaseElements(elements: jfloatArrayElements, mode: number): void {
        JNIEnv.ReleaseFloatArrayElements(this, elements, mode);
    }
}

export class jintArray extends jprimitiveArray<jintArrayElements> {
    protected $getElements(): jintArrayElements {
        return JNIEnv.GetIntArrayElements(this);
    }

    protected $releaseElements(elements: jintArrayElements, mode: number): void {
        JNIEnv.ReleaseIntArrayElements(this, elements, mode);
    }
}

export class jlongArray extends jprimitiveArray<jlongArrayElements> {
    protected $getElements(): jlongArrayElements {
        return JNIEnv.GetLongArrayElements(this);
    }

    protected $releaseElements(elements: jlongArrayElements, mode: number): void {
        JNIEnv.ReleaseLongArrayElements(this, elements, mode);
    }
}

export class jshortArray extends jprimitiveArray<jshortArrayElements> {
    protected $getElements(): jshortArrayElements {
        return JNIEnv.GetShortArrayElements(this);
    }

    protected $releaseElements(elements: jshortArrayElements, mode: number): void {
        JNIEnv.ReleaseShortArrayElements(this, elements, mode);
    }
}

export function unwrapJvalueArgs(args: jvalue, n: number): Array<NativePointer> {
    const list: NativePointer[] = [];
    for (let index = 0; index < n; index++) {
        list.push(args.$index(index));
    }
    return list;
}

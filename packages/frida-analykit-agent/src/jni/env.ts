import { Java } from "../bridges.js"
import { IndirectRefKind, JNI_VT } from "./struct.js"
import { nativeFunctionOptions } from '../consts.js'
import { help, NativePointerObject } from "../helper.js"
import { setGlobalProperties } from '../config.js'
import { NP, EnvJvmti, VMApi } from "../api/android.js"

function getThreadFromEnv(env: Java.Env): NativePointer {
    return env.handle.add(Process.pointerSize).readPointer()
}


interface nativeFunc {
    handle: NativePointer
    impl: AnyFunction
}

class MirrorObject extends NativePointerObject {
    constructor(handle: NativePointer) {
        super(handle)
    }
}



interface JObjectTypeArg {
    parent?: jobject | null
    isStatic?: boolean
}

export class jobject extends NativePointerObject {
    protected _parent: jobject | null
    protected _class: jclass | undefined
    protected _isStatic: boolean = false
    protected _deleted: boolean = false

    constructor(handle: NativePointer, {
        parent = null, 
        isStatic = parent?._isStatic || false,
    }: JObjectTypeArg = {}) {
        super(handle)
        this._parent = parent
        this._isStatic = isStatic
    }

    $unwrap(): { [key: string]: any } {
        return {
            isStatic: this._isStatic,
            parent: this._parent,
        }
    }

    $toString(): any {
        const result = JNIEnv.CallObjectMethod(this, JNIEnv.javaLangObject().toString)
        const utf16 = result.$jstring.toUTF16String()
        const str = utf16.toString()
        utf16.release()
        result.$unref()
        return str
    }

    get $IndirectRefKind(): number {
        return Number(this._handle.and(JniEnv.kKindMask))
    }

    $bind(kws: {isStatic?: boolean, parent?: jobject | null}): this {
        const opt = {...this.$unwrap(), ...kws}
        return new (this.constructor as { new(obj: any, opt?: {[key: string]: any}): any })(this._handle, opt)
    }

    get $class(): jclass {
        if(this._class !== undefined) {
            return this._class
        }
        const cls = JNIEnv.GetObjectClass(this._handle).$globalRef().$jclass.$bind({ parent: this, isStatic: this._isStatic })
        this._class = cls
        return cls
    }

    $method(name: string, sig: string): jmethodID {
        return JNIEnv.GetMethodID(this.$class, name, sig)
    }

    $methodID(methodId: any): jobject {
        return JNIEnv.ToReflectedMethod(this.$class, methodId, this._isStatic).$bind({parent: this})
    }

    $getName(): string {
        const handle = this
        const javaLang = this._parent === null ? JNIEnv.javaLangClass() : JNIEnv.javaLangReflectMethod()
        const result = JNIEnv.CallObjectMethod(handle, javaLang.getName)
        const utf16 = result.$jstring.toUTF16String()
        const str = utf16.toString()
        utf16.release()
        result.$unref()
        return str
    }

    get $jstring(): jstring { return new jstring(this.$handle, this.$unwrap()) }

    get $jobject(): jobject { return new jobject(this.$handle, this.$unwrap()) }

    get $jclass(): jclass { return new jclass(this.$handle, this.$unwrap()) }

    get $jint(): jint { return new jint(this.$handle) }

    get $jfloat(): jfloat { return new jfloat(this.$handle) }

    get $jdouble(): jdouble { return new jdouble(this.$handle) }

    get $jbyte(): jbyte { return new jbyte(this.$handle) }

    get $jchar(): jchar { return new jchar(this.$handle) }

    get $jlong(): jlong { return new jlong(this.$handle) }

    get $jshort(): jshort { return new jshort(this.$handle) }

    get $jboolean(): jboolean { return new jboolean(this.$handle) }

    get $jobjectArray(): jobjectArray { return new jobjectArray(this.$handle) }

    $decode(thread: jobject | NativePointer | null = null): MirrorObject {
        return JNIEnv.DecodeJObject(thread, this)
    }

    $unref(){
        if(this._deleted) {
            return true
        }
        this._deleted = true
        switch(this.$IndirectRefKind) {
            case IndirectRefKind.kHandleScopeOrInvalid:
            case IndirectRefKind.kLocal:
                JNIEnv.DeleteLocalRef(this)
                break
            case IndirectRefKind.kGlobal:
                JNIEnv.DeleteGlobalRef(this)
                break
            case IndirectRefKind.kWeakGlobal:
                JNIEnv.DeleteWeakGlobalRef(this)
                break
        }
    }

    $globalRef(): jobject {
        if(this.$IndirectRefKind === IndirectRefKind.kGlobal) {
            return this
        }
        const glo = JNIEnv.NewGlobalRef(this)
        const handle = ptr(glo.$handle.toString())
        Script.bindWeak(glo.$handle, ()=>{
            JNIEnv.DeleteGlobalRef(handle)
        })
        this.$unref()
        return glo
    }

    toString(){
        return `<jobject: ${this.$handle}>[${this.$IndirectRefKind}]`
    }
}


export class jmethod extends jobject {
    constructor(handle: NativePointer, opt: {[key: string]: any}={}) {
        if(!('parent' in opt)) {
            opt.parent = new jobject(NULL)
        }
        super(handle, opt)
    }

    toString() {
        return `<jmethod: ${this.$handle}>[${this.$IndirectRefKind}]`
    }
}


export class jclass extends jobject {
    constructor(handle: NativePointer, {isStatic = false}: JObjectTypeArg = {}) {
        super(handle, {isStatic})
    }

    toString() {
        return `<jclass: ${this.$handle}>[${this.$IndirectRefKind}]`
    }

    $methodID(methodId: any): jobject {
        return JNIEnv.ToReflectedMethod(this, methodId, this._isStatic).$bind({parent: this})
    }

    $method(name: string, sig: string): jmethodID {
        return JNIEnv.GetMethodID(this, name, sig)
    }

    $toString(): any {
        const isExcept = JNIEnv.ExceptionCheck()
        if(isExcept) {
            return ''
        }

        if(this.$handle.isNull() || JNIEnv.IsSameObject(this, NULL)) {
            return ''
        }
        const result = JNIEnv.CallObjectMethod(this, JNIEnv.javaLangObject().toString)
        const utf16 = result.$jstring.toUTF16String()
        const str = utf16.toString()
        utf16.release()
        result.$unref()
        return str
    }

    $getName(): string {
        const handle = this._parent ? this._parent : this
        const javaLang = JNIEnv.javaLangClass()
        const result = JNIEnv.CallObjectMethod(handle, javaLang.getName)
        const utf16 = result.$jstring.toUTF16String()
        const str = utf16.toString()
        utf16.release()
        result.$unref()
        return str
    }

}
export class jstring extends jobject {
    private _str: string | undefined

    toString(): string {
        if(this.$handle.isNull() || this._str !== undefined) {
            return this._str || ''
        }
        const utf16 = this.toUTF16String()
        const str = utf16.toString()
        this._str = str
        return str
    }

    [Symbol.toPrimitive](hint: string) {
        if (hint === "string") {
            return `<jstring: ${this.$handle}>[${this.$IndirectRefKind}]`
        }
        return "default"
    }

    toUTF16String(): UTF16JString {
        return new UTF16JString(this)
    }

    toUTF8String(): UTF8JString {
        return new UTF8JString(this)
    }

}
export class jmethodID extends jobject { 
    $getName(): string {
        const handle = this._parent
        const javaLang = JNIEnv.javaLangReflectMethod()
        const result = JNIEnv.CallObjectMethod(handle, javaLang.getName)
        const utf16 = result.$jstring.toUTF16String()
        const str = utf16.toString()
        utf16.release()
        result.$unref()
        return str
    }
    toString(): string { return `<jmethodID: ${this.$handle}>[${this.$IndirectRefKind}]` }
}
export class jboolean extends NativePointerObject {
    toBool(): boolean {
        return this._handle.toInt32() !== 0
    }
    toString(): string { return `<jboolean: ${this.$handle}>` }
}
export class jbyte extends NativePointerObject {
    toByte(): number {
        return this._handle.toInt32()
    }
    toString(): string { return `<jbyte: ${this.$handle}>` }
}
export class jchar extends NativePointerObject {
    toChar(): number {
        return this._handle.toInt32()
    }
    toString(): string { return `<jchar: ${this.$handle}>` }
}
export class jdouble extends NativePointerObject {
    toDouble(): number {
        return Number(this._handle)
    }
    toString(): string { return `<jdouble: ${this.$handle}>` }
}
export class jfloat extends NativePointerObject {
    toFloat(): number {
        return Number(this._handle)
    }
    toString(): string { return `<jfloat: ${this.$handle}>` }
}
export class jint extends NativePointerObject {
    toInt(): number {
        return Number(this._handle)
    }
    toString(): string { return `<jint: ${this.$handle}>` }
}
export class jlong extends NativePointerObject {
    toLong(): number {
        return Number(this._handle)
    }
    toString(): string { return `<jlong: ${this.$handle}>` }
}
export class jshort extends NativePointerObject {
    toShort(): number {
        return Number(this._handle)
    }
    toString(): string { return `<jshort: ${this.$handle}>` }
}
export class jvoid extends NativePointerObject {
    toString(): string { return `<jvoid: ${this.$handle}>` }
}
export class jthrowable extends jobject {
    toString(): string { return `<jthrowable: ${this.$handle}>` }
}



export class jvalue {
    private _handle: NativePointer
    constructor(handle: NativePointer) {
        this._handle = handle
    }

    $index(offset: number): NativePointer {
        return this._handle.add(offset * Process.pointerSize).readPointer()
    }

    jobject(offset: number): jobject {
        return new jobject(this.$index(offset))
    }

    jstring(offset: number): jstring {
        return new jstring(this.$index(offset))
    }
    toString(): string { return `<jvalue: ${this._handle}>` }
}


export abstract class jarray<T> extends NativePointerObject {
    protected readonly _pointerSize: number = Process.pointerSize
    protected readonly _wrapper?: { new(handle: NativePointer): T }
    constructor(handle: NativePointer) {
        super(handle)
    }

    $index(index: number): T {
        return new this._wrapper!(this._handle.add(index * this._pointerSize).readPointer())
    }
}

export class jobjectArray extends jarray<jobject> {
    protected readonly _wrapper: { new(handle: NativePointer): jobject } = jobject
    $index(index: number): jobject {
        return JNIEnv.GetObjectArrayElement(this.$handle, index)
    }
}
export class jbooleanArray extends jarray<jboolean> {
    protected readonly _pointerSize: number = 1
    protected readonly _wrapper: { new(handle: NativePointer): jboolean } = jboolean
}
export class jbyteArray extends jarray<jbyte> {
    protected readonly _pointerSize: number = 1
    protected readonly _wrapper: { new(handle: NativePointer): jbyte } = jbyte
}
export class jcharArray extends jarray<jchar> {
    protected readonly _pointerSize: number = 2
    protected readonly _wrapper: { new(handle: NativePointer): jchar } = jchar
}
export class jdoubleArray extends jarray<jdouble> {
    protected readonly _pointerSize: number = 8
    protected readonly _wrapper: { new(handle: NativePointer): jdouble } = jdouble
}
export class jfloatArray extends jarray<jfloat> {
    protected readonly _pointerSize: number = 4
    protected readonly _wrapper: { new(handle: NativePointer): jfloat } = jfloat
}
export class jintArray extends jarray<jint> {
    protected readonly _pointerSize: number = 4
    protected readonly _wrapper: { new(handle: NativePointer): jint } = jint
}
export class jlongArray extends jarray<jlong> {
    protected readonly _pointerSize: number = 8
    protected readonly _wrapper: { new(handle: NativePointer): jlong } = jlong
}
export class jshortArray extends jarray<jshort> {
    protected readonly _pointerSize: number = 2
    protected readonly _wrapper: { new(handle: NativePointer): jshort } = jshort
}


export function unwrapJvalueArgs(args: jvalue, n: number): (any|NativePointer)[] {
    const list: any[] = []
    for(let i = 0; i < n; i++) {
        list.push(args.$index(i))
    }
    return list
}



// utf16
class UTF16JString {
    protected _length: number | null = null
    protected _jstr: jstring
    protected _str: string | null = null
    protected _cstrPtr: NativePointer = NULL
    protected _released: boolean = false

    protected readonly $getString = JNIEnv.GetStringChars
    protected readonly $readString = (p: NativePointer, len: number)=>p.readUtf16String(len)
    protected readonly $releaser = JNIEnv.ReleaseStringChars

    constructor(jstr: jstring) {
        this._jstr = jstr
    }

    get $length(): number { 
        return this._length !== null ? this._length : (this._length = JNIEnv.GetStringLength(this._jstr).toInt())
    }

    toString(): string {
        if(this._str !== null) {
            return this._str
        }
        const cstr = this.$getString(this._jstr)
        this._cstrPtr = cstr
        this._str = this.$readString(cstr, this.$length)
        return this._str || '' 
    }

    isNull(): boolean {
        return this._jstr?.$handle.isNull()
    }

    release(){
        if(this._cstrPtr.isNull()) {
            return false
        }
        return this._released ? true : (
            this._released = true, 
            this.$releaser(this._jstr, this._cstrPtr),
            true
        )
    }
}

// utf8
class UTF8JString extends UTF16JString {
    protected readonly $getString = JNIEnv.GetStringUTFChars
    protected readonly $readString = (p: NativePointer, len: number)=>p.readUtf8String(len)
    protected readonly $releaser = JNIEnv.ReleaseStringUTFChars

    get $length(): number { 
        return this._length !== null ? this._length : (this._length = JNIEnv.GetStringUTFLength(this._jstr).toInt())
    }

    toString(): string {
        return (this._str !== null ? this._str : (this._str = this._jstr.$handle.readUtf16String(this.$length))) || ''
    }
}


interface javaLangClass {
    readonly handle: NativePointer
    readonly getName: NativePointer
    readonly getSimpleName: NativePointer
    readonly getGenericSuperclass: NativePointer
    readonly getDeclaredConstructors: NativePointer
    readonly getDeclaredMethods: NativePointer
    readonly getDeclaredFields: NativePointer
    readonly isArray: NativePointer
    readonly isPrimitive: NativePointer
    readonly isInterface: NativePointer
    readonly getComponentType: NativePointer
}

interface javaLangObject {
    readonly handle: NativePointer
    readonly toString: NativePointer
    readonly getClass: NativePointer
}

interface javaLangReflectMethod {
    readonly getName: NativePointer
    readonly getGenericParameterTypes: NativePointer
    readonly getParameterTypes: NativePointer
    readonly getReturnType: NativePointer // not set
    readonly getGenericReturnType: NativePointer
    readonly getGenericExceptionTypes: NativePointer
    readonly getModifiers: NativePointer
    readonly isVarArgs: NativePointer
}

interface javaLangReflectField {
    readonly getName: NativePointer
    readonly getType: NativePointer
    readonly getGenericType: NativePointer
    readonly getModifiers: NativePointer
    readonly toString: NativePointer
}

interface javaLangReflectConstructor {
    readonly getGenericParameterTypes: NativePointer
}

interface javaLangReflectTypeVariable {
    readonly handle: NativePointer
    readonly getName: NativePointer
    readonly getBounds: NativePointer
    readonly getGenericDeclaration: NativePointer
}

interface javaLangReflectWildcardType {
    readonly handle: NativePointer
    readonly getLowerBounds: NativePointer
    readonly getUpperBounds: NativePointer
}

interface javaLangReflectGenericArrayType {
    readonly handle: NativePointer
    readonly getGenericComponentType: NativePointer
}

interface javaLangReflectParameterizedType {
    readonly handle: NativePointer
    readonly getActualTypeArguments: NativePointer
    readonly getRawType: NativePointer
    readonly getOwnerType: NativePointer
}

interface javaLangString {
    readonly handle: NativePointer
}


interface JniEnv extends Java.Env {
    javaLangClass(): javaLangClass
    javaLangObject(): javaLangObject
    javaLangReflectMethod(): javaLangReflectMethod
    javaLangReflectField(): javaLangReflectField
    javaLangReflectConstructor(): javaLangReflectConstructor
    javaLangReflectTypeVariable(): javaLangReflectTypeVariable
    javaLangReflectWildcardType(): javaLangReflectWildcardType
    javaLangReflectGenericArrayType(): javaLangReflectGenericArrayType
    javaLangReflectParameterizedType(): javaLangReflectParameterizedType
    javaLangString(): javaLangString
}

function CLZ(val: number): number{
    val = val >>> 0
    return val === 0 ? 32 : 32 - val.toString(2).length
}

function MinimumBitsToStore(value: number): number{
    return (value === 0 ? -1 : (32 - 1 - CLZ(value))) + 1
}

function proxyCallMethod<RetType>(
    env: JniEnvBase,
    offMethod: number,
    constructor: { new(obj: any): RetType } | null = null,
    {
        retType = 'pointer',
        argTypes = ['pointer', 'pointer', 'pointer', 'pointer']
    }: { retType?: string, argTypes?: string[] } = {}
) {
    const method = function (this: Java.Env, impl: AnyFunction, ...args: any[]): RetType {
        return impl(this.handle, ...args)
    }
    return env.$proxy(method, retType, argTypes, offMethod, constructor)
}

function proxyCallNonvirtualMethod<RetType>(
    env: JniEnvBase,
    offMethod: number,
    constructor: { new(obj: any): RetType } | null = null,
    {
        retType = 'pointer',
        argTypes = ['pointer', 'pointer', 'pointer', 'pointer', 'pointer']
    }: { retType?: string, argTypes?: string[] } = {}
) {
    return proxyCallMethod<RetType>(env, offMethod, constructor, { retType, argTypes })
}

const callMethodVariadicArgTypes = ['pointer', 'pointer', 'pointer', '...', 'pointer']
const callNonvirtualMethodVariadictArgTypes = ['pointer', 'pointer', 'pointer', 'pointer', '...', 'pointer']

abstract class JniEnvBase {
    protected static readonly cacheClass: { [key: string]: jclass } = {}  
    private static readonly ptrSize = Process.pointerSize
    static readonly kKindBits = MinimumBitsToStore(IndirectRefKind.kLastKind)
    static readonly kKindMask = (1 << JniEnvBase.kKindBits) - 1

    private readonly _vm?: Java.VM

    constructor(vm?: Java.VM) {
        this._vm = vm
    }

    get $env(): Java.Env {
        return this.$vm.getEnv()
    }

    get $vm(): Java.VM {
        return this._vm ? this._vm : Java.vm
    }

    // JNIEnvExt::
    // [0] *JNINativeInterface
    // [1] Thread * self_
    get $thread(): NativePointer {
        return this.$env.handle.add(JniEnvBase.ptrSize).readPointer()
    }

    $proxy<RetType>(
        wrapFunc: (this: Java.Env, impl: AnyFunction, ...args: any[]) => RetType,
        retType: any, argTypes: any[], index: number,
        constructor: { new(obj: any, opt?: {[key: string]: any}): RetType } | null = null,
        optBuilder?: (...args: any[]) => {[key: string]: any},
    ): ((...args: any[]) => RetType) & { $handle: NativePointer | undefined } {
        let cache: nativeFunc | null = null

        const getCache = () => {
            const env = this.$env
            if (cache === null) {
                const p: NativePointer = env.handle.readPointer()
                const handle = p.add(index * JniEnvBase.ptrSize).readPointer()
                const impl = new NativeFunction(
                    handle,
                    retType, argTypes, nativeFunctionOptions,
                )
                cache = {
                    handle: handle,
                    impl: impl,
                }
            }
            return cache
        }

        const func = (...args: any[]): RetType => {
            const env = this.$env
            const cache = getCache()
            const result = wrapFunc.apply(env, [cache.impl, ...args.map(v => v instanceof NativePointerObject ? v.$handle : v)])
            if (constructor === null) {
                return result
            }
            let opt = {}
            if(optBuilder) {
                opt = optBuilder(...args)
            }
            return new constructor(result, opt)
        }

        Object.defineProperty(func, '$handle', {
            get: function () {
                return getCache()?.handle
            }
        })
        return (func as ((...args: any[]) => RetType) & {
            $handle: NativePointer | undefined
        })
    }

    $symbol<RetType>(
        wrapFunc: (this: Java.Env, impl: AnyFunction, ...args: any[]) => RetType,
        retType: any, argTypes: any[], symbol: string,
        constructor: { new(obj: any): RetType } | null = null,
    ): ((...args: any[]) => RetType) & { $handle: NativePointer | undefined } {


        let cache: nativeFunc | null = null

        const getCache = () => {
            if (cache === null) {
                const find = Java.api.find || ((name) => {
                    const module = Java.api.module
                    let address = module.findExportByName(name)
                    if (address === null) {
                        address = module.findSymbolByName(name)
                    }
                    return address
                })
                const handle = find(symbol)
                if (!handle) {
                    throw `symbol[${symbol}] 不存在于 art/dalvik so中`
                }
                const impl = new NativeFunction(
                    handle,
                    retType, argTypes, nativeFunctionOptions,
                )
                cache = {
                    handle: handle,
                    impl: impl,
                }
            }
            return cache
        }

        const func = (...args: any[]): RetType => {
            const env = this.$env
            const cache = getCache()
            const result = wrapFunc.apply(env, [cache.impl, ...args.map(v => v instanceof NativePointerObject ? v.$handle : v)])
            if (constructor === null) {
                return result
            }
            return new constructor(result)
        }

        Object.defineProperty(func, '$handle', {
            get: function () {
                return getCache()?.handle
            }
        })
        return (func as ((...args: any[]) => RetType) & {
            $handle: NativePointer | undefined
        })
    }


}

abstract class JniEnvCaller extends JniEnvBase {
    constructor(vm?: Java.VM) {
        super(vm)
    }

    // jobject CallObjectMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallObjectMethod = proxyCallMethod(this, JNI_VT.CallObjectMethod, jobject, { argTypes: callMethodVariadicArgTypes })
    // jobject CallObjectMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallObjectMethodV = proxyCallMethod(this, JNI_VT.CallObjectMethodV, jobject)
    // jobject CallObjectMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallObjectMethodA = proxyCallMethod(this, JNI_VT.CallObjectMethodA, jobject)


    // jboolean CallBooleanMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallBooleanMethod = proxyCallMethod(this, JNI_VT.CallBooleanMethod, jboolean, { argTypes: callMethodVariadicArgTypes })
    // jboolean CallBooleanMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallBooleanMethodV = proxyCallMethod(this, JNI_VT.CallBooleanMethodV, jboolean)
    // jboolean CallBooleanMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallBooleanMethodA = proxyCallMethod(this, JNI_VT.CallBooleanMethodA, jboolean)


    // jbyte CallByteMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallByteMethod = proxyCallMethod(this, JNI_VT.CallBooleanMethod, jbyte, { argTypes: callMethodVariadicArgTypes })
    // jbyte CallByteMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallByteMethodV = proxyCallMethod(this, JNI_VT.CallByteMethodV, jbyte)
    // jbyte CallByteMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallByteMethodA = proxyCallMethod(this, JNI_VT.CallByteMethodA, jbyte)


    // jchar CallCharMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallCharMethod = proxyCallMethod(this, JNI_VT.CallCharMethod, jchar, { argTypes: callMethodVariadicArgTypes })
    // jchar CallCharMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallCharMethodV = proxyCallMethod(this, JNI_VT.CallCharMethodV, jchar)
    // jchar CallCharMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallCharMethodA = proxyCallMethod(this, JNI_VT.CallCharMethodA, jchar)



    // jshort CallShortMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallShortMethod = proxyCallMethod(this, JNI_VT.CallShortMethod, jshort, { argTypes: callMethodVariadicArgTypes })
    // jshort CallShortMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallShortMethodV = proxyCallMethod(this, JNI_VT.CallShortMethodV, jshort)
    // jshort CallShortMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallShortMethodA = proxyCallMethod(this, JNI_VT.CallShortMethodA, jshort)


    // jint CallIntMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallIntMethod = proxyCallMethod(this, JNI_VT.CallIntMethod, jint, { argTypes: callMethodVariadicArgTypes })
    // jint CallIntMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallIntMethodV = proxyCallMethod(this, JNI_VT.CallIntMethodV, jint)
    // jint CallIntMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallIntMethodA = proxyCallMethod(this, JNI_VT.CallIntMethodA, jint)


    // jlong CallLongMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallLongMethod = proxyCallMethod(this, JNI_VT.CallLongMethod, jint, { argTypes: callMethodVariadicArgTypes })
    // jlong CallLongMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallLongMethodV = proxyCallMethod(this, JNI_VT.CallLongMethodV, jint)
    // jlong CallLongMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallLongMethodA = proxyCallMethod(this, JNI_VT.CallLongMethodA, jint)


    // jfloat CallFloatMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallFloatMethod = proxyCallMethod(this, JNI_VT.CallFloatMethod, jfloat, { argTypes: callMethodVariadicArgTypes })
    // jfloat CallFloatMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallFloatMethodV = proxyCallMethod(this, JNI_VT.CallFloatMethodV, jfloat)
    // jfloat CallFloatMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallFloatMethodA = proxyCallMethod(this, JNI_VT.CallFloatMethodA, jfloat)

    
    // jdouble CallDoubleMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallDoubleMethod = proxyCallMethod(this, JNI_VT.CallDoubleMethod, jdouble, { argTypes: callMethodVariadicArgTypes })
    // jdouble CallDoubleMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallDoubleMethodV = proxyCallMethod(this, JNI_VT.CallDoubleMethodV, jdouble)
    // jdouble CallDoubleMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallDoubleMethodA = proxyCallMethod(this, JNI_VT.CallDoubleMethodA, jdouble)


    // void CallVoidMethod(JNIEnv* env, jobject obj, jmethodID mid, ...)
    readonly CallVoidMethod = proxyCallMethod(this, JNI_VT.CallVoidMethod, jvoid, { argTypes: callMethodVariadicArgTypes })
    // void CallVoidMethodV(JNIEnv* env, jobject obj, jmethodID mid, va_list args)
    readonly CallVoidMethodV = proxyCallMethod(this, JNI_VT.CallVoidMethodV, jvoid)
    // void CallVoidMethodA(JNIEnv* env, jobject obj, jmethodID mid, const jvalue* args)
    readonly CallVoidMethodA = proxyCallMethod(this, JNI_VT.CallVoidMethodA, jvoid)


    // jobject CallNonvirtualObjectMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualObjectMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualObjectMethod, jobject, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jobject CallNonvirtualObjectMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualObjectMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualObjectMethodV, jobject)
    // jobject CallNonvirtualObjectMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualObjectMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualObjectMethodA, jobject)


    // jboolean CallNonvirtualBooleanMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualBooleanMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualBooleanMethod, jboolean, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jboolean CallNonvirtualBooleanMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualBooleanMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualBooleanMethodV, jboolean)
    // jboolean CallNonvirtualBooleanMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualBooleanMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualBooleanMethodA, jboolean)


    // jbyte CallNonvirtualByteMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualByteMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualByteMethod, jbyte, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jbyte CallNonvirtualByteMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualByteMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualByteMethodV, jbyte)
    // jbyte CallNonvirtualByteMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualByteMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualByteMethodA, jbyte)


    // jchar CallNonvirtualCharMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualCharMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualCharMethod, jchar, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jchar CallNonvirtualCharMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualCharMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualCharMethodV, jchar)
    // jchar CallNonvirtualCharMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualCharMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualCharMethodA, jchar)


    // jshort CallNonvirtualShortMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualShortMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualShortMethod, jshort, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jshort CallNonvirtualShortMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualShortMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualShortMethodV, jshort)
    // jshort CallNonvirtualShortMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualShortMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualShortMethodA, jshort)


    // jint CallNonvirtualIntMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualIntMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualIntMethod, jint, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jint CallNonvirtualIntMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualIntMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualIntMethodV, jint)
    // jint CallNonvirtualIntMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualIntMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualIntMethodA, jint)


    // jlong CallNonvirtualLongMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualLongMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualLongMethod, jlong, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jlong CallNonvirtualLongMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualLongMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualLongMethodV, jlong)
    // jlong CallNonvirtualLongMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualLongMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualLongMethodA, jlong)


    // jfloat CallNonvirtualFloatMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualFloatMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualFloatMethod, jfloat, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jfloat CallNonvirtualFloatMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualFloatMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualFloatMethodV, jfloat)
    // jfloat CallNonvirtualFloatMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualFloatMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualFloatMethodA, jfloat)


    // jdouble CallNonvirtualDoubleMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualDoubleMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualDoubleMethod, jdouble, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jdouble CallNonvirtualDoubleMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualDoubleMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualDoubleMethodV, jdouble)
    // jdouble CallNonvirtualDoubleMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualDoubleMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualDoubleMethodA, jdouble)


    // jvoid CallNonvirtualVoidMethod(JNIEnv* env, jobject obj, jclass, jmethodID mid, ...)
    readonly CallNonvirtualVoidMethod = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualVoidMethod, jvoid, { argTypes: callNonvirtualMethodVariadictArgTypes })
    // jvoid CallNonvirtualVoidMethodV(JNIEnv* env, jobject obj, jclass, jmethodID mid, va_list args)
    readonly CallNonvirtualVoidMethodV = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualVoidMethodV, jvoid)
    // jvoid CallNonvirtualVoidMethodA(JNIEnv* env, jobject obj, jclass, jmethodID mid, const jvalue* args)
    readonly CallNonvirtualVoidMethodA = proxyCallNonvirtualMethod(this, JNI_VT.CallNonvirtualVoidMethodA, jvoid)


    // jobject CallStaticObjectMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticObjectMethod = proxyCallMethod(this, JNI_VT.CallStaticObjectMethod, jobject, { argTypes: callMethodVariadicArgTypes })
    // jobject CallStaticObjectMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticObjectMethodV = proxyCallMethod(this, JNI_VT.CallStaticObjectMethodV, jobject)
    // jobject CallStaticObjectMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticObjectMethodA = proxyCallMethod(this, JNI_VT.CallStaticObjectMethodA, jobject)


    // jboolean CallStaticBooleanMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticBooleanMethod = proxyCallMethod(this, JNI_VT.CallStaticBooleanMethod, jboolean, { argTypes: callMethodVariadicArgTypes })
    // jboolean CallStaticBooleanMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticBooleanMethodV = proxyCallMethod(this, JNI_VT.CallStaticBooleanMethodV, jboolean)
    // jboolean CallStaticBooleanMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticBooleanMethodA = proxyCallMethod(this, JNI_VT.CallStaticBooleanMethodA, jboolean)


    // jbyte CallStaticByteMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticByteMethod = proxyCallMethod(this, JNI_VT.CallStaticByteMethod, jbyte, { argTypes: callMethodVariadicArgTypes })
    // jbyte CallStaticByteMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticByteMethodV = proxyCallMethod(this, JNI_VT.CallStaticByteMethodV, jbyte)
    // jbyte CallStaticByteMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticByteMethodA = proxyCallMethod(this, JNI_VT.CallStaticByteMethodA, jbyte)


    // jchar CallStaticCharMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticCharMethod = proxyCallMethod(this, JNI_VT.CallStaticCharMethod, jchar, { argTypes: callMethodVariadicArgTypes })
    // jchar CallStaticCharMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticCharMethodV = proxyCallMethod(this, JNI_VT.CallStaticCharMethodV, jchar)
    // jchar CallStaticCharMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticCharMethodA = proxyCallMethod(this, JNI_VT.CallStaticCharMethodA, jchar)



    // jshort CallStaticShortMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticShortMethod = proxyCallMethod(this, JNI_VT.CallStaticShortMethod, jshort, { argTypes: callMethodVariadicArgTypes })
    // jshort CallStaticShortMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticShortMethodV = proxyCallMethod(this, JNI_VT.CallStaticShortMethodV, jshort)
    // jshort CallStaticShortMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticShortMethodA = proxyCallMethod(this, JNI_VT.CallStaticShortMethodA, jshort)


    // jint CallStaticIntMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticIntMethod = proxyCallMethod(this, JNI_VT.CallStaticIntMethod, jint, { argTypes: callMethodVariadicArgTypes })
    // jint CallStaticIntMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticIntMethodV = proxyCallMethod(this, JNI_VT.CallStaticIntMethodV, jint)
    // jint CallStaticIntMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticIntMethodA = proxyCallMethod(this, JNI_VT.CallStaticIntMethodA, jint)


    // jlong CallStaticLongMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticLongMethod = proxyCallMethod(this, JNI_VT.CallStaticLongMethod, jint, { argTypes: callMethodVariadicArgTypes })
    // jlong CallStaticLongMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticLongMethodV = proxyCallMethod(this, JNI_VT.CallStaticLongMethodV, jint)
    // jlong CallStaticLongMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticLongMethodA = proxyCallMethod(this, JNI_VT.CallStaticLongMethodA, jint)


    // jfloat CallStaticFloatMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticFloatMethod = proxyCallMethod(this, JNI_VT.CallStaticFloatMethod, jfloat, { argTypes: callMethodVariadicArgTypes })
    // jfloat CallStaticFloatMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticFloatMethodV = proxyCallMethod(this, JNI_VT.CallStaticFloatMethodV, jfloat)
    // jfloat CallStaticFloatMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticFloatMethodA = proxyCallMethod(this, JNI_VT.CallStaticFloatMethodA, jfloat)

    
    // jdouble CallStaticDoubleMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticDoubleMethod = proxyCallMethod(this, JNI_VT.CallStaticDoubleMethod, jdouble, { argTypes: callMethodVariadicArgTypes })
    // jdouble CallStaticDoubleMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticDoubleMethodV = proxyCallMethod(this, JNI_VT.CallStaticDoubleMethodV, jdouble)
    // jdouble CallStaticDoubleMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticDoubleMethodA = proxyCallMethod(this, JNI_VT.CallStaticDoubleMethodA, jdouble)


    // void CallStaticVoidMethod(JNIEnv* env, jclass, jmethodID mid, ...)
    readonly CallStaticVoidMethod = proxyCallMethod(this, JNI_VT.CallStaticVoidMethod, jvoid, { argTypes: callMethodVariadicArgTypes })
    // void CallStaticVoidMethodV(JNIEnv* env, jclass, jmethodID mid, va_list args)
    readonly CallStaticVoidMethodV = proxyCallMethod(this, JNI_VT.CallStaticVoidMethodV, jvoid)
    // void CallStaticVoidMethodA(JNIEnv* env, jclass, jmethodID mid, const jvalue* args)
    readonly CallStaticVoidMethodA = proxyCallMethod(this, JNI_VT.CallStaticVoidMethodA, jvoid)

    // jfieldID GetFieldID(JNIEnv* env, jclass java_class, const char* name, const char* sig)
    readonly GetFieldID = this.$proxy(function (impl: AnyFunction, java_class: any, name: string, sig: string): jobject {
        return impl(this.handle, java_class, Memory.allocUtf8String(name), Memory.allocUtf8String(sig))
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'], JNI_VT.GetFieldID, jobject)

    // jfieldID GetStaticFieldID(JNIEnv* env, jclass java_class, const char* name, const char* sig)
    readonly GetStaticFieldID = this.$proxy(function (impl: AnyFunction, java_class: any, name: string, sig: string): jobject {
        return impl(this.handle, java_class, Memory.allocUtf8String(name), Memory.allocUtf8String(sig))
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'], JNI_VT.GetStaticFieldID, jobject)

    // jobject GetObjectField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetObjectField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jobject {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetObjectField, jobject)

    // jboolean GetBooleanField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetBooleanField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jboolean {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetBooleanField, jboolean)

    // jbyte GetByteField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetByteField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jbyte {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetByteField, jbyte)

    // jchar GetCharField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetCharField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jchar {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetCharField, jchar)

    // jshort GetShortField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetShortField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jshort {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetShortField, jshort)

    // jint GetIntField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetIntField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jint {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetIntField, jint)

    // jlong GetLongField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetLongField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jlong {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetLongField, jlong)

    // jfloat GetFloatField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetFloatField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jfloat {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetFloatField, jfloat)

    // jdouble GetDoubleField(JNIEnv* env, jobject obj, jfieldID fid)
    readonly GetDoubleField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jdouble {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetDoubleField, jdouble)

    // jobject GetStaticObjectField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticObjectField = this.$proxy(function (impl: AnyFunction, cls: any, fid: any): jobject {
        return impl(this.handle, cls, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticObjectField, jobject)

    // jboolean GetStaticBooleanField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticBooleanField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jboolean {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticBooleanField, jboolean)

    // jbyte GetStaticByteField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticByteField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jbyte {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticByteField, jbyte)

    // jchar GetStaticCharField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticCharField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jchar {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticCharField, jchar)

    // jshort GetStaticShortField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticShortField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jshort {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticShortField, jshort)

    // jint GetStaticIntField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticIntField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jint {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticIntField, jint)

    // jlong GetStaticLongField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticLongField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jlong {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticLongField, jlong)

    // jfloat GetStaticFloatField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticFloatField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jfloat {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticFloatField, jfloat)

    // jdouble GetStaticDoubleField(JNIEnv* env, jclass, jfieldID fid)
    readonly GetStaticDoubleField = this.$proxy(function (impl: AnyFunction, obj: any, fid: any): jdouble {
        return impl(this.handle, obj, fid)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStaticDoubleField, jdouble)


    // static jclass FindClass(JNIEnv* env, const char* name)
    readonly FindClass = this.$proxy(function (impl: AnyFunction, name: string): jclass {
        const result = impl(this.handle, Memory.allocUtf8String(name))
        this.throwIfExceptionPending()
        return result
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.FindClass, jclass)

    // jobject ToReflectedMethod(jclass cls, jmethodID methodID, jboolean isStatic)
    readonly ToReflectedMethod = this.$proxy(function (impl: AnyFunction, klass: any, methodId: any, isStatic: boolean): jobject {
        return impl(this.handle, klass, methodId, isStatic ? 1 : 0)
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'uint8'], JNI_VT.ToReflectedMethod, jobject, ($0, $1, isStatic)=>({isStatic}))

    // jclass GetSuperclass(JNIEnv* env, jclass java_class)
    readonly GetSuperclass = this.$proxy(function (impl: AnyFunction, java_class: any): jclass {
        return impl(this.handle, java_class)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.GetSuperclass, jclass)

    // jobject NewObject(JNIEnv* env, jclass java_class, jmethodID mid, ...)
    readonly NewObject = this.$proxy(function (impl: AnyFunction, java_class: any, mid: any, ...args: any): jobject {
        return impl(this.handle, java_class, mid, ...args)
    }, 'pointer', ['pointer', 'pointer', 'pointer', '...', 'pointer'], JNI_VT.NewObject, jobject)

    // jobject NewObjectV(JNIEnv* env, jclass java_class, jmethodID mid, va_list args)
    readonly NewObjectV = this.$proxy(function (impl: AnyFunction, java_class: any, mid: any, args: any): jobject {
        return impl(this.handle, java_class, mid, args)
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'], JNI_VT.NewObjectV, jobject)

    // jobject NewObjectA(JNIEnv* env, jclass java_class, jmethodID mid, const jvalue* args)
    readonly NewObjectA = this.$proxy(function (impl: AnyFunction, java_class: any, mid: any, args: any): jobject {
        return impl(this.handle, java_class, mid, args)
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'], JNI_VT.NewObjectA, jobject)

    // jclass GetObjectClass(jobject obj)
    readonly GetObjectClass = this.$proxy(function (impl: AnyFunction, obj: any): jclass {
        return impl(this.handle, obj)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.GetObjectClass, jclass)

    // jmethodID GetMethodID(jclass clazz, const char *name, const char *sig)
    readonly GetMethodID = this.$proxy(function (impl: AnyFunction, klass: any, name: string, sig: string): jmethodID {
        return impl(this.handle, klass, Memory.allocUtf8String(name), Memory.allocUtf8String(sig))
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'], JNI_VT.GetMethodID, jmethodID)

    // static jmethodID GetStaticMethodID(JNIEnv* env, jclass java_class, const char* name, const char* sig)
    readonly GetStaticMethodID = this.$proxy(function (impl: AnyFunction, java_class: any, name: string, sig: string): jmethodID {
        return impl(this.handle, java_class, Memory.allocUtf8String(name), Memory.allocUtf8String(sig))
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'], JNI_VT.GetStaticMethodID, jmethodID)


    // static const jchar* GetStringChars(JNIEnv* env, jstring java_string, jboolean* is_copy)
    readonly GetStringChars = this.$proxy(function (impl: AnyFunction, str: any): NativePointer {
        return impl(this.handle, str, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStringChars, NativePointer)

    // jsize GetStringLength(JNIEnv* env, jstring java_string)
    readonly GetStringLength = this.$proxy(function (impl: AnyFunction, java_string: any): jint {
        return impl(this.handle, java_string)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.GetStringLength, jint)


    // void ReleaseStringChars(JNIEnv* env, jstring java_string, const jchar* chars)
    readonly ReleaseStringChars = this.$proxy(function (impl: AnyFunction, java_string: any, chars: any): void {
        return impl(this.handle, java_string, chars)
    }, 'void', ['pointer', 'pointer', 'pointer'], JNI_VT.ReleaseStringChars)
    

    // const char* GetStringUTFChars(jstring str, jboolean *isCopy)
    readonly GetStringUTFChars = this.$proxy(function (impl: AnyFunction, str: any): NativePointer {
        return impl(this.handle, str, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStringUTFChars, NativePointer)

    // jsize GetStringUTFLength(JNIEnv* env, jstring java_string)
    readonly GetStringUTFLength = this.$proxy(function (impl: AnyFunction, java_string: any): jint {
        return impl(this.handle, java_string)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.GetStringUTFLength, jint)


    // void ReleaseStringUTFChars(JNIEnv*, jstring, const char* chars)
    readonly ReleaseStringUTFChars = this.$proxy(function (impl: AnyFunction, chars: any): void {
        return impl(this.handle, chars)
    }, 'void', ['pointer', 'pointer'], JNI_VT.ReleaseStringUTFChars)

    // jsize GetArrayLength(JNIEnv* env, jarray java_array)
    readonly GetArrayLength = this.$proxy(function (impl: AnyFunction, java_array: any): jint {
        return impl(this.handle, java_array)
    }, 'int', ['pointer', 'pointer'], JNI_VT.GetArrayLength, jint)


    // jobject GetObjectArrayElement(JNIEnv* env, jobjectArray java_array, jsize index)
    readonly GetObjectArrayElement = this.$proxy(function (impl: AnyFunction, java_array: any, index: number): jobject {
        return impl(this.handle, java_array, index)
    }, 'pointer', ['pointer', 'pointer', 'int'], JNI_VT.GetObjectArrayElement, jobject)

    makeObjectArrayElements(java_array: NativePointer): jobjectArray {
        return new jobjectArray(java_array)
    }

    // jboolean* GetBooleanArrayElements(JNIEnv* env, jbooleanArray array, jboolean* is_copy)
    readonly GetBooleanArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jbooleanArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetBooleanArrayElements, jbooleanArray)

    // jbyte* GetByteArrayElements(JNIEnv* env, jbyteArray array, jboolean* is_copy)
    readonly GetByteArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jbyteArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetByteArrayElements, jbyteArray)

    // jchar* GetCharArrayElements(JNIEnv* env, jcharArray array, jboolean* is_copy)
    readonly GetCharArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jcharArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetCharArrayElements, jcharArray)

    // jdouble* GetDoubleArrayElements(JNIEnv* env, jdoubleArray array, jboolean* is_copy)
    readonly GetDoubleArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jdoubleArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetDoubleArrayElements, jdoubleArray)

    // jfloat* GetFloatArrayElements(JNIEnv* env, jfloatArray array, jboolean* is_copy)
    readonly GetFloatArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jfloatArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetFloatArrayElements, jfloatArray)

    // jint* GetIntArrayElements(JNIEnv* env, jintArray array, jboolean* is_copy)
    readonly GetIntArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jintArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetIntArrayElements, jintArray)

    // jlong* GetLongArrayElements(JNIEnv* env, jlongArray array, jboolean* is_copy)
    readonly GetLongArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jlongArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetLongArrayElements, jlongArray)

    // jshort* GetShortArrayElements(JNIEnv* env, jshortArray array, jboolean* is_copy)
    readonly GetShortArrayElements = this.$proxy(function (impl: AnyFunction, java_array: any): jshortArray {
        return impl(this.handle, java_array, NULL)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetShortArrayElements, jshortArray)


    // void ReleaseBooleanArrayElements(JNIEnv* env, jbooleanArray array, jboolean* elements, jint mode)
    readonly ReleaseBooleanArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseBooleanArrayElements)

    // void ReleaseByteArrayElements(JNIEnv* env, jbyteArray array, jbyte* elements, jint mode)
    readonly ReleaseByteArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseByteArrayElements)

    // void ReleaseCharArrayElements(JNIEnv* env, jcharArray array, jchar* elements, jint mode)
    readonly ReleaseCharArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseCharArrayElements)

    // void ReleaseFloatArrayElements(JNIEnv* env, jfloatArray array, jfloat* elements, jint mode)
    readonly ReleaseFloatArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseFloatArrayElements)

    // void ReleaseDoubleArrayElements(JNIEnv* env, jdoubleArray array, jdouble* elements, jint mode)
    readonly ReleaseDoubleArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseDoubleArrayElements)

    // void ReleaseIntArrayElements(JNIEnv* env, jintArray array, jint* elements, jint mode)
    readonly ReleaseIntArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseIntArrayElements)

    // void ReleaseLongArrayElements(JNIEnv* env, jlongArray array, jlong* elements, jint mode)
    readonly ReleaseLongArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseLongArrayElements)

    // void ReleaseShortArrayElements(JNIEnv* env, jshortArray array, jshort* elements, jint mode)
    readonly ReleaseShortArrayElements = this.$proxy(function (impl: AnyFunction, array: any, elements: any, mode: number): void {
        return impl(this.handle, array, elements, mode)
    }, 'void', ['pointer', 'pointer', 'pointer', 'int'], JNI_VT.ReleaseShortArrayElements)



    // static const jchar* GetStringCritical(JNIEnv* env, jstring java_string, jboolean* is_copy)
    readonly GetStringCritical = this.$proxy(function (impl: AnyFunction, str: any): string {
        return impl(this.handle, str, NULL).readCString()
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.GetStringCritical)

    // jint Throw(JNIEnv* env, jthrowable java_exception)
    readonly Throw = this.$proxy(function (impl: AnyFunction, java_exception: any): jint {
        return impl(this.handle, java_exception)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.Throw, jint)

    // jint ThrowNew(JNIEnv* env, jclass c, const char* msg)
    readonly ThrowNew = this.$proxy(function (impl: AnyFunction, c: any, msg: string): jint {
        const cMsg = Memory.allocUtf8String(msg)
        help.$error(`[ThrowNew]c[${c}], msg[${msg}]`)
        return impl(this.handle, c, cMsg)
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.ThrowNew, jint)

    // jthrowable ExceptionOccurred(JNIEnv* env)
    readonly ExceptionOccurred = this.$proxy(function (impl: AnyFunction): jthrowable {
        return impl(this.handle)
    }, 'pointer', ['pointer'], JNI_VT.ExceptionOccurred, jthrowable)

    // void ExceptionDescribe(JNIEnv* env)
    readonly ExceptionDescribe = this.$proxy(function (impl: AnyFunction): void {
        return impl(this.handle)
    }, 'void', ['pointer'], JNI_VT.ExceptionDescribe)

    // void ExceptionClear(JNIEnv* env)
    readonly ExceptionClear = this.$proxy(function (impl: AnyFunction): void {
        return impl(this.handle)
    }, 'void', ['pointer'], JNI_VT.ExceptionClear)

    // jboolean ExceptionCheck(JNIEnv* env)
    readonly ExceptionCheck = this.$proxy(function (impl: AnyFunction): boolean {
        return impl(this.handle).toUInt32() != 0
    }, 'pointer', ['pointer'], JNI_VT.ExceptionCheck)
    
    // void FatalError(JNIEnv*, const char* msg)
    readonly FatalError = this.$proxy(function (impl: AnyFunction, msg: string): void {
        return impl(this.handle, Memory.allocUtf8String(msg))
    }, 'pointer', ['pointer'], JNI_VT.FatalError)

    // jint PushLocalFrame(JNIEnv* env, jint capacity)
    readonly PushLocalFrame = this.$proxy(function (impl: AnyFunction, capacity: number): jint {
        return impl(this.handle, capacity)
    }, 'int', ['pointer', 'int'], JNI_VT.PushLocalFrame, jint)

    // jobject PopLocalFrame(JNIEnv* env, jobject java_survivor)
    readonly PopLocalFrame = this.$proxy(function (impl: AnyFunction, java_survivor: NativePointer): jobject {
        return impl(this.handle, java_survivor)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.PopLocalFrame, jobject)

    // static jobject NewGlobalRef(JNIEnv* env, jobject obj)
    readonly NewGlobalRef = this.$proxy(function (impl: AnyFunction, obj: any): jobject {
        return impl(this.handle, obj)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.NewGlobalRef, jobject)

    // static jboolean IsSameObject(JNIEnv* env, jobject obj1, jobject obj2)
    readonly IsSameObject = this.$proxy(function (impl: AnyFunction, obj1: any, obj2: any): boolean {
        return impl(this.handle, obj1, obj2) != 0
    }, 'pointer', ['pointer', 'pointer', 'pointer'], JNI_VT.IsSameObject)

    // jobject JNIEnvExt::NewLocalRef(mirror::Object* obj)
    readonly NewLocalRef = this.$proxy(function (impl: AnyFunction, obj: any): jobject {
        return impl(this.handle, obj)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.NewLocalRef, jobject)


    // static void DeleteGlobalRef(JNIEnv* env, jobject obj)
    readonly DeleteGlobalRef = this.$proxy(function (impl: AnyFunction, obj: any): void {
        impl(this.handle, obj)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.DeleteGlobalRef)
    
    // void DeleteLocalRef(JNIEnv* env, jobject obj)
    readonly DeleteLocalRef = this.$proxy(function (impl: AnyFunction, obj: any): void {
        impl(this.handle, obj)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.DeleteLocalRef)

    // static void DeleteWeakGlobalRef(JNIEnv* env, jweak obj) 
    readonly DeleteWeakGlobalRef = this.$proxy(function (impl: AnyFunction, obj: any): void {
        impl(this.handle, obj)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.DeleteWeakGlobalRef)

    // jint RegisterNatives(JNIEnv* env, jclass java_class, const JNINativeMethod* methods, jint method_count)
    readonly RegisterNatives = this.$proxy(function (impl: AnyFunction, java_class: any, methods: any, method_count: any): jint {
        return impl(this.handle, java_class, methods, method_count)
    }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'], JNI_VT.RegisterNatives, jint)

    // jint UnregisterNatives(JNIEnv* env, jclass java_class)
    readonly UnregisterNatives = this.$proxy(function (impl: AnyFunction, java_class: any): jint {
        return impl(this.handle, java_class)
    }, 'pointer', ['pointer', 'pointer'], JNI_VT.UnregisterNatives, jint)


    // ObjPtr<mirror::Object> JavaVMExt::DecodeGlobal(IndirectRef ref)
    readonly DecodeGlobal = this.$symbol(function (impl: AnyFunction, obj: any): MirrorObject {
        return impl(this.vm.handle, obj)
    }, 'pointer', ['pointer', 'pointer'],
        '_ZN3art9JavaVMExt12DecodeGlobalEPv', MirrorObject,
    )

    // ObjPtr<mirror::Object> Thread::DecodeJObject(jobject obj)
    readonly DecodeJObject = this.$symbol(function (impl: AnyFunction, thread: NativePointer | null = null, obj: any): MirrorObject {
        const th = thread ? thread : getThreadFromEnv(this)
        return impl(th, obj)
    }, 'pointer', ['pointer', 'pointer'], 
        '_ZNK3art6Thread13DecodeJObjectEP8_jobject', MirrorObject,
    )

    // jobject JavaVMExt::AddGlobalRef(Thread* self, ObjPtr<mirror::Object> obj)
    readonly AddGlobalRef = this.$symbol(function (impl: AnyFunction, thread: NativePointer | null = null, obj: any): jobject {
        const th = thread ? thread : getThreadFromEnv(this)
        return impl(this.vm.handle, th, obj)
    }, 'pointer', ['pointer', 'pointer', 'pointer'],
        '_ZN3art9JavaVMExt12AddGlobalRefEPNS_6ThreadENS_6ObjPtrINS_6mirror6ObjectEEE', jobject,
    )

    // IndirectReferenceTable::IndirectReferenceTable(size_t max_count, IndirectRefKind desired_kind, ResizableCapacity resizable, std::string * error_msg)
    readonly IndirectReferenceTable_$new = this.$symbol(function (impl: AnyFunction, self: any, max_count: any, desired_kind: any, resizable: any, error_msg: any): NativePointer {
        return impl(self, max_count, desired_kind, resizable, error_msg)
    }, 'pointer', ['pointer', 'size_t', 'pointer', 'pointer', 'pointer'],
        '_ZN3art22IndirectReferenceTableC2EmNS_15IndirectRefKindENS0_17ResizableCapacityEPNSt3__112basic_stringIcNS3_11char_traitsIcEENS3_9allocatorIcEEEE', NativePointer,
    )

    // IndirectReferenceTable::~IndirectReferenceTable
    readonly IndirectReferenceTable_$del = this.$symbol(function (impl: AnyFunction, self: any): void {
        return impl(self)
    }, 'void', ['pointer'],
        '_ZN3art22IndirectReferenceTableD2Ev',
    )

    // bool IndirectReferenceTable::Resize(size_t new_size, std::string* error_msg)
    readonly IndirectReferenceTable_Resize = this.$symbol(function (impl: AnyFunction, new_size: any, error_msg: any): boolean {
        return impl(new_size, error_msg)
    }, 'bool', ['size_t', 'pointer'],
        '_ZN3art22IndirectReferenceTable6ResizeEmPNSt3__112basic_stringIcNS1_11char_traitsIcEENS1_9allocatorIcEEEE',
    )

}


class JniEnv extends JniEnvCaller {
    private static _javaLangReflectMethod: javaLangReflectMethod

    constructor(vm ?: Java.VM) {
        super(vm)
        const that = this
        return new Proxy(this, {
            get(target: any, prop: string) {
                if (prop in target) {
                    return target[prop as keyof JniEnv]
                }
                const env = that.$vm.getEnv()
                return env[prop as keyof Java.Env]
            }
        })
    }

    $clone(): JniEnv {
        return new JniEnv(this.$vm)
    }

    javaLangReflectMethod(): javaLangReflectMethod {
        if (!JniEnv._javaLangReflectMethod) {
            const cache = this.$env.javaLangReflectMethod()
            // patch
            const jcls = this.FindClass('java/lang/reflect/Method')
            const methodID = this.GetMethodID(jcls, 'getReturnType', '()Ljava/lang/Class;')
            cache.getReturnType = methodID
            JniEnv._javaLangReflectMethod = cache
            jcls.$unref()
        }
        return JniEnv._javaLangReflectMethod
    }

}

export const JNIEnv = new JniEnv()


setGlobalProperties({
    'JNIEnv': JNIEnv,

    'jobject': jobject,
    'jclass': jclass,
})

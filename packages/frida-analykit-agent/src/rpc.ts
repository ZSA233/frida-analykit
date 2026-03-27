import { Java, ObjC, Swift } from "./bridges.js"
import { JNIEnv } from "./jni/env.js"
import { RPCMsgType } from "./message.js"
import { SSLTools } from "./net/ssl.js"
import { help } from "./helper.js"
import { Libssl } from "./lib/libssl.js"
import { proc } from "./process.js"
import { ElfTools } from "./elf/tools.js"

const _BASE_CONTEXT = {
    Java,
    Process,
    Module,
    Memory,
    ObjC,
    Swift,
    File,
    hexdump,
    ApiResolver,
    Arm64Relocator,
    Arm64Writer,
    Stalker,
    Thread,
    Interceptor,
    ModuleMap,
    Frida,
    Script,
    Backtracer,
    UInt64,
    Int64,
    Worker,

    help,
    proc,
    JNIEnv,
    SSLTools,
    ElfTools,
    Libssl,

    Object, Array, String, Number, Boolean, Symbol, BigInt, Function,
    Math, Date, RegExp, Map, Set, WeakMap, WeakSet,
    Error, TypeError, SyntaxError,
    JSON, console,
    isNaN, isFinite, parseInt, parseFloat,
    setTimeout, clearTimeout, setInterval, clearInterval,
    encodeURI, decodeURI, encodeURIComponent, decodeURIComponent,
    Reflect, Proxy,
    

    ArrayBuffer,
    Int8Array,
    Int16Array,
    Int32Array,
    Uint8Array,
    Uint16Array,
    Uint32Array,
    NativePointer,
    NativeFunction,
    NativeCallback,


}


const EVAL_SCOPES: { [key: string]: { [key: string]: any } } = {}
const SCOPE_GETTER_PREFIX = '__get__$$'

let ID_INCR = 0

function gen_id(): string {
    ID_INCR++
    return `${SCOPE_GETTER_PREFIX}${ID_INCR.toString(16)}`
}


function getValueByPath(path: string, bind: boolean = false, root: any = globalThis): any {
    let obj: any = root
    let parent = obj
    for(let key of path.split('/')) {
        parent = obj
        obj = obj[key]
    }
    if (parent !== root && typeof (obj) === 'function') {
        obj = bind ? obj.bind(parent) : obj
    }
    return obj
}

function getObj(instIdOrObjChain: string, scopeId: string, bind: boolean = false): any {
    let value: any
    if (instIdOrObjChain.startsWith(SCOPE_GETTER_PREFIX)) {
        const scope = EVAL_SCOPES[scopeId]
        value = getValueByPath(instIdOrObjChain, bind, scope)
    } else {
        value = getValueByPath(instIdOrObjChain, bind)
    }
    return value
}


function enumerateObjProps(instIdOrObjChain: string | Array<string>, scopeId: string) {
    const propsList: Array<{ [key: string]: string }> = []
    const objList: Array<string> = []
    if(typeof(instIdOrObjChain) === 'string') {
        objList.push(instIdOrObjChain)
    }else{
        objList.push(...instIdOrObjChain)
    }
    for (let v of objList) {
        const props: { [key: string]: string } = {}
        let obj
        try{
            obj = getObj(v, scopeId)
        }catch(e){}
        try {
            const numKeys: Array<number> = []
            while (obj && obj !== Object.prototype) {
                for (const key of Reflect.ownKeys(obj)) {
                    if (typeof (key) === 'symbol') {
                        continue
                    }
                    if(/^\d+$/.test(key)){
                        numKeys.push(parseInt(key))
                        continue
                    }
                    let type
                    const desc = Reflect.getOwnPropertyDescriptor(obj, key)
                    if (desc?.get) {
                        type = 'getter'
                    }else if (desc?.set) {
                        type = 'setter'
                    }else{
                        type = typeof(obj[key])
                    }
                    props[String(key)] = type
                }
                obj = Object.getPrototypeOf(obj)
            }
            if(numKeys.length > 0) {
                if(numKeys.length <= 50) {
                    for(let n of numKeys) {
                        const key = n.toString()
                        const desc = Reflect.getOwnPropertyDescriptor(obj, key)
                        let type
                        if (desc?.get) {
                            type = 'getter'
                        } else if (desc?.set) {
                            type = 'setter'
                        } else {
                            type = typeof (obj[key])
                        }
                        props[String(key)] = type
                    }
                }else{
                    const minN: number = Math.min(...numKeys)
                    const maxN: number = Math.max(...numKeys)
                    props[`[${minN}:${maxN+1}]`] = 'index'
                }
            }
        } catch (e) {
        }

        propsList.push(props)
    }
    return {
        type: RPCMsgType.ENUMERATE_OBJ_PROPS,
        data: {
            props: propsList,
        },
    }
}


function iterScopeGet(v: any, scopeId: string, bind: boolean = false): any {
    switch(typeof(v)) {
        case 'string':
            if (v.startsWith(SCOPE_GETTER_PREFIX)) {
                return getObj(v, scopeId, bind)
            }
            break
        case 'object':
            const nv: { [key: string]: any } = {}
            for(const [kk, vv] of Object.entries(v)) {
                nv[kk] = iterScopeGet(vv, scopeId, bind)
            }
            return nv
    }
    return v
}


function scopeCall(instIdOrObjChain: string, args: Array<any>, scopeId: string){
    const obj = getObj(instIdOrObjChain, scopeId, true)
    const nargs = args.map(v => {
        return iterScopeGet(v, scopeId, false)
    })
    const result = obj(...nargs)
    const id = gen_id()
    scopeSave(result, id, scopeId)
    return {
        type: RPCMsgType.SCOPE_CALL,
        data: {
            id,
            type: typeof (result),
            result
        }
    }
}

function scopeSave(obj: any, instId: string, scopeId: string) {
    let scope = EVAL_SCOPES[scopeId]
    if (scope === undefined) {
        scope = {}
        EVAL_SCOPES[scopeId] = scope
    }
    scope[instId] = obj
}

function scopeGet(instIdOrObjChain: string, scopeId: string, bind: boolean = false): any {
    const value = getObj(instIdOrObjChain, scopeId, bind)
    return {
        type: RPCMsgType.SCOPE_GET,
        data: {
            value,
        }
    }
}

function scopeClear(scopeId: string) {
    delete (EVAL_SCOPES[scopeId])
}

function scopeDel(instId: string, scopeId: string) {
    const scope = EVAL_SCOPES[scopeId]
    if(scope) {
        delete(scope[instId])
    }
}

function evalWithContext(code: string, context: any = {}){
    const mergeContext = { ..._BASE_CONTEXT, ...context}
    return Function(...Object.keys(mergeContext), code)(...Object.values(mergeContext))
}

function scopeEval(source: string, scopeId: string) {
    const result = evalWithContext(source, EVAL_SCOPES[scopeId] || {})
    const id = gen_id()
    scopeSave(result, id, scopeId)
    return {
        type: RPCMsgType.SCOPE_EVAL,
        data: {
            id,
            type: typeof (result),
            result
        }
    }
}


rpc.exports = {
    enumerateObjProps,
    scopeCall,
    scopeEval,
    scopeClear,
    scopeGet,
    scopeSave,
    scopeDel,
}

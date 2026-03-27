
import { Config, setGlobalProperties } from "../config.js"
import { RPCMsgType } from "../message.js"
import { arrayBuffer2Hex, unwrapArgs } from "../utils/utils.js"
import { ssl_st_structOf, SSL3_RANDOM_SIZE } from "./struct.js"
import { help, NativePointerObject, ProgressNotify } from "../helper.js"
import { Libssl } from "../lib/libssl.js"
import { FuncHelper } from "../func.js"
import { ElfModuleX } from "../elf/module.js"
import { AdrlXref } from "../elf/xref.js"
import { TextEncoder } from "../utils/text_endec.js"
import { Subroutine } from "../elf/verifier.js"


type SSL3_STATE = {
    read_sequence: ArrayBuffer
    cwrite_sequence: ArrayBuffer
    server_random: ArrayBuffer
    client_random: ArrayBuffer
}


interface SSLField {
    method: NativePointer
    config: NativePointer
    version: number
    max_send_fragment: number
    rbio: NativePointer
    wbio: NativePointer
    do_handshake: NativePointer
    s3: SSL3_STATE
    d1: NativePointer
    msg_callback: NativePointer
    msg_callback_arg: NativePointer
    initial_timeout_duration_ms: number
    session: NativePointer
    info_callback: NativePointer
    ctx: NativePointer
    session_ctx: NativePointer
    ex_data: NativePointer
}


interface SSL extends SSLField { }

const HEX_TABLE = '0123456789abcdef'



export type SSLSecretLog = {
    label: string
    client_random: string
    secret: string
}

class SSL extends NativePointerObject {
    constructor(handle: NativePointer) {
        super(handle)
        for (let [field, offseter] of Object.entries(Process.pointerSize === 8 ? ssl_st_structOf.B64 : {})) {
            Object.defineProperty(this, field, {
                value: offseter(this.$handle),
                writable: false,
                enumerable: true,
            })
        }
    }


    static cbb_hex(bytes: ArrayBuffer, in_len: number): string {
        const bs = new Uint8Array(bytes)
        const hex_list: string[] = []
        for (let i = 0; i < in_len; i++) {
            hex_list.push(HEX_TABLE[bs[i] >> 4] + HEX_TABLE[bs[i] & 0xf])
        }
        return hex_list.join('')
    }

    secretlog(label: string, secret: ArrayBuffer, secret_len: number): SSLSecretLog {
        return {
            label,
            client_random: SSL.cbb_hex(this.s3.client_random, SSL3_RANDOM_SIZE),
            secret: SSL.cbb_hex(secret, secret_len),
        }
    }

}



function sendSSLSecret(tag: string, data: { label: string, client_random: string, secret: string }){
    if (Config.OnRPC) {
        help.$send({
            type: RPCMsgType.SSL_SECRET,
            data: {
                tag: tag,
                ...data
            }
        })
    } else {
        const file = help.getLogfile(tag, 'a')
        file.writeLine(`${data.label} ${data.client_random} ${data.secret}`)
        file.flush()
    }
}






export class BoringSSL {
    private mod: ElfModuleX | Module
    constructor(mod: ElfModuleX | Module) {
        this.mod = mod
    }


    static loadFromModule(mod: ElfModuleX | Module){
        return new BoringSSL(mod)
    }

    scanKeylogFunc(
        fullScan: boolean = false, 
        verifier: (p: NativePointer) => NativePointer | null = this.verifyKeylogFunc,
    ): NativePointer[] {
        const prog = new ProgressNotify('BoringSSL::scanKeylogFunc')
        
        const mod = this.mod
        const tryGetSegment = (name: string) => {
            if (mod instanceof ElfModuleX) {
                return mod.getSegment(name)
            }
            return null
        }
        const targetString = 'CLIENT_RANDOM'
        const enc = new TextEncoder()
        const strBuff = enc.encode(targetString).buffer as ArrayBuffer        
        const scanPattern = arrayBuffer2Hex(strBuff) + " 00"
        const targetScanRange = fullScan ? mod : (tryGetSegment('.rodata') || mod)

        prog.notify({
            intro: `开始扫描特征[${targetString}]`,
            modx_name: mod.name,
            modx_base: mod.base,
            modx_size: mod.size,

            scan_base: (targetScanRange ? targetScanRange : mod).base,
            scan_size: (targetScanRange ? targetScanRange : mod).size,
            scan_string: targetString,
            scan_pattern: scanPattern,

            next: 'help.scanMemory'
        })

        // 特征string 扫描
        const stringTargets = help.scanMemory(
            targetScanRange ? targetScanRange : mod,
            scanPattern,
            { limit: 0x10000 }
        )

        prog.notify({
            intro: `捕获目标数[${stringTargets.length}]`,

            targets: stringTargets.map(v => v.address),
        })
        if (!stringTargets.length) {
            return []
        }

        prog.notify({
            targets: stringTargets.map(v => v.address),
        })

        const guessBLs = []

        for (const target of stringTargets) {            
            const adrlScanRange = fullScan ? mod : (tryGetSegment('.text') || mod)
            prog.notify({                
                target: target.address,
                scan_base: adrlScanRange.base,
                scan_size: adrlScanRange.size,
                
                next: 'AdrlXref::scanAdrl'
            })
            
            // adrl 目标引用扫描
            const xref = new AdrlXref(target.address)
            const adrlResults = xref.scanAdrl(adrlScanRange)

            prog.notify({
                intro: `特征[${target.address.sub(mod.base)}]引用关联数[${adrlResults.length}]`,

                results: adrlResults,
            })
            
            for(const adrl of adrlResults) {
                const bls = []
                // bl 函数调用（只考虑第一次bl
                const bl = adrl.scanBL()
                if(bl) {
                    guessBLs.push(bl)
                    bls.push(bl)
                }
                prog.notify({
                    adrl: adrl,
                    bls: bls,
                })
            }
        }

        const guessFuncs = []
        for(const target of guessBLs) {
            const funcPtr = ptr(target.insn.operands[0].value.toString())
            guessFuncs.push(funcPtr)
            prog.notify({
                intro: `从[${target.src.$handle.sub(mod.base)}]猜测目标函数[${funcPtr.sub(mod.base)}]`,

                bl: target,
                func_ptr: funcPtr,
            })
        }
        
        // 进一步验证目标函数
        return guessFuncs.reduce<NativePointer[]>((acc, v) => {
            const p = verifier(v)
            if(p) {
                acc.push(p)
            }
            return acc
        }, [])
    }

    verifyKeylogFunc(p: NativePointer): NativePointer | null {
        const subroutine = Subroutine.loadFromPointer(p)
        // thunk/tail call
        const verifyResult = subroutine.scoreThunk()
        if (verifyResult.score > 50 && verifyResult.eoi) {
            const bInstr = verifyResult.eoi
            switch (bInstr.mnemonic) {
                case 'b':
                    const target = bInstr.operands[0]
                    return ptr(target.value.toString())
                case 'br':
                    // TODO:
                    break
            }
        }
        return p
    }


}



class SSLTools extends NativePointerObject {
    private static _libssl_hook: boolean = false

    static newConsumer(tag: string = 'sslkey.log'): SSLSecretCallbackConsumer {
        return new SSLSecretCallbackConsumer(tag)
    }

    static attachLibsslKeylogFunc(tag: string = 'sslkey.log'){
        if (this._libssl_hook) {
            return true
        }
        const handle = Libssl.SSL_new.$handle
        if (!handle || handle.isNull()) {
            return false
        }
        this._libssl_hook = true
        Interceptor.attach(handle,{
            onEnter(args) {
                const [ctx] = unwrapArgs(args, 1)
                this.ssl_ctx = ctx
            },
            onLeave(retval){
                const ctx = this.ssl_ctx
                Libssl.SSL_CTX_set_keylog_callback(ctx, FuncHelper.SSL_CTX_keylog_callback(
                    Libssl.SSL_CTX_get_keylog_callback(ctx), 
                    (impl: NativeFunction<NativePointer, Array<NativePointer>>, ssl: NativePointer, line: NativePointer) => {
                        const str = line.readCString()
                        if (str !== null) {
                            const sep_list = str.split(' ')
                            if(sep_list.length !== 3) {
                                printErr(`[attachLogSecret] error to parse secret_log[${str}]`)
                            }else{
                                const [label, client_random, secret] = sep_list
                                sendSSLSecret(tag, { label, client_random, secret })
                            }
                        }
                        if(!impl.isNull()) {
                            impl(ssl, line)
                        }
                    }
                ))
            }
        })
        return true
    }

    static attachBoringsslKeylogFunc(options: { mod?: ElfModuleX | Module, libname?: string }){
        let { mod, libname } = options
        if(!mod && !libname) {
            throw new Error(`[attachBoringssl] mod和libname必须要指定一个`)
        }
        const prog = new ProgressNotify('SSLTools::attachBoringsslKeylogFunc')
        if(!mod) {
            mod = Process.getModuleByName(libname!)
        }
        const bor = new BoringSSL(mod)
        const guessList = bor.scanKeylogFunc()
        if(guessList.length != 1) {
            throw new Error(`[attachBoringssl] 扫到的目标不存在或多个[${guessList.length}], 不执行attach。`)
        }
        Interceptor.attach(guessList[0], SSLTools.newConsumer('sslkey.log').Handler())
        prog.log(mod!.name, `ssl_log_secret: ${guessList[0].sub(mod!.base)}`)
    }


}


export class SSLSecretCallbackConsumer {
    private tag: string

    constructor(tag: string) {
        this.tag = tag
    }

    Handler(): ScriptInvocationListenerCallbacks {
        const that = this
        return {
            onEnter(args: InvocationArguments): void {
                const [ssl, label, secret, secret_len] = unwrapArgs(args, 4)
                const handle = new SSL(ssl)
                const len = secret_len.toUInt32()
                const data = handle.secretlog(label.readCString(), secret.readByteArray(len), len)
                sendSSLSecret(that.tag, data)
            },
            onLeave(retval: InvocationReturnValue): void {

            }
        }
    }

}


export { SSLTools }





setGlobalProperties({
    'SSLTools': SSLTools,
    'BoringSSL': BoringSSL,
})
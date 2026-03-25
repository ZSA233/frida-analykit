
import { ElfModuleX, ElfFileFixer } from "../elf/module.js"
import { nativeFunctionOptions } from "../consts.js"


export class Libssl {
    static $modx?: ElfModuleX

    static $getModule(): ElfModuleX {
        if (!this.$modx) {
            let isNewLoad = false
            const libsslModule = Process.findModuleByName('libssl.so') || (isNewLoad = true, Module.load('libssl.so'))
            if (isNewLoad) {
                console.error(`[libssl.so]为新加载module.`)
            }
            this.$modx = new ElfModuleX(
                libsslModule,
                [new ElfFileFixer(libsslModule.path)],
                { symbolScanLimit: 50000 },
            )
        }
        return this.$modx
    }


    static $nativeFunc<RetType extends NativeFunctionReturnType, ArgTypes extends NativeFunctionArgumentType[] | []>(
        symName: string, retType: RetType, argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        const sym = this.$getModule().findSymbol(symName)
        if (!sym || !sym.implPtr) {
            // throw error if call
            const throwFunc = function () {
                throw new Error(`[Libssl] symbol[${symName}] Not Found!`)
            } as any
            throwFunc.$handle = null
            return throwFunc
        }

        const handle = sym.implPtr

        const fn: any = new NativeFunction(
            handle,
            retType, argTypes, nativeFunctionOptions,
        )
        fn.$handle = handle
        return fn
    }

    static $lazyLoadFunc<RetType extends NativeFunctionReturnType, ArgTypes extends NativeFunctionArgumentType[] | []>(
        symName: string, retType: RetType, argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        let func: any = null
        const getFunc = () => {
            if (func === null) { func = this.$nativeFunc(symName, retType, argTypes) }
            return func
        }

        const wrapper = ((...args: any) => {
            return getFunc()(...args)
        }) as any

        Object.defineProperty(wrapper, '$handle', {
            get() { return getFunc().$handle },
        })
        return wrapper
    }



    // // int bssl::ssl_log_secret(const SSL *ssl, const char *label, const uint8_t *secret, size_t secret_len)
    // static readonly ssl_log_secret = this.$lazyLoadFunc(
    //     '_ZN4bssl14ssl_log_secretEPK6ssl_stPKcPKhm', 'bool', ['pointer', 'pointer', 'pointer', 'size_t']
    // )

    // void SSL_CTX_set_keylog_callback(SSL_CTX *ctx, void(*cb)(const SSL *ssl, const char *line))
    static readonly SSL_CTX_set_keylog_callback = this.$lazyLoadFunc(
        'SSL_CTX_set_keylog_callback', 'void', ['pointer', 'pointer']
    )

    // void (*SSL_CTX_get_keylog_callback(const SSL_CTX *ctx))(const SSL *ssl, const char *line)
    static readonly SSL_CTX_get_keylog_callback = this.$lazyLoadFunc(
        'SSL_CTX_get_keylog_callback', 'pointer', ['pointer']
    )

    // int SSL_connect(SSL *ssl)
    static readonly SSL_connect = this.$lazyLoadFunc(
        'SSL_connect', 'int', ['pointer']
    )
    
    // SSL *SSL_new(SSL_CTX *ctx)
    static readonly SSL_new = this.$lazyLoadFunc(
        'SSL_new', 'pointer', ['pointer']
    )

}
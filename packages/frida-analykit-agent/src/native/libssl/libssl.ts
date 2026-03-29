import { setGlobalProperties } from "../../config/index.js"
import { ElfFileFixer, ElfModuleX } from "../../elf/module.js"
import { nativeFunctionOptions } from "../../internal/frida/native-function.js"

export class Libssl {
    static $modx?: ElfModuleX

    static $getModule(): ElfModuleX {
        if (!this.$modx) {
            let isNewLoad = false
            const libsslModule = Process.findModuleByName("libssl.so") || (isNewLoad = true, Module.load("libssl.so"))
            if (isNewLoad) {
                console.error("[libssl.so]为新加载module.")
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
        symName: string,
        retType: RetType,
        argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        const sym = this.$getModule().findSymbol(symName)
        if (!sym || !sym.implPtr) {
            const throwFunc = function () {
                throw new Error(`[Libssl] symbol[${symName}] Not Found!`)
            } as any
            throwFunc.$handle = null
            return throwFunc
        }

        const handle = sym.implPtr
        const fn: any = new NativeFunction(handle, retType, argTypes, nativeFunctionOptions)
        fn.$handle = handle
        return fn
    }

    static $lazyLoadFunc<RetType extends NativeFunctionReturnType, ArgTypes extends NativeFunctionArgumentType[] | []>(
        symName: string,
        retType: RetType,
        argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        let func: any = null
        const getFunc = () => {
            if (func === null) {
                func = this.$nativeFunc(symName, retType, argTypes)
            }
            return func
        }

        const wrapper = ((...args: any) => getFunc()(...args)) as any
        Object.defineProperty(wrapper, "$handle", {
            get() {
                return getFunc().$handle
            },
        })
        return wrapper
    }

    static readonly SSL_CTX_set_keylog_callback = this.$lazyLoadFunc(
        "SSL_CTX_set_keylog_callback",
        "void",
        ["pointer", "pointer"],
    )

    static readonly SSL_CTX_get_keylog_callback = this.$lazyLoadFunc(
        "SSL_CTX_get_keylog_callback",
        "pointer",
        ["pointer"],
    )

    static readonly SSL_connect = this.$lazyLoadFunc("SSL_connect", "int", ["pointer"])
    static readonly SSL_new = this.$lazyLoadFunc("SSL_new", "pointer", ["pointer"])
}

type LibsslClass = typeof Libssl

declare global {
    const Libssl: LibsslClass
}

setGlobalProperties({
    Libssl,
})

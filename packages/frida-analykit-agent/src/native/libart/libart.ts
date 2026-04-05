import { setGlobalProperties } from "../../config/index.js"
import { ElfModuleX } from "../../elf/module.js"
import { ElfFileMetadataPatcher } from "../../elf/internal/file_metadata_patcher.js"
import { nativeFunctionOptions } from "../../internal/frida/native-function.js"

export class Libart {
    static $modx?: ElfModuleX

    static $getModule(): ElfModuleX {
        if (!this.$modx) {
            const libartModule = Process.findModuleByName("libart.so") || Module.load("libart.so")
            this.$modx = new ElfModuleX(
                libartModule,
                [new ElfFileMetadataPatcher(libartModule.path)],
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
        if (!sym?.implPtr) {
            const throwFunc = function () {
                throw new Error(`[Libart] symbol[${symName}] not found`)
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

    static readonly ConvertJavaArrayToDexFiles = this.$lazyLoadFunc(
        "_ZN3artL26ConvertJavaArrayToDexFilesEP7_JNIEnvP8_jobjectRNSt3__16vectorIPKNS_7DexFileENS4_9allocatorIS8_EEEERPKNS_7OatFileE",
        "int",
        ["pointer", "pointer", "pointer", "pointer"],
    )
}

type LibartClass = typeof Libart

declare global {
    const Libart: LibartClass
}

setGlobalProperties({
    Libart,
})

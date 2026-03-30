import { setGlobalProperties } from "../../config/index.js"
import { nativeFunctionOptions } from "../../internal/frida/native-function.js"

function mustType<T>(val: T | null | undefined): T {
    if (!val) {
        throw new Error("val不能为null")
    }
    return val
}

const PROP_VALUE_MAX = 92

export class Libc {
    constructor() {
        return new Proxy(this, {
            get(target: any, prop: string) {
                if (prop in target) {
                    return target[prop]
                }
                if (prop[0] !== "$") {
                    return target["$" + prop]
                }
                return target[prop.substring(1)]
            },
        })
    }

    static readonly $libc = Process.findModuleByName("libc.so") || Module.load("libc.so")

    $lazyLoadFunc<RetType extends NativeFunctionReturnType, ArgTypes extends NativeFunctionArgumentType[] | []>(
        symName: string,
        retType: RetType,
        argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        let func: any = null
        const wrapper = ((...args: any) => {
            if (func === null) {
                func = this.$nativeFunc(symName, retType, argTypes)
            }
            return func(...args)
        }) as any

        Object.defineProperty(wrapper, "$handle", {
            get() {
                if (func === null) {
                    func = this.$nativeFunc(symName, retType, argTypes)
                }
                return func.$handle
            },
            enumerable: true,
        })

        return wrapper
    }

    $nativeFunc<RetType extends NativeFunctionReturnType, ArgTypes extends NativeFunctionArgumentType[] | []>(
        symName: string,
        retType: RetType,
        argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        const handle = mustType(Libc.$libc.findExportByName(symName))
        const fn: any = new NativeFunction(handle, retType, argTypes, nativeFunctionOptions)
        fn.$handle = handle
        return fn
    }

    readonly $readlink = this.$lazyLoadFunc("readlink", "int", ["pointer", "pointer", "size_t"])
    readlink(pathname: string, bufsize: number = 256): string | null {
        const cfdPath = Memory.allocUtf8String(pathname)
        const resolvedPath = Memory.alloc(bufsize)
        const result = this.$readlink(cfdPath, resolvedPath, bufsize)
        return result === -1 ? null : resolvedPath.readCString()
    }

    readonly $opendir = this.$lazyLoadFunc("opendir", "pointer", ["pointer"])
    opendir(path: string): NativePointer {
        return this.$opendir(Memory.allocUtf8String(path))
    }

    readonly $fopen = this.$lazyLoadFunc("fopen", "pointer", ["pointer", "pointer"])
    fopen(pathname: string, mode: string): NativePointer {
        return this.$fopen(Memory.allocUtf8String(pathname), Memory.allocUtf8String(mode))
    }

    readonly fclose = this.$lazyLoadFunc("fclose", "int", ["pointer"])

    readonly $fputs = this.$lazyLoadFunc("fputs", "int", ["pointer", "pointer"])
    fputs(str: string, file: NativePointer): number {
        return this.$fputs(Memory.allocUtf8String(str), file)
    }

    readonly fflush = this.$lazyLoadFunc("fflush", "int", ["pointer"])
    readonly readdir = this.$lazyLoadFunc("readdir", "pointer", ["pointer"])
    readonly closedir = this.$lazyLoadFunc("closedir", "int", ["pointer"])
    readonly fileno = this.$lazyLoadFunc("fileno", "int", ["pointer"])
    readonly pthread_self = this.$lazyLoadFunc("pthread_self", "int64", [])
    readonly getpid = this.$lazyLoadFunc("getpid", "uint", [])
    readonly getppid = this.$lazyLoadFunc("getppid", "uint", [])
    readonly getuid = this.$lazyLoadFunc("getuid", "uint", [])
    readonly gettid = this.$lazyLoadFunc("gettid", "uint", [])

    readonly $clock_gettime = this.$lazyLoadFunc("clock_gettime", "int", ["int", "pointer"])
    clock_gettime(clkId: number): { tv_sec: number, tv_nsec: number } | null {
        const ps = Process.pointerSize
        const tv = Memory.alloc(ps * 2)
        const ret = this.$clock_gettime(clkId, tv)
        if (ret !== 0) {
            return null
        }
        return {
            tv_sec: Number(tv[ps === 8 ? "readU64" : "readU32"]()),
            tv_nsec: Number(tv.add(ps)[ps === 8 ? "readU64" : "readU32"]()),
        }
    }

    readonly $__system_property_get = this.$lazyLoadFunc("__system_property_get", "int", ["pointer", "pointer"])
    __system_property_get(name: string): string {
        const value = Memory.alloc(PROP_VALUE_MAX)
        const ret = this.$__system_property_get(Memory.allocUtf8String(name), value)
        if (ret < 0) {
            console.error(`[__system_property_get] name[${name}] error[${ret}]`)
        }
        return value.readCString(ret) || ""
    }

    readonly $getcwd = this.$lazyLoadFunc("getcwd", "pointer", ["pointer", "size_t"])
    getcwd(): string | null {
        const buffSize = 256
        const buff = Memory.alloc(buffSize)
        return this.$getcwd(buff, buffSize).readCString()
    }
}

export const libc = new Libc()

type LibcClass = typeof Libc

declare global {
    const Libc: LibcClass
}

setGlobalProperties({
    Libc,
})

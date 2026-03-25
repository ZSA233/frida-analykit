import { mustType } from "../utils/utils.js"
import { nativeFunctionOptions } from "../consts.js"


const PROP_VALUE_MAX = 92


export class Libc {
    constructor() {
        return new Proxy(this, {
            get(target: any, prop: string) {
                if (prop in target) {
                    return target[prop];
                }
                if (prop[0] !== '$') {
                    return target['$' + prop]
                } else {
                    return target[prop.substring(1)]
                }
            }
        })
    }

    static readonly $libc = Process.findModuleByName('libc.so') || Module.load('libc.so')


    $lazyLoadFunc<RetType extends NativeFunctionReturnType, ArgTypes extends NativeFunctionArgumentType[] | []>(
        symName: string, retType: RetType, argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        let func: any = null
        const wrapper = ((...args: any) => {
            if (func === null) {
                func = this.$nativeFunc(symName, retType, argTypes)
            }
            const ret = func(...args)
            return ret
        }) as any

        Object.defineProperty(wrapper, '$handle', {
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
        symName: string, retType: RetType, argTypes: ArgTypes,
    ): NativeFunction<GetNativeFunctionReturnValue<RetType>, ResolveVariadic<Extract<GetNativeFunctionArgumentValue<ArgTypes>, unknown[]>>> & { $handle: NativePointer | undefined } {
        const handle = mustType(Libc.$libc.findExportByName(symName))
        const fn: any = new NativeFunction(
            handle,
            retType, argTypes, nativeFunctionOptions,
        )
        fn.$handle = handle 
        return fn
    }

    // ssize_t readlink(const char *pathname, char *buf, size_t bufsiz);
    readonly $readlink = this.$lazyLoadFunc('readlink', 'int', ['pointer', 'pointer', 'size_t'])
    readlink(pathname: string, bufsize: number = 256): string | null {
        const cfdPath = Memory.allocUtf8String(pathname)
        const resolvedPath = Memory.alloc(bufsize)
        const result = this.$readlink(cfdPath, resolvedPath, bufsize)
        let link: string | null = null
        if (result !== -1) {
            link = resolvedPath.readCString()
        }
        return link
    }

    // DIR *opendir(const char *name);
    readonly $opendir = this.$lazyLoadFunc('opendir', 'pointer', ['pointer'])
    opendir(path: string) {
        const cpath = Memory.allocUtf8String(path)
        const dir = this.$opendir(cpath)
        return dir
    }

    // FILE *fopen(const char *pathname, const char *mode);
    readonly $fopen = this.$lazyLoadFunc('fopen', 'pointer', ['pointer', 'pointer'])
    fopen(pathname: string, mode: string): NativePointer {
        return this.$fopen(Memory.allocUtf8String(pathname), Memory.allocUtf8String(mode))
    }

    // int fclose(FILE *stream);
    readonly fclose = this.$lazyLoadFunc('fclose', 'int', ['pointer'])

    // int fputs(const char *str, FILE *stream);
    readonly $fputs = this.$lazyLoadFunc('fputs', 'int', ['pointer', 'pointer'])
    fputs(str: string, file: NativePointer) {
        return this.$fputs(Memory.allocUtf8String(str), file)
    }

    // int fflush(FILE *stream);
    readonly fflush = this.$lazyLoadFunc('fflush', 'int', ['pointer'])

    // struct dirent *readdir(DIR *dirp);
    readonly readdir = this.$lazyLoadFunc('readdir', 'pointer', ['pointer'])

    // int closedir(DIR *dirp);
    readonly closedir = this.$lazyLoadFunc('closedir', 'int', ['pointer'])

    // int fileno(FILE *stream);
    readonly fileno = this.$lazyLoadFunc('fileno', 'int', ['pointer'])

    // pthread_t pthread_self(void);
    readonly pthread_self = this.$lazyLoadFunc('pthread_self', 'int64', [])


    // pid_t getpid(void);
    readonly getpid = this.$lazyLoadFunc('getpid', 'uint', [])

    // uid_t getuid(void);
    readonly getuid = this.$lazyLoadFunc('getuid', 'uint', [])

    // pid_t gettid(void);
    readonly gettid = this.$lazyLoadFunc('gettid', 'uint', [])

    // int clock_gettime(clockid_t clk_id, struct timespec *tp);
    readonly $clock_gettime = this.$lazyLoadFunc('clock_gettime', 'int', ['int', 'pointer'])
    clock_gettime(clk_id: number): {tv_sec: number, tv_nsec: number } | null {
        const ps = Process.pointerSize
        const tv = Memory.alloc(ps * 2)
        const ret = this.$clock_gettime(clk_id, tv)
        if(ret != 0) {
            return null
        }
        return {
            tv_sec: Number(tv[ps === 8 ? 'readU64' : 'readU32']()), 
            tv_nsec: Number(tv.add(ps)[ps === 8 ? 'readU64' : 'readU32']()), 
        }
    }

    // int __system_property_get(const char *name, char *value);
    readonly $__system_property_get = this.$lazyLoadFunc('__system_property_get', 'int', ['pointer', 'pointer'])
    __system_property_get(name: string): string {
        const sdk_version_value = Memory.alloc(PROP_VALUE_MAX)
        const ret = this.$__system_property_get(Memory.allocUtf8String(name), sdk_version_value)
        if(ret < 0) {
            console.error(`[__system_property_get] name[${name}] error[${ret}]`)
        }
        return sdk_version_value.readCString(ret) || ''
    }

    // char *getcwd(char *buf, size_t size);
    readonly $getcwd = this.$lazyLoadFunc('getcwd', 'pointer', ['pointer', 'size_t'])
    getcwd(): string | null {
        const buff_size = 256
        const buff = Memory.alloc(buff_size)
        return this.$getcwd(buff, buff_size).readCString()
    }

}
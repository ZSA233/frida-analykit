import { emitElfSymbolCallLog, readCStringSafe } from "../internal/log.js"
import { ElfSymbolHooks } from "../symbol_hooks.js"
import type { ElfSymbolHookResult } from "../types.js"

type PresetHook = (fn?: AnyFunction) => ElfSymbolHookResult

export type EnhancedElfSymbolHookMethods = {
    dlopen: PresetHook
    dlsym: PresetHook
    dlclose: PresetHook
    dladdr: PresetHook
    dlerror: PresetHook
    dl_iterate_phdr: PresetHook
    abort: PresetHook
    exit: PresetHook
    _exit: PresetHook
    kill: PresetHook
    raise: PresetHook
    getpid: PresetHook
    gettid: PresetHook
    getppid: PresetHook
    ptrace: PresetHook
    prctl: PresetHook
    syscall: PresetHook
    pthread_create: PresetHook
    pthread_self: PresetHook
    pthread_detach: PresetHook
    pthread_join: PresetHook
    mmap: PresetHook
    munmap: PresetHook
    mprotect: PresetHook
    malloc: PresetHook
    calloc: PresetHook
    realloc: PresetHook
    free: PresetHook
    memcpy: PresetHook
    memmove: PresetHook
    memset: PresetHook
    open: PresetHook
    openat: PresetHook
    fopen: PresetHook
    close: PresetHook
    read: PresetHook
    pread: PresetHook
    write: PresetHook
    lseek: PresetHook
    readlink: PresetHook
    __system_property_get: PresetHook
}

export type EnhancedElfSymbolHooks = ElfSymbolHooks & EnhancedElfSymbolHookMethods

function readDlInfo(info: NativePointer) {
    const ps = Process.pointerSize
    return {
        dli_fname: readCStringSafe(info.readPointer()),
        dli_fbase: info.add(ps).readPointer(),
        dli_sname: readCStringSafe(info.add(ps * 2).readPointer()),
        dli_saddr: info.add(ps * 3).readPointer(),
    }
}

function createPresetMethods(hooks: ElfSymbolHooks): EnhancedElfSymbolHookMethods {
    const log = (symbol: string, fields: Record<string, unknown> = {}) => emitElfSymbolCallLog({
        tag: hooks.logTag,
        module: hooks.module,
    }, symbol, fields)

    return {
        dlsym(fn = function (impl: AnyFunction, handle: NativePointer, name: NativePointer) {
            const output = impl(handle, name)
            log("dlsym", { handle, name: readCStringSafe(name), output })
            return output
        }) {
            return hooks.attach("dlsym", fn, "pointer", ["pointer", "pointer"])
        },
        dlopen(fn = function (impl: AnyFunction, file: NativePointer, flags: number) {
            const handle = impl(file, flags)
            log("dlopen", { file: readCStringSafe(file), flags, handle })
            return handle
        }) {
            return hooks.attach("dlopen", fn, "pointer", ["pointer", "int"])
        },
        dlclose(fn = function (impl: AnyFunction, handle: NativePointer) {
            const result = impl(handle)
            log("dlclose", { handle, result })
            return result
        }) {
            return hooks.attach("dlclose", fn, "int", ["pointer"])
        },
        dladdr(fn = function (impl: AnyFunction, address: NativePointer, info: NativePointer) {
            const result = impl(address, info)
            log("dladdr", { address, result, info: info.isNull() ? null : readDlInfo(info) })
            return result
        }) {
            return hooks.attach("dladdr", fn, "int", ["pointer", "pointer"])
        },
        dlerror(fn = function (impl: AnyFunction) {
            const output = impl()
            log("dlerror", { message: readCStringSafe(output) })
            return output
        }) {
            return hooks.attach("dlerror", fn, "pointer", [])
        },
        dl_iterate_phdr(fn = function (impl: AnyFunction, callback: NativePointer, data: NativePointer) {
            const result = impl(callback, data)
            log("dl_iterate_phdr", { callback, data, result })
            return result
        }) {
            return hooks.attach("dl_iterate_phdr", fn, "int", ["pointer", "pointer"])
        },
        abort(fn = function (impl: AnyFunction) {
            log("abort")
            return impl()
        }) {
            return hooks.attach("abort", fn, "void", [])
        },
        exit(fn = function (impl: AnyFunction, status: number) {
            log("exit", { status })
            return impl(status)
        }) {
            return hooks.attach("exit", fn, "void", ["int"])
        },
        _exit(fn = function (impl: AnyFunction, status: number) {
            log("_exit", { status })
            return impl(status)
        }) {
            return hooks.attach("_exit", fn, "void", ["int"])
        },
        kill(fn = function (impl: AnyFunction, pid: number, signal: number) {
            const result = impl(pid, signal)
            log("kill", { pid, signal, result })
            return result
        }) {
            return hooks.attach("kill", fn, "int", ["int", "int"])
        },
        raise(fn = function (impl: AnyFunction, signal: number) {
            const result = impl(signal)
            log("raise", { signal, result })
            return result
        }) {
            return hooks.attach("raise", fn, "int", ["int"])
        },
        getpid(fn = function (impl: AnyFunction) {
            const pid = impl()
            log("getpid", { pid })
            return pid
        }) {
            return hooks.attach("getpid", fn, "uint", [])
        },
        gettid(fn = function (impl: AnyFunction) {
            const tid = impl()
            log("gettid", { tid })
            return tid
        }) {
            return hooks.attach("gettid", fn, "uint", [])
        },
        getppid(fn = function (impl: AnyFunction) {
            const pid = impl()
            log("getppid", { pid })
            return pid
        }) {
            return hooks.attach("getppid", fn, "uint", [])
        },
        ptrace(fn = function (impl: AnyFunction, request: number, pid: number, addr: NativePointer, data: NativePointer) {
            const result = impl(request, pid, addr, data)
            log("ptrace", { request, pid, addr, data, result })
            return result
        }) {
            return hooks.attach("ptrace", fn, "long", ["int", "int", "pointer", "pointer"])
        },
        prctl(fn = function (impl: AnyFunction, option: number, ...args: number[]) {
            const result = impl(option, ...args)
            log("prctl", { option, args, result })
            return result
        }) {
            return hooks.attach("prctl", fn, "int", ["int", "...", "ulong"], { variadicRepeat: 4 })
        },
        syscall(fn = function (impl: AnyFunction, sysno: number, ...args: number[]) {
            const result = impl(sysno, ...args)
            log("syscall", { sysno, args, result })
            return result
        }) {
            return hooks.attach("syscall", fn, "int64", ["long", "...", "long"], { variadicRepeat: 6 })
        },
        pthread_create(fn = function (
            impl: AnyFunction,
            thread: NativePointer,
            attr: NativePointer,
            startRoutine: NativePointer,
            arg: NativePointer,
        ) {
            const result = impl(thread, attr, startRoutine, arg)
            log("pthread_create", { thread, attr, startRoutine, arg, result })
            return result
        }) {
            return hooks.attach("pthread_create", fn, "int", ["pointer", "pointer", "pointer", "pointer"])
        },
        pthread_self(fn = function (impl: AnyFunction) {
            const thread = impl()
            log("pthread_self", { thread })
            return thread
        }) {
            return hooks.attach("pthread_self", fn, "int64", [])
        },
        pthread_detach(fn = function (impl: AnyFunction, thread: number) {
            const result = impl(thread)
            log("pthread_detach", { thread, result })
            return result
        }) {
            return hooks.attach("pthread_detach", fn, "int", ["int64"])
        },
        pthread_join(fn = function (impl: AnyFunction, thread: number, valuePtr: NativePointer) {
            const result = impl(thread, valuePtr)
            log("pthread_join", { thread, valuePtr, result })
            return result
        }) {
            return hooks.attach("pthread_join", fn, "int", ["int64", "pointer"])
        },
        mmap(fn = function (
            impl: AnyFunction,
            address: NativePointer,
            length: number,
            prot: number,
            flags: number,
            fd: number,
            offset: number,
        ) {
            const result = impl(address, length, prot, flags, fd, offset)
            log("mmap", { address, length, prot, flags, fd, offset, result })
            return result
        }) {
            return hooks.attach("mmap", fn, "pointer", ["pointer", "size_t", "int", "int", "int", "int64"])
        },
        munmap(fn = function (impl: AnyFunction, address: NativePointer, length: number) {
            const result = impl(address, length)
            log("munmap", { address, length, result })
            return result
        }) {
            return hooks.attach("munmap", fn, "int", ["pointer", "size_t"])
        },
        mprotect(fn = function (impl: AnyFunction, address: NativePointer, length: number, prot: number) {
            const result = impl(address, length, prot)
            log("mprotect", { address, length, prot, result })
            return result
        }) {
            return hooks.attach("mprotect", fn, "int", ["pointer", "size_t", "int"])
        },
        malloc(fn = function (impl: AnyFunction, size: number) {
            const pointer = impl(size)
            log("malloc", { size, pointer })
            return pointer
        }) {
            return hooks.attach("malloc", fn, "pointer", ["size_t"])
        },
        calloc(fn = function (impl: AnyFunction, nmemb: number, size: number) {
            const pointer = impl(nmemb, size)
            log("calloc", { nmemb, size, pointer })
            return pointer
        }) {
            return hooks.attach("calloc", fn, "pointer", ["size_t", "size_t"])
        },
        realloc(fn = function (impl: AnyFunction, pointer: NativePointer, size: number) {
            const output = impl(pointer, size)
            log("realloc", { pointer, size, output })
            return output
        }) {
            return hooks.attach("realloc", fn, "pointer", ["pointer", "size_t"])
        },
        free(fn = function (impl: AnyFunction, pointer: NativePointer) {
            log("free", { pointer })
            return impl(pointer)
        }) {
            return hooks.attach("free", fn, "void", ["pointer"])
        },
        memcpy(fn = function (impl: AnyFunction, dest: NativePointer, src: NativePointer, size: number) {
            const result = impl(dest, src, size)
            log("memcpy", { dest, src, size, result })
            return result
        }) {
            return hooks.attach("memcpy", fn, "pointer", ["pointer", "pointer", "size_t"])
        },
        memmove(fn = function (impl: AnyFunction, dest: NativePointer, src: NativePointer, size: number) {
            const result = impl(dest, src, size)
            log("memmove", { dest, src, size, result })
            return result
        }) {
            return hooks.attach("memmove", fn, "pointer", ["pointer", "pointer", "size_t"])
        },
        memset(fn = function (impl: AnyFunction, dest: NativePointer, value: number, size: number) {
            const result = impl(dest, value, size)
            log("memset", { dest, value, size, result })
            return result
        }) {
            return hooks.attach("memset", fn, "pointer", ["pointer", "int", "size_t"])
        },
        open(fn = function (impl: AnyFunction, path: NativePointer, flags: number, ...args: number[]) {
            const result = impl(path, flags, ...args)
            log("open", { path: readCStringSafe(path), flags, args, result })
            return result
        }) {
            return hooks.attach("open", fn, "int", ["pointer", "int", "...", "int"], { variadicRepeat: 1 })
        },
        openat(fn = function (impl: AnyFunction, fd: number, path: NativePointer, flags: number, ...args: number[]) {
            const result = impl(fd, path, flags, ...args)
            log("openat", { fd, path: readCStringSafe(path), flags, args, result })
            return result
        }) {
            return hooks.attach("openat", fn, "int", ["int", "pointer", "int", "...", "int"], { variadicRepeat: 1 })
        },
        fopen(fn = function (impl: AnyFunction, path: NativePointer, mode: NativePointer) {
            const result = impl(path, mode)
            log("fopen", { path: readCStringSafe(path), mode: readCStringSafe(mode), result })
            return result
        }) {
            return hooks.attach("fopen", fn, "pointer", ["pointer", "pointer"])
        },
        close(fn = function (impl: AnyFunction, fd: number) {
            const result = impl(fd)
            log("close", { fd, result })
            return result
        }) {
            return hooks.attach("close", fn, "int", ["int"])
        },
        read(fn = function (impl: AnyFunction, fd: number, buffer: NativePointer, count: number) {
            const result = impl(fd, buffer, count)
            log("read", { fd, buffer, count, result })
            return result
        }) {
            return hooks.attach("read", fn, "int", ["int", "pointer", "size_t"])
        },
        pread(fn = function (impl: AnyFunction, fd: number, buffer: NativePointer, count: number, offset: number) {
            const result = impl(fd, buffer, count, offset)
            log("pread", { fd, buffer, count, offset, result })
            return result
        }) {
            return hooks.attach("pread", fn, "int", ["int", "pointer", "size_t", "int64"])
        },
        write(fn = function (impl: AnyFunction, fd: number, buffer: NativePointer, count: number) {
            const result = impl(fd, buffer, count)
            log("write", { fd, buffer, count, result })
            return result
        }) {
            return hooks.attach("write", fn, "int", ["int", "pointer", "size_t"])
        },
        lseek(fn = function (impl: AnyFunction, fd: number, offset: number, whence: number) {
            const result = impl(fd, offset, whence)
            log("lseek", { fd, offset, whence, result })
            return result
        }) {
            return hooks.attach("lseek", fn, "int64", ["int", "int64", "int"])
        },
        readlink(fn = function (impl: AnyFunction, path: NativePointer, buffer: NativePointer, size: number) {
            const result = impl(path, buffer, size)
            log("readlink", { path: readCStringSafe(path), size, result, output: readCStringSafe(buffer) })
            return result
        }) {
            return hooks.attach("readlink", fn, "int", ["pointer", "pointer", "size_t"])
        },
        __system_property_get(fn = function (impl: AnyFunction, name: NativePointer, value: NativePointer) {
            const result = impl(name, value)
            log("__system_property_get", {
                name: readCStringSafe(name),
                result,
                value: readCStringSafe(value),
            })
            return result
        }) {
            return hooks.attach("__system_property_get", fn, "int", ["pointer", "pointer"])
        },
    }
}

export function castElfSymbolHooks(hooks: ElfSymbolHooks): EnhancedElfSymbolHooks {
    const methods = createPresetMethods(hooks)
    return new Proxy(hooks as EnhancedElfSymbolHooks, {
        get(target, property, receiver) {
            if (typeof property === "string" && property in methods) {
                return Reflect.get(methods, property, receiver)
            }
            const value = Reflect.get(target, property, receiver)
            return typeof value === "function" ? value.bind(target) : value
        },
    })
}


import { nativeFunctionOptions } from "./consts.js"


export class FuncHelper {
    static list: any[] = []

    static $nativeWrapper<RetType extends NativeFunctionReturnType>(
        retType: RetType, argTypes: any[],
    ) {
        return function (f: NativePointer, wrapFunc: AnyFunction) {
            const impl = f.isNull() ? NULL : new NativeFunction(f, retType, argTypes, nativeFunctionOptions)
            const wrapper = function () {
                return wrapFunc(impl, ...Array.from(arguments))
            }
            const cb = new NativeCallback(wrapper, retType, argTypes)
            FuncHelper.list.push(cb)
            return cb
        }
    }

    // int __cxa_atexit(void (*f)(void *), void *objptr, void *dso);
    static atexit = this.$nativeWrapper('void', ['pointer'])

    // int pthread_create(pthread_t *thread, const pthread_attr_t *attr, void *(*start_routine)(void *), void *arg);
    static pthread_start_routine = this.$nativeWrapper('pointer', ['pointer'])

    // void (*keylog_callback)(const SSL *ssl, const char *line)
    static SSL_CTX_keylog_callback = this.$nativeWrapper('void', ['pointer', 'pointer'])
    

}

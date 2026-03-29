import { setGlobalProperties } from "../config/index.js";
import { createCallMethods, type JniCallMethods } from "./call_methods.js";
import {
    type ExtendedJavaEnv,
    JniEnvBase,
    type JavaLangReflectMethod,
} from "./factory.js";
import { jclass, jobject } from "./refs.js";
import "./strings.js";
import { createRuntimeMethods, type JniRuntimeMethods } from "./runtime_methods.js";

type JniEnvBridgeSurface = Omit<ExtendedJavaEnv, keyof JniCallMethods | keyof JniRuntimeMethods>;

export interface JniEnv extends JniEnvBridgeSurface, JniCallMethods, JniRuntimeMethods {}

export class JniEnv extends JniEnvBase {
    private static _javaLangReflectMethod: JavaLangReflectMethod | undefined;

    constructor(vm?: Java.VM) {
        super(vm);
        Object.assign(this, createCallMethods(this), createRuntimeMethods(this));
        const self = this;
        return new Proxy(this, {
            get(target, prop, receiver) {
                if (prop in target) {
                    return Reflect.get(target, prop, receiver);
                }
                const env = self.$vm.getEnv() as ExtendedJavaEnv;
                return env[prop as keyof ExtendedJavaEnv];
            },
        });
    }

    $clone(): JniEnv {
        return new JniEnv(this.$vm);
    }

    javaLangReflectMethod(): JavaLangReflectMethod {
        if (JniEnv._javaLangReflectMethod === undefined) {
            const cache = this.$env.javaLangReflectMethod();
            // Frida's bridge cache does not populate getReturnType on all Android builds.
            // Patch it once here so reflected-method helpers can rely on a stable contract.
            const klass = this.FindClass("java/lang/reflect/Method");
            const methodId = this.GetMethodID(klass, "getReturnType", "()Ljava/lang/Class;");
            cache.getReturnType = methodId;
            JniEnv._javaLangReflectMethod = cache;
            klass.$unref();
        }
        return JniEnv._javaLangReflectMethod;
    }
}

export const JNIEnv = new JniEnv();

setGlobalProperties({
    JNIEnv,
    jobject,
    jclass,
});

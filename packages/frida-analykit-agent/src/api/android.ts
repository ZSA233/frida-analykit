


export type NP = NativePointer


export interface EnvJvmti {
    handle: NP
    vm: NP,
    vtable: NP
}



// frida-java-bridge/lib/android.js
export interface VMApi {
    vm: NP
    
    module: Module

    flavor: 'art' | 'dalvik'

    addLocalRefrence: null

    find(name: string): NativePointer, // export => symbol => null

    artRuntime: NativePointer

    artClassLinker: {
        address: NativePointer,
        quickResolutionTrampoline: NativePointer,
        quickImtConflictTrampoline: NativePointer,
        quickGenericJniTrampoline: NativePointer,
        quickToInterpreterBridgeTrampoline: NativePointer,
    }

    jvmti: EnvJvmti

    $new(size: number): NativePointer
    $delete(pointer: NativePointer): void

    // jint JNI_GetCreatedJavaVMs(JavaVM** vmBuf, jsize bufLen, jsize* nVMs);
    JNI_GetCreateJavaVMs(vmBuf: NP, bufLen: number, nVMs: NP): number

    // jobject JavaVMExt::AddGlobalRef(Thread* self, ObjPtr<mirror::Object> obj)
    ['art::JavaVMExt::AddGlobalRef']: (vm: NP, self: NP, obj: NP) => NP

    // void ReaderWriterMutex::ExclusiveLock(Thread* self)
    ['art::ReaderWriterMutex::ExclusiveLock']: (lock: NP, self: NP) => void

    // IndirectRef IndirectReferenceTable::Add(IRTSegmentState previous_state, ObjPtr<mirror:: Object> obj, std::string * error_msg)
    ['art::IndirectReferenceTable::Add']: (table: NP, previous_state: NP, obj: number, error_msg: NP) => NP

    // ObjPtr<mirror::Object> JavaVMExt::DecodeGlobal(IndirectRef ref)
    // thread: 7 > Android >= 6
    ['art::JavaVMExt::DecodeGlobal']: (vm: NP, thread: NP, ref: NP) => NP

    // ObjPtr<mirror::Object> Thread::DecodeJObject(jobject obj) const
    ['art::Thread::DecodeJObject']: (thread: NP, obj: NP) => NP


    // TODO: 
}




declare global {
    namespace Java {
        const api: VMApi,
        Env: {
            handle: NativePointer
            vm: Java.VM & {
                handle: NativePointer
            }
            throwIfExceptionPending(): Error
        }
    }

}

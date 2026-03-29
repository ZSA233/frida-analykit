export type NP = NativePointer


export interface EnvJvmti {
    readonly handle: NP
    readonly vm: NP
    readonly vtable: NP
}

export interface ArtClassLinkerApi {
    readonly address: NP
    readonly quickResolutionTrampoline: NP
    readonly quickImtConflictTrampoline: NP
    readonly quickGenericJniTrampoline: NP
    readonly quickToInterpreterBridgeTrampoline: NP
}

// frida-java-bridge/lib/android.js
export interface VMApi {
    readonly vm: NP
    readonly module: Module
    readonly flavor: 'art' | 'dalvik'
    addLocalReference: ((thread: NP, object: NP) => NP) | null
    find(name: string): NP | null
    readonly artRuntime: NP
    readonly artClassLinker: ArtClassLinkerApi
    readonly jvmti: EnvJvmti
    $new(size: number): NP
    $delete(pointer: NP): void

    // jint JNI_GetCreatedJavaVMs(JavaVM** vmBuf, jsize bufLen, jsize* nVMs);
    JNI_GetCreatedJavaVMs(vmBuf: NP, bufLen: number, nVMs: NP): number

    // jobject JavaVMExt::AddGlobalRef(Thread* self, ObjPtr<mirror::Object> obj)
    ['art::JavaVMExt::AddGlobalRef']: (vm: NP, self: NP, obj: NP) => NP

    // void ReaderWriterMutex::ExclusiveLock(Thread* self)
    ['art::ReaderWriterMutex::ExclusiveLock']: (lock: NP, self: NP) => void

    // IndirectRef IndirectReferenceTable::Add(IRTSegmentState previousState, ObjPtr<mirror::Object> obj)
    ['art::IndirectReferenceTable::Add']: (table: NP, previousState: number, obj: NP) => NP

    // ObjPtr<mirror::Object> JavaVMExt::DecodeGlobal(IndirectRef ref)
    ['art::JavaVMExt::DecodeGlobal']: (vm: NP, thread: NP, ref: NP) => NP

    // ObjPtr<mirror::Object> Thread::DecodeJObject(jobject obj) const
    ['art::Thread::DecodeJObject']: (thread: NP, obj: NP) => NP
}

declare global {
    namespace Java {
        const api: VMApi
    }
}

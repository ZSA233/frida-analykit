export type DexRuntimeFileInfo = {
    name: string
    base: NativePointer
    size: number
}

export type ClassLoaderDexFiles = {
    loader_handle: NativePointer
    loader_class: string
    dexFiles: DexRuntimeFileInfo[]
}

export type DexDumpFileInfo = DexRuntimeFileInfo & {
    loader_handle: NativePointer
    loader_class: string
    output_name: string
}

export type DexDumpOptions = {
    tag?: string
    dumpDir?: string
    log?: (message: string) => void
    maxBatchBytes?: number
}

export type DexDumpSummary = {
    transferId: string
    tag: string
    dexCount: number
    totalBytes: number
    mode: "rpc" | "file"
    dumpDir?: string
    relativeDumpDir: string
}

import type { ElfModuleX } from "./module.js"

export type ElfModuleTarget = string | Module | ElfModuleX

export type ElfSymbolHookOptions = {
    abi?: NativeABI
    variadicRepeat?: number
}

export type ElfSymbolHooksOptions = {
    observeDlsym?: boolean
    logTag?: string
    tryFix?: boolean
}

export type ElfResolvedSymbol = {
    name: string
    linked: boolean
    hook: NativePointer | null
    implPtr: NativePointer | null
    relocPtr: NativePointer | null
    size: number
}

export type ElfSymbolHookResult = boolean | NativePointer

export type ElfSnapshotArtifact = "module" | "symbols" | "proc_maps" | "info"

export type ElfSnapshotOptions = {
    tag?: string
    outputDir?: string
    log?: (message: string) => void
}

export type ElfSnapshotSummary = {
    snapshotId: string
    tag: string
    moduleName: string
    totalBytes: number
    mode: "rpc" | "file"
    outputDir?: string
}

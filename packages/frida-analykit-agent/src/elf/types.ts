import type { ElfModuleX } from "./module.js"

export type ElfModuleTarget = string | Module | ElfModuleX

export type ElfSymbolHookOptions = {
    abi?: NativeABI
    variadicRepeat?: number
}

export type ElfSymbolHooksOptions = {
    observeDlsym?: boolean
    logTag?: string
    augmentMetadata?: boolean
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

export type ElfModuleDumpArtifactKind = "raw" | "fixed" | "fixups" | "symbols" | "proc_maps" | "manifest"

export type ElfModuleDumpArtifact = {
    kind: ElfModuleDumpArtifactKind
    outputName: string
    size: number
}

export type ElfModuleDumpOptions = {
    tag?: string
    outputDir?: string
    log?: (message: string) => void
    augmentMetadata?: boolean
}

export type ElfModuleDumpSummary = {
    dumpId: string
    tag: string
    moduleName: string
    totalBytes: number
    mode: "rpc" | "file"
    outputDir?: string
    relativeDumpDir: string
    artifacts: ElfModuleDumpArtifact[]
}

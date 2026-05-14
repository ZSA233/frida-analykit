export type ElfDumpHeaderSnapshot = {
    eiClass: number
    eiOsabi: number
    eType: number
    eMachine: number
    eVersion: number
    eEntry: number
    ePhoff: number
    eShoff: number
    ePhnum: number
    eShnum: number
    eShstrndx: number
}

export type ElfDumpFixStage = {
    name: string
    detail: string
}

export type ElfDumpFixStageName =
    | "phdr-rebase"
    | "dynamic-rebase"
    | "dynsym-fixups"
    | "relocation-fixups"
    | "section-rebuild"
    | "header-finalize"

export type ElfDumpFixupFieldPatch = {
    t: "f"
    n: string
    o: number
    w: number
    b: string
    a: string
}

export type ElfDumpFixupSlotPatch = {
    t: "s"
    n: string
    w: number
    v: Array<[number, string, string]>
}

export type ElfDumpFixupBlockPatch = {
    t: "x"
    n: string
    o: number
    r: number
    x: string
}

export type ElfDumpFixupPatch = ElfDumpFixupFieldPatch | ElfDumpFixupSlotPatch | ElfDumpFixupBlockPatch

export type ElfDumpFixupStage = {
    name: ElfDumpFixStageName
    detail: string
    patches: ElfDumpFixupPatch[]
}

export type ElfDumpFixupFile = {
    version: 2
    strategy: "raw-to-fixed-staged-v2"
    raw_size: number
    fixed_size: number
    stages: ElfDumpFixupStage[]
}

export type ElfDumpBuildResult = {
    fixed: ArrayBuffer
    loadBias: number
    headerBefore: ElfDumpHeaderSnapshot
    headerAfter: ElfDumpHeaderSnapshot
    stages: ElfDumpFixStage[]
    fixups: ElfDumpFixupFile
}

export type ElfClass = 1 | 2

type EhdrField =
    | "eType"
    | "eMachine"
    | "eVersion"
    | "eEntry"
    | "ePhoff"
    | "eShoff"
    | "ePhnum"
    | "eShentsize"
    | "eShnum"
    | "eShstrndx"

type PhdrField =
    | "pType"
    | "pFlags"
    | "pOffset"
    | "pVaddr"
    | "pPaddr"
    | "pFilesz"
    | "pMemsz"
    | "pAlign"

type ShdrField =
    | "shName"
    | "shType"
    | "shFlags"
    | "shAddr"
    | "shOffset"
    | "shSize"
    | "shLink"
    | "shInfo"
    | "shAddralign"
    | "shEntsize"

type DynField = "dTag" | "dUn"

type SymField =
    | "stName"
    | "stInfo"
    | "stOther"
    | "stShndx"
    | "stValue"
    | "stSize"

type RelaField = "rOffset" | "rInfo" | "rAddend"

type ElfStructLayout<TField extends string> = Readonly<{
    size: number
    fields: Readonly<Record<TField, number>>
}>

export type ElfAbiLayout = Readonly<{
    eiClass: ElfClass
    is32: boolean
    pointerSize: 4 | 8
    ehdr: ElfStructLayout<EhdrField>
    phdr: ElfStructLayout<PhdrField>
    shdr: ElfStructLayout<ShdrField>
    dyn: ElfStructLayout<DynField>
    sym: ElfStructLayout<SymField>
    rela: ElfStructLayout<RelaField> & Readonly<{
        infoSymShift: bigint
        infoTypeMask: bigint
        relocValueOffset: number
    }>
}>

export const ELF_MAGIC_BYTES = [0x7f, 0x45, 0x4c, 0x46] as const

export const ELF_IDENT_OFFSETS = {
    magic: 0,
    eiClass: 4,
    eiOsabi: 7,
    identPaddingStart: 8,
    identPaddingEnd: 16,
} as const

const ELF_ABI_LAYOUT_32: ElfAbiLayout = {
    eiClass: 1,
    is32: true,
    pointerSize: 4,
    ehdr: {
        size: 52,
        fields: {
            eType: 16,
            eMachine: 18,
            eVersion: 20,
            eEntry: 24,
            ePhoff: 28,
            eShoff: 32,
            ePhnum: 44,
            eShentsize: 46,
            eShnum: 48,
            eShstrndx: 50,
        },
    },
    phdr: {
        size: 32,
        fields: {
            pType: 0,
            pOffset: 4,
            pVaddr: 8,
            pPaddr: 12,
            pFilesz: 16,
            pMemsz: 20,
            pFlags: 24,
            pAlign: 28,
        },
    },
    shdr: {
        size: 40,
        fields: {
            shName: 0,
            shType: 4,
            shFlags: 8,
            shAddr: 12,
            shOffset: 16,
            shSize: 20,
            shLink: 24,
            shInfo: 28,
            shAddralign: 32,
            shEntsize: 36,
        },
    },
    dyn: {
        size: 8,
        fields: {
            dTag: 0,
            dUn: 4,
        },
    },
    sym: {
        size: 16,
        fields: {
            stName: 0,
            stInfo: 4,
            stOther: 5,
            stShndx: 6,
            stValue: 8,
            stSize: 12,
        },
    },
    rela: {
        size: 12,
        fields: {
            rOffset: 0,
            rInfo: 4,
            rAddend: 8,
        },
        infoSymShift: 16n,
        infoTypeMask: 0xffffn,
        relocValueOffset: 0,
    },
}

const ELF_ABI_LAYOUT_64: ElfAbiLayout = {
    eiClass: 2,
    is32: false,
    pointerSize: 8,
    ehdr: {
        size: 64,
        fields: {
            eType: 16,
            eMachine: 18,
            eVersion: 20,
            eEntry: 24,
            ePhoff: 32,
            eShoff: 40,
            ePhnum: 56,
            eShentsize: 58,
            eShnum: 60,
            eShstrndx: 62,
        },
    },
    phdr: {
        size: 56,
        fields: {
            pType: 0,
            pFlags: 4,
            pOffset: 8,
            pVaddr: 16,
            pPaddr: 24,
            pFilesz: 32,
            pMemsz: 40,
            pAlign: 48,
        },
    },
    shdr: {
        size: 64,
        fields: {
            shName: 0,
            shType: 4,
            shFlags: 8,
            shAddr: 16,
            shOffset: 24,
            shSize: 32,
            shLink: 40,
            shInfo: 44,
            shAddralign: 48,
            shEntsize: 56,
        },
    },
    dyn: {
        size: 16,
        fields: {
            dTag: 0,
            dUn: 8,
        },
    },
    sym: {
        size: 24,
        fields: {
            stName: 0,
            stInfo: 4,
            stOther: 5,
            stShndx: 6,
            stValue: 8,
            stSize: 16,
        },
    },
    rela: {
        size: 24,
        fields: {
            rOffset: 0,
            rInfo: 8,
            rAddend: 16,
        },
        infoSymShift: 32n,
        infoTypeMask: 0xffffffffn,
        relocValueOffset: 0,
    },
}

export const ELF_ABI_LAYOUTS: Readonly<Record<ElfClass, ElfAbiLayout>> = {
    1: ELF_ABI_LAYOUT_32,
    2: ELF_ABI_LAYOUT_64,
}

export function getElfAbiLayout(eiClass: number): ElfAbiLayout {
    if (eiClass !== 1 && eiClass !== 2) {
        throw new Error(`[elf abi] unsupported ELF class: ${eiClass}`)
    }
    return ELF_ABI_LAYOUTS[eiClass]
}

export enum DyntabTag {
    DT_NULL = 0,
    DT_NEEDED = 1,
    DT_PLTRELSZ = 2,
    DT_PLTGOT = 3,
    DT_HASH = 4,
    DT_STRTAB = 5,
    DT_SYMTAB = 6,
    DT_RELA = 7,
    DT_RELASZ = 8,
    DT_RELAENT = 9,
    DT_STRSZ = 10,
    DT_SYMENT = 11,
    DT_INIT = 12,
    DT_FINI = 13,
    DT_SONAME = 14,
    DT_RPATH = 15,
    DT_SYMBOLIC = 16,
    DT_REL = 17,
    DT_RELSZ = 18,
    DT_RELENT = 19,
    DT_PLTREL = 20,
    DT_DEBUG = 21,
    DT_TEXTREL = 22,
    DT_JMPREL = 23,
    DT_BIND_NOW = 24,
    DT_INIT_ARRAY = 25,
    DT_FINI_ARRAY = 26,
    DT_INIT_ARRAYSZ = 27,
    DT_FINI_ARRAYSZ = 28,
    DT_RUNPATH = 29,
    DT_FLAGS = 30,
    DT_ENCODING = 32,
    DT_RELR = 0x6fffe000,
    DT_RELRSZ = 0x6fffe001,
    DT_RELRENT = 0x6fffe003,
    DT_RELRCOUNT = 0x6fffe005,
}

export const PT_LOAD = 1
export const PT_DYNAMIC = 2
export const PT_LOPROC = 0x70000000

export const PF_X = 0x1

export const SHT_NULL = 0
export const SHT_PROGBITS = 1
export const SHT_RELA = 4
export const SHT_HASH = 5
export const SHT_DYNAMIC = 6
export const SHT_NOTE = 7
export const SHT_NOBITS = 8
export const SHT_REL = 9
export const SHT_STRTAB = 3
export const SHT_DYNSYM = 11
export const SHT_INIT_ARRAY = 14
export const SHT_FINI_ARRAY = 15
export const SHT_PREINIT_ARRAY = 16
export const SHT_GROUP = 17
export const SHT_SYMTAB_SHNDX = 18

export const SHF_WRITE = 0x1
export const SHF_ALLOC = 0x2
export const SHF_EXECINSTR = 0x4

export const STT_NOTYPE = 0x0
export const STT_OBJECT = 0x1
export const STT_FUNC = 0x2
export const STT_SECTION = 0x3
export const STT_FILE = 0x4

export const SHN_UNDEF = 0
export const SHN_ABS = 0xfff1

export const R_ARM_JUMP_SLOT = 22
export const R_ARM_RELATIVE = 23
export const R_AARCH64_JUMP_SLOT = 1026
export const R_AARCH64_RELATIVE = 1027
export const R_386_JUMP_SLOT = 7
export const R_386_RELATIVE = 8
export const R_X86_64_JUMP_SLOT = 7
export const R_X86_64_RELATIVE = 8

export const EI_OSABI_SYSV = 0
export const ET_DYN = 3
export const EV_CURRENT = 1

export const EM_386 = 3
export const EM_ARM = 40
export const EM_X86_64 = 62
export const EM_AARCH64 = 183

export function elfMachineForProcessArch(arch: string): number {
    switch (arch) {
        case "arm":
            return EM_ARM
        case "arm64":
            return EM_AARCH64
        case "ia32":
            return EM_386
        case "x64":
            return EM_X86_64
        default:
            throw new Error(`[elf abi] unsupported Process.arch for e_machine normalization: ${arch}`)
    }
}

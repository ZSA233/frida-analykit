
import {
    readByteArray,
    binaryReadU8, binaryReadU16,
    binaryReadU32, binaryReadS32,
    binaryReadU64, binaryReadS64,
} from "../utils/utils.js"



export type Ehdr = {
    ei_class: number,
    e_type: number,
    e_phoff: number,
    e_shoff: number,
    e_phnum: number,
    e_shnum: number,
    e_shstrndx: number,
}

export type Phdr = {
    p_type: number,
    p_offset: number,
    p_vaddr: number,
    p_paddr: number,
    p_filesz: number,
    p_memsz: number,
    p_align: number,
}

export type Shdr = {
    name: string | null,
    base: NativePointer
    size: number

    sh_name: number,
    sh_type: number,
    sh_addr: number,
    sh_offset: number,
    sh_size: number,
    sh_link: number,
    sh_info: number,
    sh_addralign: number,
    sh_entsize: number,
}


export type Dyn = {
    d_tag: number,
    d_un: number,
}


export class Soinfo {
    strtab: NativePointer = NULL
    strtab_size: number = 0
    symtab: NativePointer = NULL
    plt_rela: NativePointer = NULL
    plt_rela_count: number = 0
    rela: NativePointer = NULL
    rela_count: number = 0
    relr: NativePointer = NULL
    relr_count: number = 0
    init_func: NativePointer = NULL
    init_array: NativePointer = NULL
    init_array_count: number = 0
    fini_array: NativePointer = NULL
    fini_array_count: number = 0
    plt_got: NativePointer = NULL
}

export type Rela = {
    r_offset: number,
    r_info: number,
    r_addend: number,
}


export type Sym = {
    name: string
    relocPtr: NativePointer | null
    hook: NativePointer | null
    implPtr: NativePointer | null
    linked: boolean

    st_name: number
    st_info: number
    st_other: number
    st_shndx: number
    st_value: NativePointer | null
    st_size: number
}


export const Elf_Ehdr = {
    EI_Magic: readByteArray(0, 4),
    EI_CLASS: binaryReadU8(4),
    B64: {
        E_Type: binaryReadU16(16),
        E_Phoff: binaryReadU64(32),
        E_Shoff: binaryReadU64(40),
        E_Phnum: binaryReadU16(56),
        E_Shnum: binaryReadU16(60),
        E_Shstrndx: binaryReadU16(62),
        SIZE: 64,
    },
    B32: {
        E_Type: binaryReadU16(16),
        E_Phoff: binaryReadU32(28),
        E_Shoff: binaryReadU32(32),
        E_Phnum: binaryReadU16(44),
        E_Shnum: binaryReadU16(48),
        E_Shstrndx: binaryReadU16(50),
        SIZE: 52,
    },
}


export const Elf_Phdr = {
    B64: {
        P_Type: binaryReadU32(0),
        E_Flags: binaryReadU32(4),
        P_Offset: binaryReadU64(8),
        P_Vaddr: binaryReadU64(16),
        P_Paddr: binaryReadU64(24),
        P_Filesz: binaryReadU64(32),
        P_Memsz: binaryReadU64(40),
        P_Align: binaryReadU64(48),
        SIZE: 56,
    },
    B32: {
        P_Type: binaryReadU32(0),
        E_Flags: binaryReadU32(4),
        P_Offset: binaryReadU32(8),
        P_Vaddr: binaryReadU32(12),
        P_Paddr: binaryReadU32(16),
        P_Filesz: binaryReadU32(20),
        P_Memsz: binaryReadU32(24),
        P_Align: binaryReadU32(28),
        SIZE: 32,
    },
}


export const Elf_Shdr = {
    B64: {
        Sh_Name: binaryReadU32(0),
        Sh_Type: binaryReadU32(4),
        Sh_Flags: binaryReadU64(8),
        Sh_Addr: binaryReadU64(16),
        Sh_Offset: binaryReadU64(24),
        Sh_Size: binaryReadU64(32),
        Sh_Link: binaryReadU32(40),
        Sh_Info: binaryReadU32(44),
        Sh_Addralign: binaryReadU64(48),
        Sh_Entsize: binaryReadU64(56),
        SIZE: 64,
    },
    B32: {
        Sh_Name: binaryReadU32(0),
        Sh_Type: binaryReadU32(4),
        Sh_Flags: binaryReadU32(8),
        Sh_Addr: binaryReadU32(12),
        Sh_Offset: binaryReadU32(16),
        Sh_Size: binaryReadU32(20),
        Sh_Link: binaryReadU32(24),
        Sh_Info: binaryReadU32(28),
        Sh_Addralign: binaryReadU32(32),
        Sh_Entsize: binaryReadU32(36),
        SIZE: 40,
    },
}

export const Elf_Dyn = {
    B64: {
        D_Tag: binaryReadU64(0),
        D_Un: binaryReadU64(8),
        SIZE: 16,
    },
    B32: {
        D_Tag: binaryReadU32(0),
        D_Un: binaryReadU32(4),
        SIZE: 8,
    },
}


export const Elf_Sym = {
    B64: {
        St_Name: binaryReadU32(0),
        St_Info: binaryReadU8(4),
        St_Other: binaryReadU8(5),
        St_Shndx: binaryReadU16(6),
        St_Value: binaryReadU64(8),
        St_Size: binaryReadU64(16),
        SIZE: 24,
    },
    B32: {
        St_Name: binaryReadU32(0),
        St_Info: binaryReadU8(4),
        St_Other: binaryReadU8(5),
        St_Shndx: binaryReadU16(6),
        St_Value: binaryReadU32(8),
        St_Size: binaryReadU32(12),
        SIZE: 16,
    }
}

export const Elf_Rela = {
    B64: {
        R_Offset: binaryReadU64(0),
        R_Info: binaryReadU64(8),
        R_Addend: binaryReadS64(16),
        SIZE: 24,
        INFO_SYM: 32n,
        INFO_TYPE: 0xffffffffn,
        Reloc: binaryReadU64(0),
    },
    B32: {
        R_Offset: binaryReadU32(0),
        R_Info: binaryReadU32(4),
        R_Addend: binaryReadS32(8),
        SIZE: 12,
        INFO_SYM: 16n,
        INFO_TYPE: 0xffffn,
        Reloc: binaryReadU32(0),
    },
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
    DT_ENCODING = 32,

    DT_BIND_NOW = 24,
    DT_INIT_ARRAY = 25,
    DT_FINI_ARRAY = 26,
    DT_INIT_ARRAYSZ = 27,
    DT_FINI_ARRAYSZ = 28,
    DT_RUNPATH = 29,
    DT_FLAGS = 30,
    
    DT_RELR = 0x6fffe000,
    DT_RELRSZ = 0x6fffe001,
    DT_RELRENT = 0x6fffe003,
    DT_RELRCOUNT = 0x6fffe005,
}


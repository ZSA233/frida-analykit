import {
    readByteArray,
    binaryReadU8, binaryReadU16,
    binaryReadU32, binaryReadS32,
    binaryReadU64, binaryReadS64,
} from "../internal/binary/readers.js"
import { ELF_ABI_LAYOUTS, ELF_IDENT_OFFSETS, DyntabTag, type ElfAbiLayout } from "./internal/abi.js"
export { DyntabTag } from "./internal/abi.js"



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

function createEhdrReaders(layout: ElfAbiLayout) {
    const fields = layout.ehdr.fields
    return {
        E_Type: binaryReadU16(fields.eType),
        E_Phoff: layout.is32 ? binaryReadU32(fields.ePhoff) : binaryReadU64(fields.ePhoff),
        E_Shoff: layout.is32 ? binaryReadU32(fields.eShoff) : binaryReadU64(fields.eShoff),
        E_Phnum: binaryReadU16(fields.ePhnum),
        E_Shnum: binaryReadU16(fields.eShnum),
        E_Shstrndx: binaryReadU16(fields.eShstrndx),
        SIZE: layout.ehdr.size,
    }
}

function createPhdrReaders(layout: ElfAbiLayout) {
    const fields = layout.phdr.fields
    return {
        P_Type: binaryReadU32(fields.pType),
        E_Flags: binaryReadU32(fields.pFlags),
        P_Offset: layout.is32 ? binaryReadU32(fields.pOffset) : binaryReadU64(fields.pOffset),
        P_Vaddr: layout.is32 ? binaryReadU32(fields.pVaddr) : binaryReadU64(fields.pVaddr),
        P_Paddr: layout.is32 ? binaryReadU32(fields.pPaddr) : binaryReadU64(fields.pPaddr),
        P_Filesz: layout.is32 ? binaryReadU32(fields.pFilesz) : binaryReadU64(fields.pFilesz),
        P_Memsz: layout.is32 ? binaryReadU32(fields.pMemsz) : binaryReadU64(fields.pMemsz),
        P_Align: layout.is32 ? binaryReadU32(fields.pAlign) : binaryReadU64(fields.pAlign),
        SIZE: layout.phdr.size,
    }
}

function createShdrReaders(layout: ElfAbiLayout) {
    const fields = layout.shdr.fields
    return {
        Sh_Name: binaryReadU32(fields.shName),
        Sh_Type: binaryReadU32(fields.shType),
        Sh_Flags: layout.is32 ? binaryReadU32(fields.shFlags) : binaryReadU64(fields.shFlags),
        Sh_Addr: layout.is32 ? binaryReadU32(fields.shAddr) : binaryReadU64(fields.shAddr),
        Sh_Offset: layout.is32 ? binaryReadU32(fields.shOffset) : binaryReadU64(fields.shOffset),
        Sh_Size: layout.is32 ? binaryReadU32(fields.shSize) : binaryReadU64(fields.shSize),
        Sh_Link: binaryReadU32(fields.shLink),
        Sh_Info: binaryReadU32(fields.shInfo),
        Sh_Addralign: layout.is32 ? binaryReadU32(fields.shAddralign) : binaryReadU64(fields.shAddralign),
        Sh_Entsize: layout.is32 ? binaryReadU32(fields.shEntsize) : binaryReadU64(fields.shEntsize),
        SIZE: layout.shdr.size,
    }
}

function createDynReaders(layout: ElfAbiLayout) {
    const fields = layout.dyn.fields
    return {
        D_Tag: layout.is32 ? binaryReadU32(fields.dTag) : binaryReadU64(fields.dTag),
        D_Un: layout.is32 ? binaryReadU32(fields.dUn) : binaryReadU64(fields.dUn),
        SIZE: layout.dyn.size,
    }
}

function createSymReaders(layout: ElfAbiLayout) {
    const fields = layout.sym.fields
    return {
        St_Name: binaryReadU32(fields.stName),
        St_Info: binaryReadU8(fields.stInfo),
        St_Other: binaryReadU8(fields.stOther),
        St_Shndx: binaryReadU16(fields.stShndx),
        St_Value: layout.is32 ? binaryReadU32(fields.stValue) : binaryReadU64(fields.stValue),
        St_Size: layout.is32 ? binaryReadU32(fields.stSize) : binaryReadU64(fields.stSize),
        SIZE: layout.sym.size,
    }
}

function createRelaReaders(layout: ElfAbiLayout) {
    const fields = layout.rela.fields
    return {
        R_Offset: layout.is32 ? binaryReadU32(fields.rOffset) : binaryReadU64(fields.rOffset),
        R_Info: layout.is32 ? binaryReadU32(fields.rInfo) : binaryReadU64(fields.rInfo),
        R_Addend: layout.is32 ? binaryReadS32(fields.rAddend) : binaryReadS64(fields.rAddend),
        SIZE: layout.rela.size,
        INFO_SYM: layout.rela.infoSymShift,
        INFO_TYPE: layout.rela.infoTypeMask,
        Reloc: layout.is32 ? binaryReadU32(layout.rela.relocValueOffset) : binaryReadU64(layout.rela.relocValueOffset),
    }
}

const ELF_ABI_32 = ELF_ABI_LAYOUTS[1]
const ELF_ABI_64 = ELF_ABI_LAYOUTS[2]


export const Elf_Ehdr = {
    EI_Magic: readByteArray(ELF_IDENT_OFFSETS.magic, 4),
    EI_CLASS: binaryReadU8(ELF_IDENT_OFFSETS.eiClass),
    B64: createEhdrReaders(ELF_ABI_64),
    B32: createEhdrReaders(ELF_ABI_32),
}


export const Elf_Phdr = {
    B64: createPhdrReaders(ELF_ABI_64),
    B32: createPhdrReaders(ELF_ABI_32),
}


export const Elf_Shdr = {
    B64: createShdrReaders(ELF_ABI_64),
    B32: createShdrReaders(ELF_ABI_32),
}

export const Elf_Dyn = {
    B64: createDynReaders(ELF_ABI_64),
    B32: createDynReaders(ELF_ABI_32),
}


export const Elf_Sym = {
    B64: createSymReaders(ELF_ABI_64),
    B32: createSymReaders(ELF_ABI_32),
}

export const Elf_Rela = {
    B64: createRelaReaders(ELF_ABI_64),
    B32: createRelaReaders(ELF_ABI_32),
}

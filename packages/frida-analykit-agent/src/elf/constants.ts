import { SHN_ABS, SHN_UNDEF, STT_FILE, STT_FUNC, STT_NOTYPE, STT_OBJECT, STT_SECTION } from "./internal/abi.js"

export const SYM_INFO_BIND: Readonly<Record<"STB_LOCAL" | "STB_GLOBAL" | "STB_WEAK" | "STB_GNU_UNIQUE", number>> = {
    STB_LOCAL: 0x0,
    STB_GLOBAL: 0x1,
    STB_WEAK: 0x2,
    STB_GNU_UNIQUE: 0x3,
}

export const SYM_INFO_TYPE: Readonly<Record<"STT_NOTYPE" | "STT_OBJECT" | "STT_FUNC" | "STT_SECTION" | "STT_FILE", number>> = {
    STT_NOTYPE,
    STT_OBJECT,
    STT_FUNC,
    STT_SECTION,
    STT_FILE,
}

export const SYM_SHNDX: Readonly<Record<"SHN_UNDEF" | "SHN_ABS", number>> = {
    SHN_UNDEF,
    SHN_ABS,
}

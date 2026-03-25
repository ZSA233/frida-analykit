



export const nativeFunctionOptions: NativeABI | NativeFunctionOptions = {
    exceptions: 'propagate',
}




export const enum SYM_INFO_BIND {
    STB_LOCAL = 0x0,
    STB_GLOBAL = 0x1,
    STB_WEAK = 0x2,
    STB_GNU_UNIQUE = 0x3,
}


export const enum SYM_INFO_TYPE {
    STT_NOTYPE = 0x0,
    STT_OBJECT = 0x1,
    STT_FUNC = 0x2,
    STT_SECTION = 0x3,
    STT_FILE = 0x4,
}

export const enum SYM_SHNDX {
    SHN_UNDEF = 0,
    SHN_ABS = 0xfff1,
}


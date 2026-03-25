
import { Ehdr, Phdr, Dyn, Shdr, Soinfo, Sym, Rela } from './struct.js'
import { nativeFunctionOptions, SYM_INFO_BIND, SYM_INFO_TYPE, SYM_SHNDX } from '../consts.js'
import {
    Elf_Dyn, Elf_Ehdr, Elf_Phdr, Elf_Shdr, Elf_Sym, Elf_Rela,
    DyntabTag
} from './struct.js'
import { help , downAlign, upAlign, page_end, page_start } from '../helper.js'
import { ArrayPointer } from '../utils/array_pointer.js'
import { setGlobalProperties } from '../config.js'
import { saveFileSource } from '../message.js'


interface ElfModuleX extends BaseModule {}


declare global {
    interface BaseModule {
        name: string
        base: NativePointer
        size: number

    }
}


export interface ElfModuleFixer {
    fixShdrs(modx: ElfModuleX): boolean
}


class ElfModuleX {
    module: BaseModule
    ehdr: Ehdr
    phdrs: Phdr[]
    dyntabs: Dyn[] | null
    shdrs: Shdr[] | null = null
    soinfo: Soinfo | null
    dynSymbols: Sym[] | null
    rela: Rela[] | null
    plt_rela: Rela[] | null
    
    symtab: Sym[] | null = null
    strtab: { [key: number]: string } | null = null

    private _keepNativeCb: {[key: string]: any}

    constructor(module: BaseModule, fixers?: ElfModuleFixer[], { symbolScanLimit=1000 }: {symbolScanLimit?: number } = {}) {
        this.name = module.name
        this.base = module.base
        this.size = module.size
        this.module = module

        this.ehdr = this.readEhdr()
        this.phdrs = this.readPhdrs()
        this.dyntabs = this.readDyntabs()
        this.soinfo = this.prelink_image()
        this.dynSymbols = this.scanSymbols(0, symbolScanLimit)

        try {
            this.shdrs = this.readShdrs()
        }catch(e){
            if(fixers) {
                for(let fixer of fixers) {
                    if(fixer.fixShdrs(this)) {
                        break 
                    }
                }
            }
            // if(!this.shdrs) {
            //     throw e
            // }
        }


        this.rela = this.readRela()
        this.plt_rela = this.readPltRela()


        // TODO: android_relocs/relocate_relr

        this._keepNativeCb = {}

        this.link_image()

        return new Proxy(this, {
            get(target: any, prop: string) {
                if (prop in target) {
                    return target[prop as keyof ElfModuleX]
                }
                return target.module[prop as keyof BaseModule]
            }
        })
    }

    static loadFromModule(mod: Module) {
        return new ElfModuleX(mod)
    }

    readEhdr() {
        const base = this.module.base
        const magic = Array.from(new Uint8Array(Elf_Ehdr.EI_Magic(base)))
        const FIXED_MAGIC = [0x7f, 0x45, 0x4c, 0x46]
        if (!FIXED_MAGIC.every((v, i) => v == magic[i])) {
            throw new Error(`error magic[${magic}]`)
        }
        const ei_class = Elf_Ehdr.EI_CLASS(base)
        const structOf = ei_class === 1 ? Elf_Ehdr.B32 : Elf_Ehdr.B64
        return {
            ei_class: ei_class,
            e_type: structOf.E_Type(base),
            e_phoff: structOf.E_Phoff(base),
            e_shoff: structOf.E_Shoff(base),
            e_phnum: structOf.E_Phnum(base),
            e_shnum: structOf.E_Shnum(base),
            e_shstrndx: structOf.E_Shstrndx(base),
        }
    }

    readPhdrs() {
        const base = this.module.base.add(this.ehdr.e_phoff)
        const structOf = this.ehdr.ei_class === 1 ? Elf_Phdr.B32 : Elf_Phdr.B64
        const tables: Phdr[] = []
        for (let i = 0; i < this.ehdr.e_phnum; i++) {
            const cellBase = base.add(i * structOf.SIZE)
            tables.push({
                p_type: structOf.P_Type(cellBase),
                p_offset: structOf.P_Offset(cellBase),
                p_vaddr: structOf.P_Vaddr(cellBase),
                p_paddr: structOf.P_Paddr(cellBase),
                p_filesz: structOf.P_Filesz(cellBase),
                p_memsz: structOf.P_Memsz(cellBase),
                p_align: structOf.P_Align(cellBase),
            })
        }
        return tables
    }

    readDyntabs() {
        let dynPhdr: Phdr | null = null
        for (let phdr of this.phdrs) {
            if (phdr.p_type !== 0x2) {
                continue
            }
            dynPhdr = phdr
        }
        if (!dynPhdr) {
            return null
        }

        const structOf = this.ehdr.ei_class === 1 ? Elf_Dyn.B32 : Elf_Dyn.B64

        const base = this.module.base.add(dynPhdr.p_vaddr)
        const tables: Dyn[] = []

        for (let i = 0; i < dynPhdr.p_filesz / structOf.SIZE; i++) {
            const cellBase = base.add(i * structOf.SIZE)
            tables.push({
                d_tag: structOf.D_Tag(cellBase),
                d_un: structOf.D_Un(cellBase),
            })
        }
        return tables
    }

    load_bias(value: number | NativePointer) { return this.module.base.add(value) }

    prelink_image() {
        if (this.dyntabs === null) {
            return null
        }
        const soinfo: Soinfo = new Soinfo()
        const structOf = this.ehdr.ei_class === 1 ? Elf_Rela.B32 : Elf_Rela.B64
        for (let dyn of this.dyntabs) {
            switch (Number(dyn.d_tag)) {
                case DyntabTag.DT_STRTAB:
                    soinfo.strtab = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_STRSZ:
                    soinfo.strtab_size = dyn.d_un
                    break
                case DyntabTag.DT_SYMTAB:
                    soinfo.symtab = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_JMPREL:
                    soinfo.plt_rela = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_PLTRELSZ:
                    soinfo.plt_rela_count = Math.floor(dyn.d_un / structOf.SIZE)
                    break
                case DyntabTag.DT_RELA:
                    soinfo.rela = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_RELASZ:
                    soinfo.rela_count = Math.floor(dyn.d_un / structOf.SIZE)
                    break
                case DyntabTag.DT_RELR:
                    soinfo.relr = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_RELRSZ:
                    soinfo.relr_count = dyn.d_un
                    break
                case DyntabTag.DT_INIT:
                    soinfo.init_func = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_INIT_ARRAY:
                    soinfo.init_array = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_INIT_ARRAYSZ:
                    soinfo.init_array_count = dyn.d_un
                    break
                case DyntabTag.DT_FINI_ARRAY:
                    soinfo.fini_array = this.load_bias(dyn.d_un)
                    break
                case DyntabTag.DT_FINI_ARRAYSZ:
                    soinfo.fini_array_count = dyn.d_un
                    break
                case DyntabTag.DT_PLTGOT:
                    soinfo.plt_got = this.load_bias(dyn.d_un)
                    break
            }
        }
        return soinfo
    }

    link_image() {
        if (this.dynSymbols == null || (this.rela == null && this.plt_rela == null)) {
            return
        }

        const relas = (this.rela || []).concat(this.plt_rela || [])
        const structOf = this.ehdr.ei_class === 1 ? Elf_Rela.B32 : Elf_Rela.B64
        for (let rel of relas) {
            const type = BigInt(rel.r_info) & structOf.INFO_TYPE
            const sym = BigInt(rel.r_info) >> structOf.INFO_SYM
            const reloc = rel.r_offset
            if (type === 0n) {
                continue
            }
            const s = this.dynSymbols[Number(sym)]
            if (sym === 0n) {
            } else if (s?.name && reloc) {
                const relocPtr = this.module.base.add(reloc)
                s.relocPtr = relocPtr
                s.st_value = ptr(structOf.Reloc(relocPtr))
            }
        }
    }

    off2addr(offset: number) {
        let dstPhdr: Phdr | null = null
        for (let phdr of this.phdrs) {
            if (phdr.p_type !== 0x1) {
                continue
            }
            const file_page_start = page_start(phdr.p_offset)
            const file_length = phdr.p_offset + phdr.p_filesz - file_page_start
            if (!dstPhdr || phdr.p_offset + phdr.p_filesz >= dstPhdr.p_offset + dstPhdr.p_filesz) {
                dstPhdr = phdr
            }
            if (offset >= file_page_start && offset < file_page_start + file_length) {
                dstPhdr = phdr
                break
            }

        }
        if (dstPhdr) {
            const seg_page_start = page_start(dstPhdr.p_vaddr)
            const file_page_start = page_start(dstPhdr.p_offset)
            return seg_page_start - file_page_start + offset
        }
        return null
    }

    readShdrs() {
        const addr = this.off2addr(this.ehdr.e_shoff)
        if (!addr) {
            return null
        }
        const base = this.module.base.add(addr)
        if(!this.isMyAddr(base)) {
            throw new Error(`shdrs not found in ${base}`)
        }
        const structOf = this.ehdr.ei_class === 1 ? Elf_Shdr.B32 : Elf_Shdr.B64
        const tables: Shdr[] = []
        for (let i = 0; i < this.ehdr.e_shnum; i++) {
            const cellBase = base.add(i * structOf.SIZE)
            const sh_addr = structOf.Sh_Addr(cellBase)
            const sh_size = structOf.Sh_Size(cellBase)
            tables.push({
                name: null,
                base: this.module.base.add(sh_addr),
                size: sh_size,

                sh_name: structOf.Sh_Name(cellBase),
                sh_type: structOf.Sh_Type(cellBase),
                sh_addr: sh_addr,
                sh_offset: structOf.Sh_Offset(cellBase),
                sh_size: sh_size,
                sh_link: structOf.Sh_Link(cellBase),
                sh_info: structOf.Sh_Info(cellBase),
                sh_addralign: structOf.Sh_Addralign(cellBase),
                sh_entsize: structOf.Sh_Entsize(cellBase),
            })
        }

        // fill name
        const shstrndxShdr = tables[this.ehdr.e_shstrndx]
        const shstrBase = this.base.add(shstrndxShdr.sh_offset)
        for(let v of tables) {
            v.name = shstrBase.add(v.sh_name).readCString()
        }
        return tables
    }

    getSymString(index: number) {
        if (this.soinfo == null || index >= this.soinfo.strtab_size) {
            return null
        }
        const p = this.soinfo.strtab.add(index)
        return p.readCString()
    }

    scanSymbols(cursor: number, limit: number): Sym[] | null {
        if(this.soinfo == null) {
            return null
        }
        const base = this.soinfo.symtab
        const structOf = this.ehdr.ei_class === 1 ? Elf_Sym.B32 : Elf_Sym.B64
        const symbols: Sym[] = []
        for (let i = cursor; i < cursor + limit; i++) {
            const cellBase = base.add(i * structOf.SIZE)
            const nameIDX = structOf.St_Name(cellBase)
            const name = this.getSymString(nameIDX)
            if (name == null) {
                break
            }
            let implPtr = ptr(structOf.St_Value(cellBase))
            const st_info = structOf.St_Info(cellBase)
            const st_shndx = structOf.St_Shndx(cellBase)
            const st_other = structOf.St_Other(cellBase)

            if ([SYM_SHNDX.SHN_UNDEF, SYM_SHNDX.SHN_ABS].indexOf(st_shndx) === -1) {
                if ([SYM_INFO_TYPE.STT_FUNC, SYM_INFO_TYPE.STT_OBJECT].indexOf(st_info & 0xF) !== -1) {
                    if (!this.isMyAddr(implPtr)) {
                        implPtr = this.module.base.add(implPtr)
                    }
                }
            }

            const sym: Sym = {
                name: name,
                relocPtr: null,
                hook: null,
                implPtr: implPtr,
                linked: true,

                st_name: nameIDX,
                st_info: st_info,
                st_other: st_other,
                st_shndx: st_shndx,
                st_value: implPtr,
                st_size: structOf.St_Size(cellBase),
            }
            symbols.push(sym)
        }
        return symbols
    }

    readRela() {
        if(this.soinfo == null) {
            return null
        }
        const structOf = this.ehdr.ei_class === 1 ? Elf_Rela.B32 : Elf_Rela.B64
        // DT_RELA
        const base = this.soinfo.rela
        const tables: Rela[] = []
        for (let i = 0; i < (this.soinfo.rela_count || 0); i++) {
            const cellBase = base.add(i * structOf.SIZE)
            const rela: Rela = {
                r_offset: structOf.R_Offset(cellBase),
                r_info: structOf.R_Info(cellBase),
                r_addend: structOf.R_Addend(cellBase),
            }
            tables.push(rela)
        }
        return tables
    }

    readPltRela() {
        if (this.soinfo == null) {
            return null
        }
        const structOf = this.ehdr.ei_class === 1 ? Elf_Rela.B32 : Elf_Rela.B64
        // DT_JMPREL
        const base = this.soinfo.plt_rela
        const tables: Rela[] = []
        for (let i = 0; i < (this.soinfo.plt_rela_count || 0); i++) {
            const cellBase = base.add(i * structOf.SIZE)
            const rela: Rela = {
                r_offset: structOf.R_Offset(cellBase),
                r_info: structOf.R_Info(cellBase),
                r_addend: structOf.R_Addend(cellBase),
            }
            tables.push(rela)
        }
        return tables
    }

    attachSymbol<RetType extends NativeFunctionReturnType, ArgTypes extends any[]>(
        symName: string, fn: AnyFunction, retType: RetType, argTypes: ArgTypes, abi = undefined,
    ) {
        if(this.dynSymbols == null) {
            return false
        }
        const sym = this.dynSymbols.find(sym => sym.name == symName)
        if (!sym || sym.st_value == null || sym.relocPtr == null) {
            return false
        }
        const impl = new NativeFunction(sym.st_value, retType, argTypes, nativeFunctionOptions)
        const wrapper = function () {
            const args = [impl, ...Array.from(arguments)]
            return fn(...args)
        }
        const cb = new NativeCallback(wrapper, retType, argTypes, abi)
        let isWritten = false
        
        const doWrite = () => {
            isWritten = true
            this._keepNativeCb[symName] = cb
            sym.relocPtr!.writePointer(cb)
            sym.hook = cb
            help.$info(`[attachSymbol] ${symName} [${impl}] => [${cb}]`)
        }

        const rangeDetail = Process.findRangeByAddress(sym.relocPtr)
        if (rangeDetail) {
            if(rangeDetail.protection.indexOf('w') === -1) {
                const prots = rangeDetail.protection[0] + 'w' + rangeDetail.protection[2]
                Memory.protect(sym.relocPtr, Process.pointerSize, prots)
            }
            doWrite()
            // FIXME: changeback
        }
        // fallback
        if(!isWritten) {
            for (let prot of ['rwx', 'rw', 'rx']) {
                if (Memory.protect(sym.relocPtr, Process.pointerSize, prot)) {
                    doWrite()
                    break
                }
            }
        }
        return isWritten
    }

    findSymbol(symName: string): Sym | undefined {
        let sym
        if(this.dynSymbols !== null) {
            sym = this.dynSymbols.find(sym => sym.name === symName)
        }
        if (!sym && this.symtab !== null) {
            return this.symtab.find(sym => sym.name === symName)   
        }
        return sym
    }

    fromAddress(addr: NativePointer) {
        if(this.base == null) {
            return null
        }
        const base = this.module.base
        const endAddr = this.base.add(this.module.size)
        if (this.isMyAddr(addr)) {
            return `${addr} ${this.module.name}!${addr.sub(base)}`
        }
        return addr
    }

    isMyAddr(addr: NativePointer) {
        return addr >= this.base && addr < this.base.add(this.size)
    }

    getSegment(seg: string): Shdr | null {
        if (this.shdrs) {
            return this.shdrs.find(shdr => shdr.name === seg) || null
        }
        return null
    }

    dump(tag: string) {
        let buff: ArrayBuffer | null = null
        help.memoryReadDo(this.base, this.size, (makeReadable, makeRecovery) => {
            makeReadable()
            buff = this.base.readByteArray(this.size)
            makeRecovery()
        })
        if (buff) {
            help.saveFile(tag, buff, 'wb', saveFileSource.elfModule)
        }
    }

}


export { ElfModuleX }


export class ElfFileFixer implements ElfModuleFixer {
    path: string

    private modx?: ElfModuleX
    private fileBytes?: ArrayBuffer
    private ehdr?: Ehdr
    private phdrs?: Phdr[]
    private shdrs?: Shdr[]
    private strtab?: { [key: number]: string }

    private shstrtabShdr?: Shdr

    constructor(path: string) {
        this.path = path
    }

    getFilePtr(): ArrayPointer {
        if(!this.fileBytes) {
            this.fileBytes = help.readFile(this.path)
        }
        return new ArrayPointer(0, this.fileBytes!)
    }
    
    ensureEhdr() {
        if(!this.ehdr) {
            this.ehdr = this.readEhdr()
        }
        help.assert(this.ehdr)
    }

    ensurePhdrs() {
        if (!this.phdrs) {
            this.phdrs = this.readPhdrs()
        }
        help.assert(this.phdrs)
    }

    ensureShdrs(){
        if (!this.shdrs) {
            this.shdrs = this.readShdrs()
        }
        help.assert(this.shdrs)
    }

    ensureStrtab() {
        if (!this.strtab) {
            this.strtab = this.readStrtab()
        }
        help.assert(this.shdrs)
    }

    readEhdr() {
        const base = this.getFilePtr()
        const magic = Array.from(new Uint8Array(Elf_Ehdr.EI_Magic(base)))
        const FIXED_MAGIC = [0x7f, 0x45, 0x4c, 0x46]
        if (!FIXED_MAGIC.every((v, i) => v == magic[i])) {
            throw new Error(`error magic[${magic}]`)
        }
        const ei_class = Elf_Ehdr.EI_CLASS(base)
        const structOf = ei_class === 1 ? Elf_Ehdr.B32 : Elf_Ehdr.B64
        return {
            ei_class: ei_class,
            e_type: structOf.E_Type(base),
            e_phoff: structOf.E_Phoff(base),
            e_shoff: structOf.E_Shoff(base),
            e_phnum: structOf.E_Phnum(base),
            e_shnum: structOf.E_Shnum(base),
            e_shstrndx: structOf.E_Shstrndx(base),
        }
    }

    readPhdrs(): Phdr[] {
        this.ensureEhdr()

        const fileBase = this.getFilePtr()
        const ehdr = this.ehdr!
        const base = fileBase.add(ehdr.e_phoff)
        const structOf = ehdr.ei_class === 1 ? Elf_Phdr.B32 : Elf_Phdr.B64
        const tables: Phdr[] = []
        for (let i = 0; i < ehdr.e_phnum; i++) {
            const cellBase = base.add(i * structOf.SIZE)
            tables.push({
                p_type: structOf.P_Type(cellBase),
                p_offset: structOf.P_Offset(cellBase),
                p_vaddr: structOf.P_Vaddr(cellBase),
                p_paddr: structOf.P_Paddr(cellBase),
                p_filesz: structOf.P_Filesz(cellBase),
                p_memsz: structOf.P_Memsz(cellBase),
                p_align: structOf.P_Align(cellBase),
            })
        }
        return tables
    }

    readShdrs() {
        this.ensureEhdr()
        this.ensurePhdrs()

        const fileBase = this.getFilePtr()
        const ehdr = this.ehdr!
        const base = fileBase.add(ehdr.e_shoff)

        const structOf = ehdr.ei_class === 1 ? Elf_Shdr.B32 : Elf_Shdr.B64
        const tables: Shdr[] = []
        for (let i = 0; i < ehdr.e_shnum; i++) {
            const cellBase = base.add(i * structOf.SIZE)
            const sh_addr = structOf.Sh_Addr(cellBase)
            const sh_size = structOf.Sh_Size(cellBase)
            tables.push({
                name: null,
                base: this.modx!.base.add(sh_addr),
                size: sh_size,
                
                sh_name: structOf.Sh_Name(cellBase),
                sh_type: structOf.Sh_Type(cellBase),
                sh_addr: structOf.Sh_Addr(cellBase),
                sh_offset: structOf.Sh_Offset(cellBase),
                sh_size: structOf.Sh_Size(cellBase),
                sh_link: structOf.Sh_Link(cellBase),
                sh_info: structOf.Sh_Info(cellBase),
                sh_addralign: structOf.Sh_Addralign(cellBase),
                sh_entsize: structOf.Sh_Entsize(cellBase),
            })
        }
        this.shdrs = tables
        // fill name
        for(let v of tables) {
            v.name = this.getShstrtabString(v.sh_name)
        }

        return tables
    }

    readStrtab(): { [key: number]: string } | undefined {
        this.ensureEhdr()
        this.ensurePhdrs()
        this.ensureShdrs()

        const shdr = this.shdrs!.find(shdr => this.getShstrtabString(shdr.sh_name) === '.strtab')
        if (!shdr) {
            return
        }
        const fileBase = this.getFilePtr()
        const strbase = fileBase.add(shdr.sh_offset)
        const strend = strbase.add(shdr.sh_size)
        const strtabs: { [key: number]: string } = {}
        let next = strbase
        while (next < strend) {
            const off = Number(next.sub(strbase)) 
            const cstr = next.readCString()
            next = next.add(cstr.length + 1)
            strtabs[off] = cstr
        }
        return strtabs
    }

    getShstrtabString(nameOff: number): string {
        if (!this.shstrtabShdr) {
            const shdr = this.shdrs![this.ehdr!.e_shstrndx]
            this.shstrtabShdr = shdr
        }
        const fileBase = this.getFilePtr()
        return fileBase.add(this.shstrtabShdr.sh_offset).add(nameOff).readCString()
    }

    getSymString(nameIDX: number): string {
        return this.strtab![nameIDX]
    }
    

    readSymtab(): Sym[] | null{
        this.ensureEhdr()
        this.ensurePhdrs()
        this.ensureShdrs()
        this.ensureStrtab()

        const shdr = this.shdrs!.find(shdr => this.getShstrtabString(shdr.sh_name) === '.symtab')
        if(!shdr) {
            return null
        }
        const fileBase = this.getFilePtr()
        const ehdr = this.ehdr!
        const structOf = ehdr.ei_class === 1 ? Elf_Sym.B32 : Elf_Sym.B64

        const base = fileBase.add(shdr.sh_offset)
        const num = shdr.sh_size / structOf.SIZE
        const symbols: Sym[] = []
        for (let i = 0; i < num; i++) {
            const cellBase = base.add(i * structOf.SIZE)
            const nameIDX = structOf.St_Name(cellBase)
            const name = this.getSymString(nameIDX)
            let implPtr = ptr(structOf.St_Value(cellBase))
            const st_info = structOf.St_Info(cellBase)
            const st_shndx = structOf.St_Shndx(cellBase)
            const st_other = structOf.St_Other(cellBase)

            if ([SYM_SHNDX.SHN_UNDEF, SYM_SHNDX.SHN_ABS].indexOf(st_shndx) === -1) {
                if ([SYM_INFO_TYPE.STT_FUNC, SYM_INFO_TYPE.STT_OBJECT].indexOf(st_info & 0xF) !== -1) {
                    if (!this.modx?.isMyAddr(implPtr)) {
                        implPtr = this.modx!.module.base.add(implPtr)
                    }
                }
            }
            const sym: Sym = {
                name: name,
                relocPtr: null,
                hook: null,
                implPtr: implPtr,
                linked: true,

                st_name: nameIDX,
                st_info: st_info,
                st_other: st_other,
                st_shndx: st_shndx,
                st_value: implPtr,
                st_size: structOf.St_Size(cellBase),
            }
            symbols.push(sym)
        }
        return symbols
    }

    fixShdrs(modx: ElfModuleX): boolean {
        this.modx = modx
        try {
            const shdrs = this.readShdrs()
            if(shdrs){
                this.strtab = this.readStrtab()  
                const symtab = this.readSymtab()
                
                modx.shdrs = shdrs
                modx.strtab = this.strtab || null
                modx.symtab = symtab
                return true
            }
        }catch(e) {
            console.error(`[ElfFileFixer]fixShdrs name[${modx.name}] e[${e}]`)
        }

        return false
    }

}

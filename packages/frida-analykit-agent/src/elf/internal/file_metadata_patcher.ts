import type { Ehdr, Phdr, Shdr, Sym } from "../struct.js"
import { Elf_Ehdr, Elf_Phdr, Elf_Shdr, Elf_Sym } from "../struct.js"
import { ELF_MAGIC_BYTES, SHN_ABS, SHN_UNDEF, STT_FUNC, STT_OBJECT } from "./abi.js"
import { help } from "../../helper/index.js"
import { ArrayPointer } from "../../internal/binary/array_pointer.js"
import type { ElfModuleX } from "../module.js"
import type { ElfModuleMetadataPatcher } from "./metadata_patcher.js"

export class ElfFileMetadataPatcher implements ElfModuleMetadataPatcher {
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
        if (!this.fileBytes) {
            this.fileBytes = help.fs.read(this.path)
        }
        return new ArrayPointer(0, this.fileBytes)
    }

    ensureEhdr() {
        if (!this.ehdr) {
            this.ehdr = this.readEhdr()
        }
        help.runtime.assert(this.ehdr)
    }

    ensurePhdrs() {
        if (!this.phdrs) {
            this.phdrs = this.readPhdrs()
        }
        help.runtime.assert(this.phdrs)
    }

    ensureShdrs() {
        if (!this.shdrs) {
            this.shdrs = this.readShdrs()
        }
        help.runtime.assert(this.shdrs)
    }

    ensureStrtab() {
        if (!this.strtab) {
            this.strtab = this.readStrtab()
        }
        help.runtime.assert(this.shdrs)
    }

    readEhdr() {
        const base = this.getFilePtr()
        const magic = Array.from(new Uint8Array(Elf_Ehdr.EI_Magic(base)))
        if (!ELF_MAGIC_BYTES.every((value, index) => value === magic[index])) {
            throw new Error(`error magic[${magic}]`)
        }
        const ei_class = Elf_Ehdr.EI_CLASS(base)
        const structOf = ei_class === 1 ? Elf_Ehdr.B32 : Elf_Ehdr.B64
        return {
            ei_class,
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
                sh_addr: sh_addr,
                sh_offset: structOf.Sh_Offset(cellBase),
                sh_size: sh_size,
                sh_link: structOf.Sh_Link(cellBase),
                sh_info: structOf.Sh_Info(cellBase),
                sh_addralign: structOf.Sh_Addralign(cellBase),
                sh_entsize: structOf.Sh_Entsize(cellBase),
            })
        }
        this.shdrs = tables
        for (const section of tables) {
            section.name = this.getShstrtabString(section.sh_name)
        }

        return tables
    }

    readStrtab(): { [key: number]: string } | undefined {
        this.ensureEhdr()
        this.ensurePhdrs()
        this.ensureShdrs()

        const shdr = this.shdrs!.find((section) => this.getShstrtabString(section.sh_name) === ".strtab")
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
            this.shstrtabShdr = this.shdrs![this.ehdr!.e_shstrndx]
        }
        const fileBase = this.getFilePtr()
        return fileBase.add(this.shstrtabShdr.sh_offset).add(nameOff).readCString()
    }

    getSymString(nameIDX: number): string {
        return this.strtab![nameIDX]
    }

    readSymtab(): Sym[] | null {
        this.ensureEhdr()
        this.ensurePhdrs()
        this.ensureShdrs()
        this.ensureStrtab()

        const shdr = this.shdrs!.find((section) => this.getShstrtabString(section.sh_name) === ".symtab")
        if (!shdr) {
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

            if ([SHN_UNDEF, SHN_ABS].indexOf(st_shndx) === -1) {
                if ([STT_FUNC, STT_OBJECT].indexOf(st_info & 0xF) !== -1) {
                    if (!this.modx?.isMyAddr(implPtr)) {
                        implPtr = this.modx!.module.base.add(implPtr)
                    }
                }
            }
            symbols.push({
                name,
                relocPtr: null,
                hook: null,
                implPtr,
                linked: true,

                st_name: nameIDX,
                st_info,
                st_other,
                st_shndx,
                st_value: implPtr,
                st_size: structOf.St_Size(cellBase),
            })
        }
        return symbols
    }

    // This is a best-effort metadata patcher for well-formed on-disk ELFs.
    // It fills section/symbol tables for loaded modules, but does not try to
    // recover packed or heavily corrupted binaries.
    patch(modx: ElfModuleX): boolean {
        this.modx = modx
        try {
            const shdrs = this.readShdrs()
            if (shdrs) {
                this.strtab = this.readStrtab()
                const symtab = this.readSymtab()

                modx.shdrs = shdrs
                modx.strtab = this.strtab || null
                modx.symtab = symtab
                return true
            }
        } catch (e) {
            console.error(`[ElfFileMetadataPatcher] patch name[${modx.name}] e[${e}]`)
        }

        return false
    }
}

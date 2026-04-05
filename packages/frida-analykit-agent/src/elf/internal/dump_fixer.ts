/* 参考来源: https://github.com/maiyao1988/elf-dump-fix/blob/master/app/jni/ElfFixSection/fix.cpp */

import {
    DyntabTag,
    EI_OSABI_SYSV,
    ELF_IDENT_OFFSETS,
    ELF_MAGIC_BYTES,
    ET_DYN,
    EV_CURRENT,
    PF_X,
    PT_DYNAMIC,
    PT_LOAD,
    PT_LOPROC,
    R_386_RELATIVE,
    R_AARCH64_RELATIVE,
    R_ARM_RELATIVE,
    R_X86_64_RELATIVE,
    SHF_ALLOC,
    SHF_EXECINSTR,
    SHF_WRITE,
    SHT_DYNAMIC,
    SHT_DYNSYM,
    SHT_FINI_ARRAY,
    SHT_HASH,
    SHT_INIT_ARRAY,
    SHT_NOBITS,
    SHT_NULL,
    SHT_PROGBITS,
    SHT_REL,
    SHT_RELA,
    SHT_STRTAB,
    SHN_ABS,
    SHN_UNDEF,
    STT_COMMON,
    STT_FILE,
    STT_FUNC,
    STT_GNU_IFUNC,
    STT_HIOS,
    STT_HIPROC,
    STT_LOOS,
    STT_LOPROC,
    STT_OBJECT,
    STT_NOTYPE,
    STT_SECTION,
    STT_TLS,
    elfMachineForProcessArch,
    getElfAbiLayout,
    type ElfAbiLayout,
} from "./abi.js"

type ElfDumpHeaderSnapshot = {
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

type ElfDumpFixStage = {
    name: string
    detail: string
}

type ElfDumpFixStageName =
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

type ElfLayout = {
    eiClass: ElfAbiLayout["eiClass"]
    is32: boolean
    pointerSize: 4 | 8
    ehdrSize: number
    phdrSize: number
    shdrSize: number
    dynSize: number
    symSize: number
    header: {
        eType: number
        eMachine: number
        eVersion: number
        eEntry: number
        ePhoff: number
        eShoff: number
        ePhnum: number
        eShentsize: number
        eShnum: number
        eShstrndx: number
    }
    phdr: {
        pType: number
        pFlags: number
        pOffset: number
        pVaddr: number
        pPaddr: number
        pFilesz: number
        pMemsz: number
        pAlign: number
    }
    shdr: {
        shName: number
        shType: number
        shFlags: number
        shAddr: number
        shOffset: number
        shSize: number
        shLink: number
        shInfo: number
        shAddralign: number
        shEntsize: number
    }
    sym: {
        stName: number
        stValue: number
        stSize: number
        stInfo: number
        stOther: number
        stShndx: number
    }
    readAddr: (view: DataView, offset: number) => number
    writeAddr: (view: DataView, offset: number, value: number) => void
}

type ProgramHeader = {
    index: number
    offset: number
    pType: number
    pFlags: number
    pOffset: number
    pVaddr: number
    pPaddr: number
    pFilesz: number
    pMemsz: number
    pAlign: number
}

type SectionHeader = {
    shName: number
    shType: number
    shFlags: number
    shAddr: number
    shOffset: number
    shSize: number
    shLink: number
    shInfo: number
    shAddralign: number
    shEntsize: number
}

const SECTION_SLOT = {
    NONE: 0,
    DYNSYM: 1,
    DYNSTR: 2,
    HASH: 3,
    RELDYN: 4,
    RELPLT: 5,
    PLT: 6,
    TEXT: 7,
    ARMEXIDX: 8,
    FINIARRAY: 9,
    INITARRAY: 10,
    DYNAMIC: 11,
    GOT: 12,
    DATA: 13,
    BSS: 14,
    SHSTRTAB: 15,
} as const

const SECTION_SLOT_COUNT = 16
const SHSTRTAB_CONTENT =
    "\0.dynsym\0.dynstr\0.hash\0.rel.dyn\0.rel.plt\0.plt\0.text\0.ARM.exidx\0.fini_array\0.init_array\0.dynamic\0.got\0.data\0.bss\0.shstrtab\0.rela.dyn\0.rela.plt\0"

function mustBeElf(raw: Uint8Array): void {
    if (raw.length < 16 || !ELF_MAGIC_BYTES.every((value, index) => raw[index] === value)) {
        throw new Error("[ElfDumpFixer] input is not an ELF image")
    }
}

function alignUp(value: number, alignment: number): number {
    if (alignment <= 0) {
        return value
    }
    const mask = alignment - 1
    return (value + mask) & ~mask
}

function sectionNameOffset(name: string): number {
    const token = `${name}\0`
    const offset = SHSTRTAB_CONTENT.indexOf(token)
    if (offset === -1) {
        throw new Error(`[ElfDumpFixer] shstrtab entry not found: ${name}`)
    }
    return offset
}

function zeroSection(): SectionHeader {
    return {
        shName: 0,
        shType: SHT_NULL,
        shFlags: 0,
        shAddr: 0,
        shOffset: 0,
        shSize: 0,
        shLink: 0,
        shInfo: 0,
        shAddralign: 0,
        shEntsize: 0,
    }
}

function getLayout(raw: Uint8Array): ElfLayout {
    const abi = getElfAbiLayout(raw[ELF_IDENT_OFFSETS.eiClass])
    return {
        eiClass: abi.eiClass,
        is32: abi.is32,
        pointerSize: abi.pointerSize,
        ehdrSize: abi.ehdr.size,
        phdrSize: abi.phdr.size,
        shdrSize: abi.shdr.size,
        dynSize: abi.dyn.size,
        symSize: abi.sym.size,
        header: abi.ehdr.fields,
        phdr: abi.phdr.fields,
        shdr: abi.shdr.fields,
        sym: abi.sym.fields,
        readAddr(view, offset) {
            return abi.is32 ? view.getUint32(offset, true) : Number(view.getBigUint64(offset, true))
        },
        writeAddr(view, offset, value) {
            if (abi.is32) {
                view.setUint32(offset, value >>> 0, true)
                return
            }
            view.setBigUint64(offset, BigInt(value), true)
        },
    }
}

function readHeaderSnapshot(view: DataView, layout: ElfLayout): ElfDumpHeaderSnapshot {
    return {
        eiClass: layout.eiClass,
        eiOsabi: view.getUint8(7),
        eType: view.getUint16(layout.header.eType, true),
        eMachine: view.getUint16(layout.header.eMachine, true),
        eVersion: view.getUint32(layout.header.eVersion, true),
        eEntry: layout.readAddr(view, layout.header.eEntry),
        ePhoff: layout.readAddr(view, layout.header.ePhoff),
        eShoff: layout.readAddr(view, layout.header.eShoff),
        ePhnum: view.getUint16(layout.header.ePhnum, true),
        eShnum: view.getUint16(layout.header.eShnum, true),
        eShstrndx: view.getUint16(layout.header.eShstrndx, true),
    }
}

function parseProgramHeaders(view: DataView, layout: ElfLayout, header: ElfDumpHeaderSnapshot): ProgramHeader[] {
    const phdrs: ProgramHeader[] = []
    for (let index = 0; index < header.ePhnum; index++) {
        const offset = header.ePhoff + index * layout.phdrSize
        phdrs.push({
            index,
            offset,
            pType: view.getUint32(offset + layout.phdr.pType, true),
            pFlags: view.getUint32(offset + layout.phdr.pFlags, true),
            pOffset: layout.readAddr(view, offset + layout.phdr.pOffset),
            pVaddr: layout.readAddr(view, offset + layout.phdr.pVaddr),
            pPaddr: layout.readAddr(view, offset + layout.phdr.pPaddr),
            pFilesz: layout.readAddr(view, offset + layout.phdr.pFilesz),
            pMemsz: layout.readAddr(view, offset + layout.phdr.pMemsz),
            pAlign: layout.readAddr(view, offset + layout.phdr.pAlign),
        })
    }
    return phdrs
}

function readString(view: DataView, offset: number, end: number): string | null {
    if (offset < 0 || offset >= end) {
        return null
    }
    const bytes: number[] = []
    for (let cursor = offset; cursor < end; cursor++) {
        const value = view.getUint8(cursor)
        if (value === 0) {
            break
        }
        bytes.push(value)
    }
    return String.fromCharCode(...bytes)
}

function relocationType(view: DataView, layout: ElfLayout, entryOffset: number): number {
    if (layout.is32) {
        return view.getUint32(entryOffset + 4, true) & 0xff
    }
    return view.getUint32(entryOffset + 8, true)
}

function relocationOffset(view: DataView, layout: ElfLayout, entryOffset: number): number {
    return layout.readAddr(view, entryOffset)
}

function writeRelocationOffset(view: DataView, layout: ElfLayout, entryOffset: number, value: number): void {
    layout.writeAddr(view, entryOffset, value)
}

function getMemFlags(phdrs: ProgramHeader[], address: number): number {
    for (const phdr of phdrs) {
        const begin = phdr.pVaddr
        const end = begin + phdr.pMemsz
        if (address > begin && address < end) {
            return phdr.pFlags
        }
    }
    return 0
}

function detectDynSymCount(view: DataView, layout: ElfLayout, dynsymBase: number, dynstrBase: number, dynstrSize: number, imageSize: number): number {
    let symCount = 0
    const dynstrEnd = dynstrBase + dynstrSize
    while (dynsymBase + (symCount + 1) * layout.symSize <= imageSize) {
        const symOffset = dynsymBase + symCount * layout.symSize
        const nameOffset = view.getUint32(symOffset + layout.sym.stName, true)
        const symName = readString(view, dynstrBase + nameOffset, dynstrEnd)
        if (symName === null) {
            break
        }
        symCount++
    }
    return symCount
}

function isWithinDumpedImage(value: number, loadBias: number, imageSize: number): boolean {
    return value >= loadBias && value < loadBias + imageSize
}

function isOsOrProcessorSpecificSymbolType(type: number): boolean {
    return (type >= STT_LOOS && type <= STT_HIOS) || (type >= STT_LOPROC && type <= STT_HIPROC)
}

function isAddressBearingSymbolType(type: number): boolean {
    return type === STT_OBJECT || type === STT_FUNC || type === STT_SECTION
}

function fixSymbolTypes(
    recorder: ElfDumpFixRecorder,
    view: DataView,
    fixed: Uint8Array,
    layout: ElfLayout,
    phdrs: ProgramHeader[],
    dynsymBase: number,
    dynsymCount: number,
    loadBias: number,
    imageSize: number,
): void {
    for (let index = 0; index < dynsymCount; index++) {
        const symOffset = dynsymBase + index * layout.symSize
        const infoOffset = symOffset + layout.sym.stInfo
        const info = view.getUint8(infoOffset)
        const type = info & 0x0f
        if (type !== STT_NOTYPE) {
            continue
        }

        const symValue = layout.readAddr(view, symOffset + layout.sym.stValue)
        const sectionIndex = view.getUint16(symOffset + layout.sym.stShndx, true)
        if (
            symValue === 0
            || sectionIndex === SHN_UNDEF
            || sectionIndex === SHN_ABS
            || !isWithinDumpedImage(symValue, loadBias, imageSize)
        ) {
            continue
        }
        const bindBits = info & 0xf0
        let newType = STT_OBJECT
        const flags = getMemFlags(phdrs, symValue)
        if ((flags & PF_X) !== 0) {
            newType = STT_FUNC
        }
        const before = sliceBytes(fixed.buffer, infoOffset, 1)
        view.setUint8(infoOffset, bindBits | newType)
        recorder.recordSlotPatch("dynsym.st_info", 1, infoOffset, before, sliceBytes(fixed.buffer, infoOffset, 1))
    }
}

function fixDynSymBias(
    recorder: ElfDumpFixRecorder,
    view: DataView,
    fixed: Uint8Array,
    layout: ElfLayout,
    dynsymBase: number,
    dynsymCount: number,
    bias: number,
    imageSize: number,
): void {
    for (let index = 0; index < dynsymCount; index++) {
        const symOffset = dynsymBase + index * layout.symSize
        const info = view.getUint8(symOffset + layout.sym.stInfo)
        const type = info & 0x0f
        const sectionIndex = view.getUint16(symOffset + layout.sym.stShndx, true)
        const valueOffset = symOffset + layout.sym.stValue
        const currentValue = layout.readAddr(view, valueOffset)
        if (
            sectionIndex === SHN_UNDEF
            || sectionIndex === SHN_ABS
            || currentValue === 0
            || !isWithinDumpedImage(currentValue, bias, imageSize)
            || type === STT_TLS
            || type === STT_GNU_IFUNC
            || type === STT_COMMON
            || type === STT_FILE
            || type === STT_NOTYPE
            || isOsOrProcessorSpecificSymbolType(type)
            || !isAddressBearingSymbolType(type)
        ) {
            continue
        }
        const before = sliceBytes(fixed.buffer, valueOffset, layout.pointerSize)
        layout.writeAddr(view, valueOffset, currentValue - bias)
        recorder.recordSlotPatch("dynsym.st_value", layout.pointerSize, valueOffset, before, sliceBytes(fixed.buffer, valueOffset, layout.pointerSize))
    }
}

function fixRelocationOffsets(
    recorder: ElfDumpFixRecorder,
    view: DataView,
    fixed: Uint8Array,
    layout: ElfLayout,
    section: SectionHeader,
    bias: number,
    imageSize: number,
    slotName: string,
): void {
    if (section.shOffset <= 0 || section.shEntsize <= 0 || section.shSize <= 0) {
        return
    }

    const count = Math.floor(section.shSize / section.shEntsize)
    for (let index = 0; index < count; index++) {
        const entryOffset = section.shOffset + index * section.shEntsize
        const currentOffset = relocationOffset(view, layout, entryOffset)
        if (currentOffset < bias) {
            continue
        }
        const adjustedOffset = currentOffset - bias
        // Only rewrite relocation targets that can be mapped back into the dumped image.
        if (adjustedOffset < 0 || adjustedOffset >= imageSize || adjustedOffset === currentOffset) {
            continue
        }
        const before = sliceBytes(fixed.buffer, entryOffset, layout.pointerSize)
        writeRelocationOffset(view, layout, entryOffset, adjustedOffset)
        recorder.recordSlotPatch(slotName, layout.pointerSize, entryOffset, before, sliceBytes(fixed.buffer, entryOffset, layout.pointerSize))
    }
}

function fixRelativeRebase(
    recorder: ElfDumpFixRecorder,
    view: DataView,
    fixed: Uint8Array,
    layout: ElfLayout,
    section: SectionHeader,
    imageBase: number,
    imageSize: number,
    relativeTypes: ReadonlySet<number>,
): void {
    if (section.shOffset <= 0 || section.shEntsize <= 0 || section.shSize <= 0) {
        return
    }

    const count = Math.floor(section.shSize / section.shEntsize)
    for (let index = 0; index < count; index++) {
        const entryOffset = section.shOffset + index * section.shEntsize
        const type = relocationType(view, layout, entryOffset)
        if (!relativeTypes.has(type)) {
            continue
        }

        const targetOffset = relocationOffset(view, layout, entryOffset)
        if (targetOffset < 0 || targetOffset + layout.pointerSize > imageSize) {
            continue
        }

        const currentValue = layout.readAddr(view, targetOffset)
        if (currentValue >= imageBase) {
            const before = sliceBytes(fixed.buffer, targetOffset, layout.pointerSize)
            layout.writeAddr(view, targetOffset, currentValue - imageBase)
            recorder.recordSlotPatch("relative.targets", layout.pointerSize, targetOffset, before, sliceBytes(fixed.buffer, targetOffset, layout.pointerSize))
        }
    }
}

function writeSectionHeader(view: DataView, layout: ElfLayout, baseOffset: number, section: SectionHeader): void {
    view.setUint32(baseOffset + layout.shdr.shName, section.shName, true)
    view.setUint32(baseOffset + layout.shdr.shType, section.shType, true)
    layout.writeAddr(view, baseOffset + layout.shdr.shFlags, section.shFlags)
    layout.writeAddr(view, baseOffset + layout.shdr.shAddr, section.shAddr)
    layout.writeAddr(view, baseOffset + layout.shdr.shOffset, section.shOffset)
    layout.writeAddr(view, baseOffset + layout.shdr.shSize, section.shSize)
    view.setUint32(baseOffset + layout.shdr.shLink, section.shLink, true)
    view.setUint32(baseOffset + layout.shdr.shInfo, section.shInfo, true)
    layout.writeAddr(view, baseOffset + layout.shdr.shAddralign, section.shAddralign)
    layout.writeAddr(view, baseOffset + layout.shdr.shEntsize, section.shEntsize)
}

function formatHex(value: number): string {
    return `0x${value.toString(16)}`
}

function sliceBytes(source: ArrayBufferLike, offset: number, size: number): Uint8Array {
    return new Uint8Array(source, offset, size).slice()
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
    if (left.byteLength !== right.byteLength) {
        return false
    }
    for (let index = 0; index < left.byteLength; index++) {
        if (left[index] !== right[index]) {
            return false
        }
    }
    return true
}

function bytesToHex(bytes: Uint8Array): string {
    let output = ""
    for (const value of bytes) {
        output += value.toString(16).padStart(2, "0")
    }
    return output
}

function bytesToScalarHex(bytes: Uint8Array): string {
    let value = 0n
    for (let index = 0; index < bytes.byteLength; index++) {
        value |= BigInt(bytes[index] ?? 0) << BigInt(index * 8)
    }
    return `0x${value.toString(16).padStart(Math.max(bytes.byteLength * 2, 1), "0")}`
}

type StageRecorderState = {
    name: ElfDumpFixStageName
    detail: string
    patches: ElfDumpFixupPatch[]
    slotPatches: Map<string, ElfDumpFixupSlotPatch>
}

class ElfDumpFixRecorder {
    private readonly stages: ElfDumpFixupStage[] = []
    private current: StageRecorderState | null = null

    beginStage(name: ElfDumpFixStageName, detail: string): void {
        this.finishStage()
        this.current = {
            name,
            detail,
            patches: [],
            slotPatches: new Map(),
        }
    }

    finishStage(): void {
        if (this.current === null) {
            return
        }
        this.stages.push({
            name: this.current.name,
            detail: this.current.detail,
            patches: this.current.patches,
        })
        this.current = null
    }

    recordFieldPatch(name: string, offset: number, width: number, before: Uint8Array, after: Uint8Array): void {
        if (before.byteLength !== width || after.byteLength !== width || bytesEqual(before, after)) {
            return
        }
        this.requireStage().patches.push({
            t: "f",
            n: name,
            o: offset,
            w: width,
            b: bytesToScalarHex(before),
            a: bytesToScalarHex(after),
        })
    }

    recordSlotPatch(name: string, width: number, offset: number, before: Uint8Array, after: Uint8Array): void {
        if (before.byteLength !== width || after.byteLength !== width || bytesEqual(before, after)) {
            return
        }
        const stage = this.requireStage()
        const key = `${name}:${width}`
        let patch = stage.slotPatches.get(key)
        if (patch === undefined) {
            patch = {
                t: "s",
                n: name,
                w: width,
                v: [],
            }
            stage.slotPatches.set(key, patch)
            stage.patches.push(patch)
        }
        patch.v.push([offset, bytesToScalarHex(before), bytesToScalarHex(after)])
    }

    recordBlockPatch(name: string, offset: number, replacedRawSize: number, data: Uint8Array): void {
        if (replacedRawSize === 0 && data.byteLength === 0) {
            return
        }
        this.requireStage().patches.push({
            t: "x",
            n: name,
            o: offset,
            r: replacedRawSize,
            x: bytesToHex(data),
        })
    }

    build(rawSize: number, fixedSize: number): ElfDumpFixupFile {
        this.finishStage()
        return {
            version: 2,
            strategy: "raw-to-fixed-staged-v2",
            raw_size: rawSize,
            fixed_size: fixedSize,
            stages: this.stages,
        }
    }

    private requireStage(): StageRecorderState {
        if (this.current === null) {
            throw new Error("[ElfDumpFixer] patch recorded without an active stage")
        }
        return this.current
    }
}

function recordWriteField(
    recorder: ElfDumpFixRecorder,
    fixed: Uint8Array,
    offset: number,
    width: number,
    name: string,
    writer: () => void,
): void {
    const before = sliceBytes(fixed.buffer, offset, width)
    writer()
    recorder.recordFieldPatch(name, offset, width, before, sliceBytes(fixed.buffer, offset, width))
}

function isWithinLoadSegment(phdrs: ProgramHeader[], value: number): boolean {
    for (const phdr of phdrs) {
        if (phdr.pType !== PT_LOAD) {
            continue
        }
        const begin = phdr.pVaddr
        const end = begin + Math.max(phdr.pFilesz, phdr.pMemsz)
        if (value >= begin && value < end) {
            return true
        }
    }
    return false
}

function normalizeEntryValue(
    entry: number,
    phdrs: ProgramHeader[],
    options: {
        moduleBase: NativePointer
        moduleSize: number
        loadBias: number
    },
): {
    value: number
    detail: string
} {
    if (entry === 0) {
        return {
            value: 0,
            detail: "kept zero e_entry because the dumped image did not expose a usable entry point",
        }
    }

    const moduleBase = Number(options.moduleBase)
    const moduleEnd = moduleBase + options.moduleSize
    let candidate: number | null = null
    let source: string | null = null

    if (entry >= moduleBase && entry < moduleEnd) {
        candidate = entry - moduleBase
        source = "runtime-base"
    } else if (entry >= options.loadBias) {
        candidate = entry - options.loadBias
        source = "load-bias"
    }

    if (candidate !== null && isWithinLoadSegment(phdrs, candidate)) {
        return {
            value: candidate,
            detail: `normalized e_entry from ${source} (${formatHex(entry)} -> ${formatHex(candidate)})`,
        }
    }

    if (isWithinLoadSegment(phdrs, entry)) {
        return {
            value: entry,
            detail: candidate !== null
                ? `kept rebased e_entry ${formatHex(entry)} because candidate ${formatHex(candidate)} was outside normalized PT_LOAD ranges`
                : `kept rebased e_entry ${formatHex(entry)} because it already pointed inside the normalized image`,
        }
    }

    return {
        value: 0,
        detail: candidate !== null
            ? `reset e_entry to 0 because candidate ${formatHex(candidate)} from ${source} was outside normalized PT_LOAD ranges`
            : `reset e_entry to 0 because ${formatHex(entry)} did not map into the normalized PT_LOAD ranges`,
    }
}

function previewFinalization(
    view: DataView,
    layout: ElfLayout,
    options: {
        moduleBase: NativePointer
        moduleSize: number
        loadBias: number
    },
): {
    headerAfter: ElfDumpHeaderSnapshot
    entryDetail: string
} {
    const headerCurrent = readHeaderSnapshot(view, layout)
    const phdrs = parseProgramHeaders(view, layout, headerCurrent)
    const entry = normalizeEntryValue(headerCurrent.eEntry, phdrs, options)
    return {
        headerAfter: {
            ...headerCurrent,
            eiOsabi: EI_OSABI_SYSV,
            eType: ET_DYN,
            eMachine: elfMachineForProcessArch(Process.arch),
            eVersion: EV_CURRENT,
            eEntry: entry.value,
        },
        entryDetail: entry.detail,
    }
}

function bufferFromString(value: string): Uint8Array {
    const bytes: number[] = []
    for (let index = 0; index < value.length; index++) {
        bytes.push(value.charCodeAt(index) & 0xff)
    }
    return Uint8Array.from(bytes)
}

function dynamicTagName(tag: number): string {
    switch (tag) {
        case DyntabTag.DT_SYMTAB:
            return "DT_SYMTAB"
        case DyntabTag.DT_STRTAB:
            return "DT_STRTAB"
        case DyntabTag.DT_HASH:
            return "DT_HASH"
        case DyntabTag.DT_REL:
            return "DT_REL"
        case DyntabTag.DT_RELA:
            return "DT_RELA"
        case DyntabTag.DT_JMPREL:
            return "DT_JMPREL"
        case DyntabTag.DT_FINI_ARRAY:
            return "DT_FINI_ARRAY"
        case DyntabTag.DT_INIT_ARRAY:
            return "DT_INIT_ARRAY"
        case DyntabTag.DT_PLTGOT:
            return "DT_PLTGOT"
        default:
            return `DT_${tag}`
    }
}

function finalizeFixedElfForAnalysis(
    recorder: ElfDumpFixRecorder,
    fixedBytes: Uint8Array,
    fixed: ArrayBuffer,
    options: {
        moduleBase: NativePointer
        moduleSize: number
        loadBias: number
    },
): {
    headerAfter: ElfDumpHeaderSnapshot
} {
    mustBeElf(fixedBytes)
    const layout = getLayout(fixedBytes)
    const view = new DataView(fixed)
    const preview = previewFinalization(view, layout, options)

    const detail = `${preview.entryDetail}; normalized minimal ELF header fields for IDA and generic ELF tooling`
    recorder.beginStage("header-finalize", detail)
    recordWriteField(recorder, fixedBytes, layout.header.eEntry, layout.pointerSize, "ehdr.e_entry", () => {
        layout.writeAddr(view, layout.header.eEntry, preview.headerAfter.eEntry)
    })
    recordWriteField(recorder, fixedBytes, ELF_IDENT_OFFSETS.eiOsabi, 1, "ehdr.ei_osabi", () => {
        view.setUint8(ELF_IDENT_OFFSETS.eiOsabi, EI_OSABI_SYSV)
    })
    recordWriteField(
        recorder,
        fixedBytes,
        ELF_IDENT_OFFSETS.identPaddingStart,
        ELF_IDENT_OFFSETS.identPaddingEnd - ELF_IDENT_OFFSETS.identPaddingStart,
        "ehdr.e_ident_padding",
        () => {
            for (let index = ELF_IDENT_OFFSETS.identPaddingStart; index < ELF_IDENT_OFFSETS.identPaddingEnd; index++) {
                view.setUint8(index, 0)
            }
        },
    )
    recordWriteField(recorder, fixedBytes, layout.header.eType, 2, "ehdr.e_type", () => {
        view.setUint16(layout.header.eType, ET_DYN, true)
    })
    recordWriteField(recorder, fixedBytes, layout.header.eMachine, 2, "ehdr.e_machine", () => {
        view.setUint16(layout.header.eMachine, elfMachineForProcessArch(Process.arch), true)
    })
    recordWriteField(recorder, fixedBytes, layout.header.eVersion, 4, "ehdr.e_version", () => {
        view.setUint32(layout.header.eVersion, EV_CURRENT, true)
    })
    recorder.finishStage()

    return {
        headerAfter: readHeaderSnapshot(view, layout),
    }
}

export function buildFixedElfForAnalysis(
    raw: ArrayBuffer,
    options: { moduleBase: NativePointer; moduleSize: number },
): ElfDumpBuildResult {
    const rawBytes = new Uint8Array(raw)
    mustBeElf(rawBytes)

    const layout = getLayout(rawBytes)
    const shstrtabBytes = bufferFromString(SHSTRTAB_CONTENT)
    const rawSize = raw.byteLength
    const sectionTableOffset = rawSize + shstrtabBytes.byteLength
    const fixed = new Uint8Array(rawSize + shstrtabBytes.byteLength + layout.shdrSize * SECTION_SLOT_COUNT)
    fixed.set(rawBytes, 0)
    const fixedView = new DataView(fixed.buffer)
    const headerBefore = readHeaderSnapshot(fixedView, layout)
    const originalPhdrs = parseProgramHeaders(fixedView, layout, headerBefore)
    const phdrs = originalPhdrs.map((phdr) => ({ ...phdr }))
    const recorder = new ElfDumpFixRecorder()

    const loadBias = phdrs.find((phdr) => phdr.pType === PT_LOAD)?.pVaddr ?? 0
    const sections = Array.from({ length: SECTION_SLOT_COUNT }, () => zeroSection())

    let dynamicOffset = 0
    let dynamicSize = 0
    let lastLoad: ProgramHeader | null = null
    let execLoad: ProgramHeader | null = null

    recorder.beginStage(
        "phdr-rebase",
        "rebased PT_LOAD program headers from runtime virtual addresses into file-relative offsets",
    )
    for (const phdr of phdrs) {
        if (phdr.pType === PT_LOAD) {
            phdr.pVaddr -= loadBias
            phdr.pPaddr = phdr.pVaddr
            phdr.pOffset = phdr.pVaddr
            phdr.pFilesz = phdr.pMemsz
            recordWriteField(recorder, fixed, phdr.offset + layout.phdr.pOffset, layout.pointerSize, `phdr[${phdr.index}].p_offset`, () => {
                layout.writeAddr(fixedView, phdr.offset + layout.phdr.pOffset, phdr.pOffset)
            })
            recordWriteField(recorder, fixed, phdr.offset + layout.phdr.pVaddr, layout.pointerSize, `phdr[${phdr.index}].p_vaddr`, () => {
                layout.writeAddr(fixedView, phdr.offset + layout.phdr.pVaddr, phdr.pVaddr)
            })
            recordWriteField(recorder, fixed, phdr.offset + layout.phdr.pPaddr, layout.pointerSize, `phdr[${phdr.index}].p_paddr`, () => {
                layout.writeAddr(fixedView, phdr.offset + layout.phdr.pPaddr, phdr.pPaddr)
            })
            recordWriteField(recorder, fixed, phdr.offset + layout.phdr.pFilesz, layout.pointerSize, `phdr[${phdr.index}].p_filesz`, () => {
                layout.writeAddr(fixedView, phdr.offset + layout.phdr.pFilesz, phdr.pFilesz)
            })

            if (lastLoad === null || phdr.pVaddr + phdr.pMemsz >= lastLoad.pVaddr + lastLoad.pMemsz) {
                lastLoad = phdr
            }
            if (execLoad === null && (phdr.pFlags & PF_X) !== 0) {
                execLoad = phdr
            }
            continue
        }

        if (phdr.pType === PT_DYNAMIC) {
            const adjustedVaddr = phdr.pVaddr - loadBias
            sections[SECTION_SLOT.DYNAMIC] = {
                shName: sectionNameOffset(".dynamic"),
                shType: SHT_DYNAMIC,
                shFlags: SHF_WRITE | SHF_ALLOC,
                shAddr: adjustedVaddr,
                shOffset: adjustedVaddr,
                shSize: phdr.pMemsz,
                shLink: SECTION_SLOT.DYNSTR,
                shInfo: 0,
                shAddralign: layout.pointerSize,
                shEntsize: layout.dynSize,
            }
            dynamicOffset = adjustedVaddr
            dynamicSize = phdr.pMemsz
            continue
        }

        if (phdr.pType === PT_LOPROC || phdr.pType === PT_LOPROC + 1) {
            const adjustedVaddr = phdr.pVaddr - loadBias
            sections[SECTION_SLOT.ARMEXIDX] = {
                shName: sectionNameOffset(".ARM.exidx"),
                shType: PT_LOPROC,
                shFlags: SHF_ALLOC,
                shAddr: adjustedVaddr,
                shOffset: adjustedVaddr,
                shSize: phdr.pMemsz,
                shLink: SECTION_SLOT.TEXT,
                shInfo: 0,
                shAddralign: layout.pointerSize,
                shEntsize: 8,
            }
        }
    }
    recorder.finishStage()

    if (dynamicOffset <= 0 || dynamicSize <= 0) {
        throw new Error("[ElfDumpFixer] PT_DYNAMIC segment not found")
    }

    const dynamicCount = Math.floor(dynamicSize / layout.dynSize)
    let globalOffsetTable = 0
    let dynsymCount = 0
    let relpltCount = 0

    recorder.beginStage(
        "dynamic-rebase",
        "rebased dynamic pointers and rebuilt section descriptors from DT_* metadata",
    )
    for (let index = 0; index < dynamicCount; index++) {
        const entryOffset = dynamicOffset + index * layout.dynSize
        const tag = layout.readAddr(fixedView, entryOffset)
        const valueOffset = entryOffset + layout.pointerSize
        const value = layout.readAddr(fixedView, valueOffset)
        const fieldName = `dynamic[${index}].${dynamicTagName(tag)}.d_un`

        switch (tag) {
            case DyntabTag.DT_SYMTAB: {
                const adjusted = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, adjusted)
                })
                sections[SECTION_SLOT.DYNSYM] = {
                    shName: sectionNameOffset(".dynsym"),
                    shType: SHT_DYNSYM,
                    shFlags: SHF_ALLOC,
                    shAddr: adjusted,
                    shOffset: adjusted,
                    shSize: sections[SECTION_SLOT.DYNSYM].shSize,
                    shLink: SECTION_SLOT.DYNSTR,
                    shInfo: 1,
                    shAddralign: layout.pointerSize,
                    shEntsize: sections[SECTION_SLOT.DYNSYM].shEntsize,
                }
                break
            }
            case DyntabTag.DT_SYMENT:
                sections[SECTION_SLOT.DYNSYM].shEntsize = value
                break
            case DyntabTag.DT_STRTAB: {
                const adjusted = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, adjusted)
                })
                sections[SECTION_SLOT.DYNSTR] = {
                    shName: sectionNameOffset(".dynstr"),
                    shType: SHT_STRTAB,
                    shFlags: SHF_ALLOC,
                    shAddr: adjusted,
                    shOffset: adjusted,
                    shSize: sections[SECTION_SLOT.DYNSTR].shSize,
                    shLink: 0,
                    shInfo: 0,
                    shAddralign: 1,
                    shEntsize: 0,
                }
                break
            }
            case DyntabTag.DT_STRSZ:
                sections[SECTION_SLOT.DYNSTR].shSize = value
                break
            case DyntabTag.DT_HASH: {
                const adjusted = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, adjusted)
                })
                const nbucket = fixedView.getUint32(adjusted, true)
                const nchain = fixedView.getUint32(adjusted + 4, true)
                dynsymCount = nchain
                sections[SECTION_SLOT.HASH] = {
                    shName: sectionNameOffset(".hash"),
                    shType: SHT_HASH,
                    shFlags: SHF_ALLOC,
                    shAddr: adjusted,
                    shOffset: adjusted,
                    shSize: (nbucket + nchain + 2) * 4,
                    shLink: SECTION_SLOT.DYNSYM,
                    shInfo: 0,
                    shAddralign: layout.pointerSize,
                    shEntsize: 4,
                }
                break
            }
            case DyntabTag.DT_REL:
            case DyntabTag.DT_RELA: {
                const adjusted = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, adjusted)
                })
                sections[SECTION_SLOT.RELDYN].shName = sectionNameOffset(tag === DyntabTag.DT_REL ? ".rel.dyn" : ".rela.dyn")
                sections[SECTION_SLOT.RELDYN].shType = tag === DyntabTag.DT_REL ? SHT_REL : SHT_RELA
                sections[SECTION_SLOT.RELDYN].shFlags = SHF_ALLOC
                sections[SECTION_SLOT.RELDYN].shAddr = adjusted
                sections[SECTION_SLOT.RELDYN].shOffset = adjusted
                sections[SECTION_SLOT.RELDYN].shLink = SECTION_SLOT.DYNSYM
                sections[SECTION_SLOT.RELDYN].shInfo = 0
                sections[SECTION_SLOT.RELDYN].shAddralign = layout.pointerSize
                break
            }
            case DyntabTag.DT_RELSZ:
            case DyntabTag.DT_RELASZ:
                sections[SECTION_SLOT.RELDYN].shSize = value
                break
            case DyntabTag.DT_RELENT:
            case DyntabTag.DT_RELAENT:
                sections[SECTION_SLOT.RELDYN].shEntsize = value
                sections[SECTION_SLOT.RELPLT].shEntsize = value
                break
            case DyntabTag.DT_JMPREL: {
                const adjusted = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, adjusted)
                })
                sections[SECTION_SLOT.RELPLT].shName = sectionNameOffset(layout.is32 ? ".rel.plt" : ".rela.plt")
                sections[SECTION_SLOT.RELPLT].shType = layout.is32 ? SHT_REL : SHT_RELA
                sections[SECTION_SLOT.RELPLT].shFlags = SHF_ALLOC
                sections[SECTION_SLOT.RELPLT].shAddr = adjusted
                sections[SECTION_SLOT.RELPLT].shOffset = adjusted
                sections[SECTION_SLOT.RELPLT].shLink = SECTION_SLOT.DYNSYM
                sections[SECTION_SLOT.RELPLT].shInfo = SECTION_SLOT.PLT
                sections[SECTION_SLOT.RELPLT].shAddralign = layout.pointerSize
                break
            }
            case DyntabTag.DT_PLTRELSZ:
                sections[SECTION_SLOT.RELPLT].shSize = value
                break
            case DyntabTag.DT_FINI_ARRAY: {
                const adjusted = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, adjusted)
                })
                sections[SECTION_SLOT.FINIARRAY] = {
                    shName: sectionNameOffset(".fini_array"),
                    shType: SHT_FINI_ARRAY,
                    shFlags: SHF_WRITE | SHF_ALLOC,
                    shAddr: adjusted,
                    shOffset: adjusted,
                    shSize: sections[SECTION_SLOT.FINIARRAY].shSize,
                    shLink: 0,
                    shInfo: 0,
                    shAddralign: layout.pointerSize,
                    shEntsize: 0,
                }
                break
            }
            case DyntabTag.DT_FINI_ARRAYSZ:
                sections[SECTION_SLOT.FINIARRAY].shSize = value
                break
            case DyntabTag.DT_INIT_ARRAY: {
                const adjusted = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, adjusted)
                })
                sections[SECTION_SLOT.INITARRAY] = {
                    shName: sectionNameOffset(".init_array"),
                    shType: SHT_INIT_ARRAY,
                    shFlags: SHF_WRITE | SHF_ALLOC,
                    shAddr: adjusted,
                    shOffset: adjusted,
                    shSize: sections[SECTION_SLOT.INITARRAY].shSize,
                    shLink: 0,
                    shInfo: 0,
                    shAddralign: layout.pointerSize,
                    shEntsize: 0,
                }
                break
            }
            case DyntabTag.DT_INIT_ARRAYSZ:
                sections[SECTION_SLOT.INITARRAY].shSize = value
                break
            case DyntabTag.DT_PLTGOT:
                globalOffsetTable = value - loadBias
                recordWriteField(recorder, fixed, valueOffset, layout.pointerSize, fieldName, () => {
                    layout.writeAddr(fixedView, valueOffset, globalOffsetTable)
                })
                sections[SECTION_SLOT.GOT] = {
                    shName: sectionNameOffset(".got"),
                    shType: SHT_PROGBITS,
                    shFlags: SHF_WRITE | SHF_ALLOC,
                    shAddr: sections[SECTION_SLOT.DYNAMIC].shAddr + sections[SECTION_SLOT.DYNAMIC].shSize,
                    shOffset: sections[SECTION_SLOT.DYNAMIC].shAddr + sections[SECTION_SLOT.DYNAMIC].shSize,
                    shSize: 0,
                    shLink: 0,
                    shInfo: 0,
                    shAddralign: layout.pointerSize,
                    shEntsize: 0,
                }
                break
            default:
                break
        }
    }
    recorder.finishStage()

    relpltCount =
        sections[SECTION_SLOT.RELPLT].shSize > 0 && sections[SECTION_SLOT.RELPLT].shEntsize > 0
            ? Math.floor(sections[SECTION_SLOT.RELPLT].shSize / sections[SECTION_SLOT.RELPLT].shEntsize)
            : 0

    if (globalOffsetTable > 0 && lastLoad !== null) {
        const gotEntrySize = layout.pointerSize
        let gotEnd = globalOffsetTable + gotEntrySize * (relpltCount + 3)
        const gotEndTry = gotEnd & ~0x0fff
        if (globalOffsetTable < gotEndTry) {
            gotEnd = gotEndTry
        }

        sections[SECTION_SLOT.DATA] = {
            shName: sectionNameOffset(".data"),
            shType: SHT_PROGBITS,
            shFlags: SHF_WRITE | SHF_ALLOC,
            shAddr: alignUp(gotEnd, 0x1000),
            shOffset: alignUp(gotEnd, 0x1000),
            shSize: Math.max(lastLoad.pVaddr + lastLoad.pMemsz - alignUp(gotEnd, 0x1000), 0),
            shLink: 0,
            shInfo: 0,
            shAddralign: layout.pointerSize,
            shEntsize: 0,
        }

        if (gotEnd > sections[SECTION_SLOT.GOT].shAddr) {
            sections[SECTION_SLOT.GOT].shSize = gotEnd - sections[SECTION_SLOT.GOT].shAddr
        } else {
            sections[SECTION_SLOT.GOT].shAddr = globalOffsetTable
            sections[SECTION_SLOT.GOT].shOffset = globalOffsetTable
            sections[SECTION_SLOT.GOT].shSize = Math.max(gotEnd - globalOffsetTable, 0)
        }
    }

    if (dynsymCount === 0 && sections[SECTION_SLOT.DYNSYM].shOffset > 0 && sections[SECTION_SLOT.DYNSTR].shOffset > 0) {
        dynsymCount = detectDynSymCount(
            fixedView,
            layout,
            sections[SECTION_SLOT.DYNSYM].shOffset,
            sections[SECTION_SLOT.DYNSTR].shOffset,
            sections[SECTION_SLOT.DYNSTR].shSize,
            rawSize,
        )
    }

    recorder.beginStage(
        "dynsym-fixups",
        "conservatively inferred in-image STT_NOTYPE symbols and rebased address-bearing dynsym st_value entries into the fixed image",
    )
    // fix.cpp is the coverage reference for dynsym handling, but we intentionally keep
    // TLS/IFUNC/OS-specific and other non-address symbols intact instead of forcing them
    // into FUNC/OBJECT or blindly subtracting the load bias from every positive st_value.
    fixSymbolTypes(
        recorder,
        fixedView,
        fixed,
        layout,
        originalPhdrs,
        sections[SECTION_SLOT.DYNSYM].shOffset,
        dynsymCount,
        loadBias,
        rawSize,
    )
    sections[SECTION_SLOT.DYNSYM].shSize = dynsymCount * layout.symSize
    fixDynSymBias(
        recorder,
        fixedView,
        fixed,
        layout,
        sections[SECTION_SLOT.DYNSYM].shOffset,
        dynsymCount,
        loadBias,
        rawSize,
    )
    recorder.finishStage()

    const pltAlign = layout.is32 ? 4 : 16
    const pltEntrySize = layout.is32 ? 12 : 16
    const pltStart = alignUp(sections[SECTION_SLOT.RELPLT].shAddr + sections[SECTION_SLOT.RELPLT].shSize, pltAlign)
    sections[SECTION_SLOT.PLT] = {
        shName: sectionNameOffset(".plt"),
        shType: SHT_PROGBITS,
        shFlags: SHF_ALLOC | SHF_EXECINSTR,
        shAddr: pltStart,
        shOffset: pltStart,
        shSize: alignUp(20 + pltEntrySize * relpltCount, pltAlign),
        shLink: 0,
        shInfo: 0,
        shAddralign: pltAlign,
        shEntsize: 0,
    }

    const textStart = sections[SECTION_SLOT.PLT].shAddr + sections[SECTION_SLOT.PLT].shSize
    if (sections[SECTION_SLOT.ARMEXIDX].shAddr > textStart) {
        sections[SECTION_SLOT.TEXT] = {
            shName: sectionNameOffset(".text"),
            shType: SHT_PROGBITS,
            shFlags: SHF_ALLOC | SHF_EXECINSTR,
            shAddr: textStart,
            shOffset: textStart,
            shSize: sections[SECTION_SLOT.ARMEXIDX].shAddr - textStart,
            shLink: 0,
            shInfo: 0,
            shAddralign: 16,
            shEntsize: 0,
        }
    } else if (execLoad !== null) {
        const execEnd = execLoad.pVaddr + execLoad.pMemsz
        if (execEnd > textStart) {
            sections[SECTION_SLOT.TEXT] = {
                shName: sectionNameOffset(".text"),
                shType: SHT_PROGBITS,
                shFlags: SHF_ALLOC | SHF_EXECINSTR,
                shAddr: textStart,
                shOffset: textStart,
                shSize: execEnd - textStart,
                shLink: 0,
                shInfo: 0,
                shAddralign: 16,
                shEntsize: 0,
            }
        }
    }

    sections[SECTION_SLOT.SHSTRTAB] = {
        shName: sectionNameOffset(".shstrtab"),
        shType: SHT_STRTAB,
        shFlags: 0,
        shAddr: 0,
        shOffset: 0,
        shSize: SHSTRTAB_CONTENT.length,
        shLink: 0,
        shInfo: 0,
        shAddralign: 1,
        shEntsize: 0,
    }

    const relativeTypes = new Set([R_ARM_RELATIVE, R_AARCH64_RELATIVE, R_386_RELATIVE, R_X86_64_RELATIVE])

    recorder.beginStage(
        "relocation-fixups",
        "rebased relocation entry r_offset values into the dumped image and rewrote RELATIVE target slots to match the fixed image",
    )
    fixRelocationOffsets(
        recorder,
        fixedView,
        fixed,
        layout,
        sections[SECTION_SLOT.RELDYN],
        loadBias,
        rawSize,
        sections[SECTION_SLOT.RELDYN].shType === SHT_RELA ? "rela.dyn.r_offset" : "rel.dyn.r_offset",
    )
    fixRelocationOffsets(
        recorder,
        fixedView,
        fixed,
        layout,
        sections[SECTION_SLOT.RELPLT],
        loadBias,
        rawSize,
        sections[SECTION_SLOT.RELPLT].shType === SHT_RELA ? "rela.plt.r_offset" : "rel.plt.r_offset",
    )
    fixRelativeRebase(recorder, fixedView, fixed, layout, sections[SECTION_SLOT.RELDYN], Number(options.moduleBase), rawSize, relativeTypes)
    recorder.finishStage()

    recorder.beginStage(
        "section-rebuild",
        "appended shstrtab data and rebuilt the section header table for offline analysis tools",
    )
    fixed.set(shstrtabBytes, rawSize)
    sections[SECTION_SLOT.SHSTRTAB].shOffset = rawSize
    recorder.recordBlockPatch("shstrtab", rawSize, 0, shstrtabBytes)
    recordWriteField(recorder, fixed, layout.header.eShoff, layout.pointerSize, "ehdr.e_shoff", () => {
        layout.writeAddr(fixedView, layout.header.eShoff, sectionTableOffset)
    })
    recordWriteField(recorder, fixed, layout.header.eShentsize, 2, "ehdr.e_shentsize", () => {
        fixedView.setUint16(layout.header.eShentsize, layout.shdrSize, true)
    })
    recordWriteField(recorder, fixed, layout.header.eShnum, 2, "ehdr.e_shnum", () => {
        fixedView.setUint16(layout.header.eShnum, SECTION_SLOT_COUNT, true)
    })
    recordWriteField(recorder, fixed, layout.header.eShstrndx, 2, "ehdr.e_shstrndx", () => {
        fixedView.setUint16(layout.header.eShstrndx, SECTION_SLOT.SHSTRTAB, true)
    })

    const sectionTableBytes = new Uint8Array(layout.shdrSize * sections.length)
    const sectionTableView = new DataView(sectionTableBytes.buffer)
    for (let index = 0; index < sections.length; index++) {
        writeSectionHeader(sectionTableView, layout, index * layout.shdrSize, sections[index])
    }
    fixed.set(sectionTableBytes, sectionTableOffset)
    recorder.recordBlockPatch("section_headers", sectionTableOffset, 0, sectionTableBytes)
    recorder.finishStage()

    const finalization = finalizeFixedElfForAnalysis(recorder, fixed, fixed.buffer, {
        moduleBase: options.moduleBase,
        moduleSize: options.moduleSize,
        loadBias,
    })
    const fixups = recorder.build(rawSize, fixed.byteLength)

    return {
        fixed: fixed.buffer,
        loadBias,
        headerBefore,
        headerAfter: finalization.headerAfter,
        stages: fixups.stages.map((item) => ({ name: item.name, detail: item.detail })),
        fixups,
    }
}

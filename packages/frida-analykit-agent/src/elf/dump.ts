import { Config } from "../config/index.js"
import { help } from "../helper/index.js"
import { BatchSender } from "../internal/rpc/batch_sender.js"
import { batchSendSource, RPCMsgType, saveFileSource } from "../internal/rpc/messages.js"
import { TextEncoder } from "../internal/text/encoder.js"
import { libc } from "../native/libc/libc.js"
import { buildFixedElfForAnalysis, type ElfDumpFixupFile } from "./internal/dump_fixer.js"
import type { ElfModuleX } from "./module.js"
import type { ElfModuleDumpArtifact, ElfModuleDumpOptions, ElfModuleDumpSummary, ElfResolvedSymbol } from "./types.js"

type DumpArtifactPayload = {
    artifact: ElfModuleDumpArtifact
    data: ArrayBuffer
}

type DumpManifest = {
    dump_id: string
    tag: string
    effective_tag: string
    created_at_ms: number
    mode: ElfModuleDumpSummary["mode"]
    requested_output_dir: string | null
    requested_relative_dump_dir: string
    configured_output_root: string | null
    actual_relative_dir: string
    process: {
        pid: number
        arch: string
        pointer_size: number
    }
    module: {
        name: string
        path: string
        base: string
        end: string
        size: number
        elf_class: number
        load_bias: number
        phdr_count: number
    }
    artifacts: Array<{
        kind: ElfModuleDumpArtifact["kind"]
        output_name: string
        size: number
    }>
    fix: {
        strategy: string
        stages: Array<{
            name: string
            detail: string
        }>
        header_before: Record<string, number>
        header_after: Record<string, number>
        change_record: {
            output_name: string
            stage_count: number
            patch_count: number
            raw_size: number
            fixed_size: number
        }
    }
}

const DEFAULT_BATCH_BYTES = 8 * 1024 * 1024
const TEXT_ENCODER = new TextEncoder()

function createDumpId(): string {
    return `elf-${Process.id}-${Date.now()}-${Math.floor(Math.random() * 0x100000).toString(16)}`
}

function sanitizePathSegment(value: string): string {
    const normalized = value.replace(/[\\/]+/g, "_").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "")
    return normalized.length > 0 ? normalized : "module"
}

function basename(path: string): string {
    const items = path.split(/[\\/]+/).filter((item) => item.length > 0)
    return items.length > 0 ? items[items.length - 1] : path
}

function addFileVariant(name: string, variant: "raw" | "fixed"): string {
    const safeName = sanitizePathSegment(name)
    const dotIndex = safeName.lastIndexOf(".")
    if (dotIndex <= 0) {
        return `${safeName}.${variant}`
    }
    return `${safeName.slice(0, dotIndex)}.${variant}${safeName.slice(dotIndex)}`
}

function normalizeBatchBytes(value?: number): number {
    if (value !== undefined && Number.isFinite(value) && value > 0) {
        return Math.floor(value)
    }
    if (Number.isFinite(Config.BatchMaxBytes) && Config.BatchMaxBytes > 0) {
        return Math.floor(Config.BatchMaxBytes)
    }
    return DEFAULT_BATCH_BYTES
}

function toJsonBytes(value: unknown): ArrayBuffer {
    return TEXT_ENCODER.encode(JSON.stringify(value, null, 2)).buffer as ArrayBuffer
}

function toTextBytes(value: string): ArrayBuffer {
    return TEXT_ENCODER.encode(value).buffer as ArrayBuffer
}

function serializeResolvedSymbol(symbol: ElfResolvedSymbol & { value?: NativePointer | null; info?: number; shndx?: number }): Record<string, unknown> {
    return {
        name: symbol.name,
        linked: symbol.linked,
        hook: symbol.hook ? String(symbol.hook) : null,
        implPtr: symbol.implPtr ? String(symbol.implPtr) : null,
        relocPtr: symbol.relocPtr ? String(symbol.relocPtr) : null,
        value: symbol.value ? String(symbol.value) : null,
        info: symbol.info ?? null,
        shndx: symbol.shndx ?? null,
        size: symbol.size,
    }
}

function readModuleBytes(module: ElfModuleX): ArrayBuffer {
    let output: ArrayBuffer | null = null
    help.mem.withReadableRange(module.base, module.size, (makeReadable, makeRecovery) => {
        makeReadable()
        try {
            output = module.base.readByteArray(module.size)
        } finally {
            makeRecovery()
        }
    })
    if (output === null) {
        throw new Error(`[ElfTools] failed to read module bytes for ${module.name}`)
    }
    return output
}

function localDumpBaseDir(outputDir?: string): string {
    if (outputDir && outputDir.length > 0) {
        return outputDir
    }
    return help.fs.joinPath(help.runtime.getOutputDir(), "elftools")
}

function relativeDumpDir(tag: string, dumpId: string): string {
    void dumpId
    return tag.length > 0 ? sanitizePathSegment(tag) : ""
}

function localDumpDir(baseDir: string, dumpRelativeDir: string): string {
    return dumpRelativeDir.length > 0 ? help.fs.joinPath(baseDir, dumpRelativeDir) : baseDir
}

function ensureDirectory(path: string): void {
    const isAbsolute = path.startsWith("/")
    const segments = path.split("/").filter((item) => item.length > 0)
    let current = isAbsolute ? "/" : ""
    for (const segment of segments) {
        current = current === "/" ? `/${segment}` : (current ? help.fs.joinPath(current, segment) : segment)
        libc.mkdir(current, 0o755)
    }
}

function buildManifest(
    module: ElfModuleX,
    dumpId: string,
    tag: string,
    effectiveTag: string,
    createdAtMs: number,
    mode: ElfModuleDumpSummary["mode"],
    requestedOutputDir: string | null,
    requestedRelativeDumpDir: string,
    configuredOutputRoot: string | null,
    actualRelativeDir: string,
    artifacts: ElfModuleDumpArtifact[],
    stages: Array<{
        name: string
        detail: string
    }>,
    loadBias: number,
    headerBefore: Record<string, number>,
    headerAfter: Record<string, number>,
    fixStrategy: string,
    changeRecord: {
        outputName: string
        stageCount: number
        patchCount: number
        rawSize: number
        fixedSize: number
    },
): DumpManifest {
    const modulePath = String((module as unknown as { path?: string }).path || "")
    return {
        dump_id: dumpId,
        tag,
        effective_tag: effectiveTag,
        created_at_ms: createdAtMs,
        mode,
        requested_output_dir: requestedOutputDir,
        requested_relative_dump_dir: requestedRelativeDumpDir,
        configured_output_root: configuredOutputRoot,
        actual_relative_dir: actualRelativeDir,
        process: {
            pid: Process.id,
            arch: Process.arch,
            pointer_size: Process.pointerSize,
        },
        module: {
            name: module.name,
            path: modulePath,
            base: String(module.base),
            end: String(module.base.add(module.size)),
            size: module.size,
            elf_class: module.ehdr.ei_class,
            load_bias: loadBias,
            phdr_count: module.phdrs.length,
        },
        artifacts: artifacts.map((item) => ({
            kind: item.kind,
            output_name: item.outputName,
            size: item.size,
        })),
        fix: {
            strategy: fixStrategy,
            stages,
            header_before: headerBefore,
            header_after: headerAfter,
            change_record: {
                output_name: changeRecord.outputName,
                stage_count: changeRecord.stageCount,
                patch_count: changeRecord.patchCount,
                raw_size: changeRecord.rawSize,
                fixed_size: changeRecord.fixedSize,
            },
        },
    }
}

function createArtifact(kind: ElfModuleDumpArtifact["kind"], outputName: string, size: number): ElfModuleDumpArtifact {
    return { kind, outputName, size }
}

function createBufferedArtifact(kind: ElfModuleDumpArtifact["kind"], outputName: string, data: ArrayBuffer): DumpArtifactPayload {
    return {
        artifact: createArtifact(kind, outputName, data.byteLength),
        data,
    }
}

function buildSymbolsArtifact(module: ElfModuleX): DumpArtifactPayload {
    const symbols = module.getDynSymbols({ full: true }).map((item) => serializeResolvedSymbol({
        name: item.name,
        linked: item.linked,
        hook: item.hook,
        implPtr: item.implPtr,
        relocPtr: item.relocPtr,
        size: item.st_size,
        value: item.st_value,
        info: item.st_info,
        shndx: item.st_shndx,
    }))
    return createBufferedArtifact("symbols", "symbols.json", toJsonBytes(symbols))
}

function buildProcMapsArtifact(): DumpArtifactPayload {
    return createBufferedArtifact("proc_maps", "proc_maps.txt", toTextBytes(help.proc.readMaps()))
}

function buildFixupsArtifact(fixups: ElfDumpFixupFile): DumpArtifactPayload {
    return createBufferedArtifact("fixups", "fixups.json", toJsonBytes(fixups))
}

function countFixupPatches(fixups: ElfDumpFixupFile): number {
    return fixups.stages.reduce((count, stage) => count + stage.patches.length, 0)
}

function sendArtifactInChunks(
    batch: BatchSender,
    dumpId: string,
    tag: string,
    artifact: ElfModuleDumpArtifact,
    data: ArrayBuffer,
    batchBytes: number,
): number {
    let sentBytes = 0
    for (let offset = 0, chunkIndex = 0; offset < data.byteLength; offset += batchBytes, chunkIndex++) {
        const chunkSize = Math.min(batchBytes, data.byteLength - offset)
        const payload = data.slice(offset, offset + chunkSize)
        sentBytes += payload.byteLength
        batch.send({
            type: RPCMsgType.ELF_MODULE_DUMP_CHUNK,
            data: {
                dump_id: dumpId,
                tag,
                artifact: artifact.kind,
                output_name: artifact.outputName,
                chunk_index: chunkIndex,
                total_size: data.byteLength,
            },
        }, payload)
    }
    return sentBytes
}

function writeArtifact(targetDir: string, artifact: ElfModuleDumpArtifact, data: ArrayBuffer): void {
    const filepath = help.fs.joinPath(targetDir, artifact.outputName)
    if (artifact.kind === "raw" || artifact.kind === "fixed") {
        help.fs.save(filepath, data, "wb", saveFileSource.elfModule)
        return
    }
    help.fs.write(filepath, data)
}

export function dumpElfModule(module: ElfModuleX, options: ElfModuleDumpOptions = {}): ElfModuleDumpSummary {
    const tag = options.tag || ""
    const dumpId = createDumpId()
    const mode: ElfModuleDumpSummary["mode"] = Config.OnRPC ? "rpc" : "file"
    const batchBytes = normalizeBatchBytes()
    const outputRoot = Config.OnRPC ? undefined : localDumpBaseDir(options.outputDir)
    const dumpRelativeDir = relativeDumpDir(tag, dumpId)
    const targetDir = outputRoot ? localDumpDir(outputRoot, dumpRelativeDir) : undefined
    const modulePath = String((module as unknown as { path?: string }).path || "")
    const moduleBasename = basename(modulePath || module.name)
    const createdAtMs = Date.now()

    let rawData: ArrayBuffer | null = readModuleBytes(module)
    const {
        fixed: builtFixed,
        loadBias,
        headerBefore,
        headerAfter,
        stages,
        fixups,
    } = buildFixedElfForAnalysis(rawData, {
        moduleBase: module.base,
        moduleSize: module.size,
    })
    let fixedData: ArrayBuffer | null = builtFixed

    const rawArtifact = createArtifact("raw", addFileVariant(moduleBasename, "raw"), rawData.byteLength)
    const fixedArtifact = createArtifact("fixed", addFileVariant(moduleBasename, "fixed"), fixedData.byteLength)
    const fixupsArtifact = buildFixupsArtifact(fixups)
    const symbolsArtifact = buildSymbolsArtifact(module)
    const procMapsArtifact = buildProcMapsArtifact()
    const manifestArtifact = createBufferedArtifact(
        "manifest",
        "manifest.json",
        toJsonBytes(buildManifest(
            module,
            dumpId,
            tag,
            dumpRelativeDir,
            createdAtMs,
            mode,
            options.outputDir || null,
            dumpRelativeDir,
            outputRoot || null,
            dumpRelativeDir,
            [rawArtifact, fixedArtifact, fixupsArtifact.artifact, symbolsArtifact.artifact, procMapsArtifact.artifact],
            stages,
            loadBias,
            headerBefore,
            headerAfter,
            fixups.strategy,
            {
                outputName: fixupsArtifact.artifact.outputName,
                stageCount: fixups.stages.length,
                patchCount: countFixupPatches(fixups),
                rawSize: fixups.raw_size,
                fixedSize: fixups.fixed_size,
            },
        )),
    )
    const artifactDescriptors = [
        rawArtifact,
        fixedArtifact,
        fixupsArtifact.artifact,
        symbolsArtifact.artifact,
        procMapsArtifact.artifact,
        manifestArtifact.artifact,
    ]
    const totalBytes = artifactDescriptors.reduce((sum, item) => sum + item.size, 0)
    const expectedFiles = artifactDescriptors.map((item) => item.outputName)

    options.log?.(`[ElfTools] dump ${module.name} (${totalBytes} bytes)`)

    let receivedBytes = 0
    const emitArtifact = (artifact: ElfModuleDumpArtifact, data: ArrayBuffer, batch?: BatchSender): void => {
        if (Config.OnRPC) {
            receivedBytes += sendArtifactInChunks(batch!, dumpId, tag, artifact, data, batchBytes)
            return
        }
        if (!targetDir) {
            throw new Error("[ElfTools] local dump target directory is unavailable")
        }
        writeArtifact(targetDir, artifact, data)
    }

    if (Config.OnRPC) {
        help.runtime.send({
            type: RPCMsgType.ELF_MODULE_DUMP_BEGIN,
            data: {
                dump_id: dumpId,
                tag,
                output_dir: options.outputDir || undefined,
                relative_dump_dir: dumpRelativeDir,
                module_name: module.name,
                module_path: modulePath,
                module_base: String(module.base),
                module_end: String(module.base.add(module.size)),
                module_size: module.size,
                expected_files: expectedFiles,
                total_bytes: totalBytes,
            },
        })

        const batch = new BatchSender(batchSendSource.ELF_MODULE_DUMP_CHUNKS, {
            maxBatchBytes: batchBytes,
        })
        emitArtifact(rawArtifact, rawData!, batch)
        rawData = null
        emitArtifact(fixedArtifact, fixedData!, batch)
        fixedData = null
        emitArtifact(fixupsArtifact.artifact, fixupsArtifact.data, batch)
        emitArtifact(symbolsArtifact.artifact, symbolsArtifact.data, batch)
        emitArtifact(procMapsArtifact.artifact, procMapsArtifact.data, batch)
        emitArtifact(manifestArtifact.artifact, manifestArtifact.data, batch)
        batch.flush()

        help.runtime.send({
            type: RPCMsgType.ELF_MODULE_DUMP_END,
            data: {
                dump_id: dumpId,
                tag,
                module_name: module.name,
                relative_dump_dir: dumpRelativeDir,
                expected_files: expectedFiles,
                total_bytes: totalBytes,
                received_bytes: receivedBytes,
            },
        })
    } else {
        if (!targetDir) {
            throw new Error("[ElfTools] local dump target directory is unavailable")
        }
        ensureDirectory(targetDir)
        emitArtifact(rawArtifact, rawData!)
        rawData = null
        emitArtifact(fixedArtifact, fixedData!)
        fixedData = null
        emitArtifact(fixupsArtifact.artifact, fixupsArtifact.data)
        emitArtifact(symbolsArtifact.artifact, symbolsArtifact.data)
        emitArtifact(procMapsArtifact.artifact, procMapsArtifact.data)
        emitArtifact(manifestArtifact.artifact, manifestArtifact.data)
    }

    return {
        dumpId,
        tag,
        moduleName: module.name,
        totalBytes,
        mode,
        outputDir: outputRoot,
        relativeDumpDir: dumpRelativeDir,
        artifacts: artifactDescriptors,
    }
}

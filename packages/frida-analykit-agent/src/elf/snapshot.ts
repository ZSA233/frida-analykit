import { Config } from "../config/index.js"
import { help } from "../helper/index.js"
import { BatchSender } from "../internal/rpc/batch_sender.js"
import { batchSendSource, RPCMsgType, saveFileSource } from "../internal/rpc/messages.js"
import { TextEncoder } from "../internal/text/encoder.js"
import type { ElfModuleX } from "./module.js"
import type { ElfResolvedSymbol, ElfSnapshotArtifact, ElfSnapshotOptions, ElfSnapshotSummary } from "./types.js"

type SnapshotArtifactData = {
    artifact: ElfSnapshotArtifact
    outputName: string
    data: ArrayBuffer
}

type SnapshotMetadata = {
    snapshot_id: string
    tag: string
    module: {
        name: string
        path: string
        base: string
        size: number
    }
    artifacts: {
        module: string
        symbols: string
        proc_maps: string
        info: string
    }
}

const DEFAULT_BATCH_BYTES = 8 * 1024 * 1024
const TEXT_ENCODER = new TextEncoder()
const mkdir = new NativeFunction(
    Module.findExportByName("libc.so", "mkdir") || Module.load("libc.so").findExportByName("mkdir")!,
    "int",
    ["pointer", "int"],
)

function createSnapshotId(): string {
    return `elf-${Process.id}-${Date.now()}-${Math.floor(Math.random() * 0x100000).toString(16)}`
}

function sanitizePathSegment(value: string): string {
    const normalized = value.replace(/[\\/]+/g, "_").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "")
    return normalized.length > 0 ? normalized : "module"
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

function serializeResolvedSymbol(symbol: ElfResolvedSymbol): Record<string, unknown> {
    return {
        name: symbol.name,
        linked: symbol.linked,
        hook: symbol.hook ? String(symbol.hook) : null,
        implPtr: symbol.implPtr ? String(symbol.implPtr) : null,
        relocPtr: symbol.relocPtr ? String(symbol.relocPtr) : null,
        size: symbol.size,
    }
}

function buildSnapshotArtifacts(module: ElfModuleX, snapshotId: string, tag: string): SnapshotArtifactData[] {
    const moduleOutputName = sanitizePathSegment(module.name)
    const symbolsOutputName = "symbols.json"
    const procMapsOutputName = "proc_maps.txt"
    const infoOutputName = "info.json"

    const metadata: SnapshotMetadata = {
        snapshot_id: snapshotId,
        tag,
        module: {
            name: module.name,
            path: String((module as unknown as { path?: string }).path || ""),
            base: String(module.base),
            size: module.size,
        },
        artifacts: {
            module: moduleOutputName,
            symbols: symbolsOutputName,
            proc_maps: procMapsOutputName,
            info: infoOutputName,
        },
    }

    const symbols = (module.dynSymbols || []).map((item) => serializeResolvedSymbol({
        name: item.name,
        linked: item.linked,
        hook: item.hook,
        implPtr: item.implPtr,
        relocPtr: item.relocPtr,
        size: item.st_size,
    }))

    return [
        {
            artifact: "symbols",
            outputName: symbolsOutputName,
            data: toJsonBytes(symbols),
        },
        {
            artifact: "proc_maps",
            outputName: procMapsOutputName,
            data: toTextBytes(help.proc.readMaps()),
        },
        {
            artifact: "info",
            outputName: infoOutputName,
            data: toJsonBytes(metadata),
        },
    ]
}

function readModuleBytes(module: ElfModuleX): ArrayBuffer {
    let output: ArrayBuffer | null = null
    help.mem.withReadableRange(module.base, module.size, (makeReadable, makeRecovery) => {
        makeReadable()
        output = module.base.readByteArray(module.size)
        makeRecovery()
    })
    if (output === null) {
        throw new Error(`[ElfTools] failed to read module bytes for ${module.name}`)
    }
    return output
}

function localSnapshotBaseDir(outputDir?: string): string {
    if (outputDir && outputDir.length > 0) {
        return outputDir
    }
    return help.fs.joinPath(help.runtime.getOutputDir(), "elftools")
}

function localSnapshotDir(baseDir: string, tag: string, snapshotId: string): string {
    return help.fs.joinPath(help.fs.joinPath(baseDir, "snapshots"), sanitizePathSegment(tag || snapshotId))
}

function ensureDirectory(path: string): void {
    const isAbsolute = path.startsWith("/")
    const segments = path.split("/").filter((item) => item.length > 0)
    let current = isAbsolute ? "/" : ""
    for (const segment of segments) {
        current = current === "/" ? `/${segment}` : (current ? help.fs.joinPath(current, segment) : segment)
        mkdir(Memory.allocUtf8String(current), 0o755)
    }
}

export function snapshotElfModule(module: ElfModuleX, options: ElfSnapshotOptions = {}): ElfSnapshotSummary {
    const tag = options.tag || ""
    const snapshotId = createSnapshotId()
    const mode: ElfSnapshotSummary["mode"] = Config.OnRPC ? "rpc" : "file"
    const batchBytes = normalizeBatchBytes()
    const localBaseDir = localSnapshotBaseDir(options.outputDir)
    const baseDir = Config.OnRPC ? (options.outputDir || undefined) : localBaseDir
    const artifacts = buildSnapshotArtifacts(module, snapshotId, tag)
    const totalBytes = module.size + artifacts.reduce((sum, item) => sum + item.data.byteLength, 0)
    const moduleOutputName = sanitizePathSegment(module.name)

    options.log?.(`[ElfTools] snapshot ${module.name} (${totalBytes} bytes)`)

    if (Config.OnRPC) {
        help.runtime.send({
            type: RPCMsgType.ELF_SNAPSHOT_BEGIN,
            data: {
                snapshot_id: snapshotId,
                tag,
                output_dir: options.outputDir || undefined,
                module_name: module.name,
                module_path: String((module as unknown as { path?: string }).path || ""),
                module_base: module.base,
                module_size: module.size,
                expected_files: [moduleOutputName, ...artifacts.map((item) => item.outputName)],
                total_bytes: totalBytes,
            },
        })

        const batch = new BatchSender(batchSendSource.ELF_SNAPSHOT_CHUNKS, {
            maxBatchBytes: batchBytes,
        })
        let receivedBytes = 0

        help.mem.withReadableRange(module.base, module.size, (makeReadable, makeRecovery) => {
            makeReadable()
            for (let offset = 0, chunkIndex = 0; offset < module.size; offset += batchBytes, chunkIndex++) {
                const chunkSize = Math.min(batchBytes, module.size - offset)
                const payload = module.base.add(offset).readByteArray(chunkSize)
                if (payload === null) {
                    throw new Error(`[ElfTools] failed to read module chunk ${chunkIndex} for ${module.name}`)
                }
                receivedBytes += chunkSize
                batch.send({
                    type: RPCMsgType.ELF_SNAPSHOT_CHUNK,
                    data: {
                        snapshot_id: snapshotId,
                        tag,
                        artifact: "module",
                        output_name: moduleOutputName,
                        chunk_index: chunkIndex,
                        total_size: module.size,
                    },
                }, payload)
            }
            makeRecovery()
        })

        for (const artifact of artifacts) {
            receivedBytes += artifact.data.byteLength
            batch.send({
                type: RPCMsgType.ELF_SNAPSHOT_CHUNK,
                data: {
                    snapshot_id: snapshotId,
                    tag,
                    artifact: artifact.artifact,
                    output_name: artifact.outputName,
                    chunk_index: 0,
                    total_size: artifact.data.byteLength,
                },
            }, artifact.data)
        }
        batch.flush()

        help.runtime.send({
            type: RPCMsgType.ELF_SNAPSHOT_END,
            data: {
                snapshot_id: snapshotId,
                tag,
                module_name: module.name,
                expected_files: [moduleOutputName, ...artifacts.map((item) => item.outputName)],
                total_bytes: totalBytes,
                received_bytes: receivedBytes,
            },
        })
    } else {
        const targetDir = localSnapshotDir(localBaseDir, tag, snapshotId)
        ensureDirectory(targetDir)
        help.fs.save(help.fs.joinPath(targetDir, moduleOutputName), readModuleBytes(module), "wb", saveFileSource.elfModule)
        for (const artifact of artifacts) {
            help.fs.write(help.fs.joinPath(targetDir, artifact.outputName), artifact.data)
        }
    }

    return {
        snapshotId,
        tag,
        moduleName: module.name,
        totalBytes,
        mode,
        outputDir: baseDir,
    }
}

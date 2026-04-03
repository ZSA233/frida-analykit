import { Java } from "../bridges/index.js"
import { Config, setGlobalProperties } from "../config/index.js"
import { help } from "../helper/index.js"
import { PointerVector } from "../internal/cxx/index.js"
import { NativePointerObject } from "../internal/frida/pointer_object.js"
import { BatchSender } from "../internal/rpc/batch_sender.js"
import { batchSendSource, RPCMsgType, saveFileSource } from "../internal/rpc/messages.js"
import { JNIEnv } from "../jni/index.js"
import { Libart } from "../native/libart/libart.js"
import { DexFileStructOf } from "./struct.js"
import type { ClassLoaderDexFiles, DexDumpFileInfo, DexDumpOptions, DexDumpSummary, DexRuntimeFileInfo } from "./types.js"

type DexFileShape = {
    begin: NativePointer
    size: number
    location: NativePointer
}

type DumpAllDexCompatArgs = {
    tag?: string
    dumpDir?: string
    log?: (message: string) => void
}

class DexFileView extends NativePointerObject implements DexFileShape {
    declare readonly begin: NativePointer
    declare readonly size: number
    declare readonly location: NativePointer

    constructor(handle: NativePointer) {
        super(handle)
        const structOf = Process.pointerSize === 4 ? DexFileStructOf.B32 : DexFileStructOf.B64
        for (const [field, reader] of Object.entries(structOf)) {
            Object.defineProperty(this, field, {
                value: reader(this.$handle),
                writable: false,
                enumerable: true,
            })
        }
    }
}

function createTransferId(): string {
    return `dex-${Process.id}-${Date.now()}-${Math.floor(Math.random() * 0x100000).toString(16)}`
}

function readArtStdString(handle: NativePointer): string {
    if (handle.isNull()) {
        return ""
    }
    if (Process.pointerSize === 4) {
        const size = handle.add(11).readU8() & 0x7f
        return (handle.readPointer().readCString(size) || "")
    }
    const cap = handle.readU64()
    const longMode = !cap.and(0x1).equals(0)
    if (longMode) {
        const size = Number(handle.add(Process.pointerSize).readU64())
        return handle.add(Process.pointerSize * 2).readPointer().readCString(size) || ""
    }
    const size = handle.add(23).readU8() & 0x7f
    return handle.readPointer().readCString(size) || ""
}

function getJavaObjectHandle(value: unknown): NativePointer | null {
    const handle = (value as { $h?: NativePointer } | null | undefined)?.$h
    if (handle === undefined || handle === null || handle.isNull()) {
        return null
    }
    return handle
}

function getJavaClassName(value: Java.Wrapper): string {
    const className = (value as unknown as { $className?: string }).$className
    if (typeof className === "string" && className.length > 0) {
        return className
    }
    return String((value as any).getClass().getName().toString())
}

function readJavaString(value: unknown): string {
    if (value === null || value === undefined) {
        return ""
    }
    if (typeof value === "string") {
        return value
    }
    if (typeof (value as { toString?: () => string }).toString === "function") {
        return (value as { toString: () => string }).toString()
    }
    return String(value)
}

function normalizeDumpArgs(
    tagOrOptions?: string | DexDumpOptions,
    dumpDir?: string,
    log?: (message: string) => void,
): Required<DumpAllDexCompatArgs> & { maxBatchBytes?: number } {
    if (typeof tagOrOptions === "object" && tagOrOptions !== null) {
        return {
            tag: tagOrOptions.tag ?? "",
            dumpDir: tagOrOptions.dumpDir ?? "",
            log: tagOrOptions.log ?? console.log,
            maxBatchBytes: tagOrOptions.maxBatchBytes,
        }
    }
    return {
        tag: tagOrOptions ?? "",
        dumpDir: dumpDir ?? "",
        log: log ?? console.log,
        maxBatchBytes: undefined,
    }
}

function normalizeDexName(javaName: string, dex: DexFileView, count: number): string {
    if (count <= 1 && javaName.length > 0) {
        return javaName
    }
    const nativeName = readArtStdString(dex.location)
    if (nativeName.length > 0) {
        return nativeName
    }
    return javaName
}

export class DexTools {
    static enumerateClassLoaderDexFiles(): ClassLoaderDexFiles[] {
        if (!Java.available) {
            throw new Error("Java runtime is not available")
        }

        const BaseDexClassLoader = Java.use("dalvik.system.BaseDexClassLoader")
        const loaders = Java.enumerateClassLoadersSync()
        const results: ClassLoaderDexFiles[] = []

        for (const loader of loaders) {
            let dexFiles: DexRuntimeFileInfo[] = []
            try {
                const baseLoader = Java.cast(loader, BaseDexClassLoader)
                const pathList = baseLoader.pathList.value
                const dexElements = pathList?.dexElements?.value as Java.Wrapper[] | null | undefined
                if (!dexElements || dexElements.length === 0) {
                    results.push({
                        loader_handle: getJavaObjectHandle(loader) ?? NULL,
                        loader_class: getJavaClassName(loader),
                        dexFiles,
                    })
                    continue
                }

                JNIEnv.PushLocalFrame(Math.max(64, dexElements.length * 4 + 8))
                try {
                    dexFiles = dexElements.flatMap((element) => {
                        const dexFile = (element as any).dexFile?.value
                        if (dexFile === null || dexFile === undefined) {
                            return []
                        }

                        const cookieHandle = getJavaObjectHandle((dexFile as any).mCookie?.value)
                        if (cookieHandle === null) {
                            return []
                        }

                        const vector = new PointerVector()
                        const oatFileHolder = Memory.alloc(Process.pointerSize)
                        try {
                            const converted = Libart.ConvertJavaArrayToDexFiles(
                                JNIEnv.$env.handle,
                                cookieHandle,
                                vector.$handle,
                                oatFileHolder,
                            )
                            if (converted === 0) {
                                const fileName = readJavaString((dexFile as any).mFileName?.value)
                                help.$warn(`[DexTools] ConvertJavaArrayToDexFiles failed for ${fileName}`)
                                return []
                            }

                            const handles = vector.toPointerArray()
                            const javaName = readJavaString((dexFile as any).mFileName?.value)
                            return handles.map((handle) => {
                                const dex = new DexFileView(handle)
                                return {
                                    name: normalizeDexName(javaName, dex, handles.length),
                                    base: dex.begin,
                                    size: dex.size,
                                }
                            })
                        } finally {
                            vector.dispose()
                        }
                    })
                } finally {
                    JNIEnv.PopLocalFrame(NULL)
                }
            } catch (error) {
                help.$warn(`[DexTools] failed to enumerate loader ${getJavaClassName(loader)}: ${error}`)
            }

            results.push({
                loader_handle: getJavaObjectHandle(loader) ?? NULL,
                loader_class: getJavaClassName(loader),
                dexFiles,
            })
        }

        return results
    }

    static dumpAllDex(tagOrOptions?: string | DexDumpOptions, dumpDir?: string, log?: (message: string) => void): DexDumpSummary {
        const options = normalizeDumpArgs(tagOrOptions, dumpDir, log)
        const classLoaderDexFiles = this.enumerateClassLoaderDexFiles()
        const files: DexDumpFileInfo[] = []
        const totalCount = classLoaderDexFiles.reduce((count, loader) => count + loader.dexFiles.length, 0)
        const padWidth = Math.max(2, String(Math.max(totalCount - 1, 0)).length)
        let totalBytes = 0
        let fileIndex = 0

        for (const loader of classLoaderDexFiles) {
            for (const dex of loader.dexFiles) {
                const outputName = `classes${String(fileIndex).padStart(padWidth, "0")}.dex`
                files.push({
                    ...dex,
                    loader_handle: loader.loader_handle,
                    loader_class: loader.loader_class,
                    output_name: outputName,
                })
                totalBytes += dex.size
                fileIndex++
            }
        }

        const tag = options.tag
        const transferId = createTransferId()
        const mode: DexDumpSummary["mode"] = Config.OnRPC ? "rpc" : "file"
        const localOutputDir = options.dumpDir || help.runtime.getOutputDir()

        options.log(`[DexTools] dumping ${files.length} dex files (${totalBytes} bytes)`)
        if (Config.OnRPC) {
            help.runtime.send({
                type: RPCMsgType.DEX_DUMP_BEGIN,
                data: {
                    transfer_id: transferId,
                    tag,
                    dump_dir: options.dumpDir || undefined,
                    expected_count: files.length,
                    total_bytes: totalBytes,
                    max_batch_bytes: options.maxBatchBytes ?? Config.BatchMaxBytes,
                },
            })

            const batch = new BatchSender(batchSendSource.DEX_DUMP_FILES, {
                maxBatchBytes: options.maxBatchBytes ?? Config.BatchMaxBytes,
            })
            let sentCount = 0
            for (const dex of files) {
                const payload = dex.base.readByteArray(dex.size)
                if (payload === null) {
                    help.$warn(`[DexTools] failed to read dex bytes for ${dex.name}`)
                    continue
                }
                batch.send({
                    type: RPCMsgType.DUMP_DEX_FILE,
                    data: {
                        transfer_id: transferId,
                        tag,
                        info: {
                            name: dex.name,
                            base: dex.base,
                            size: dex.size,
                            loader: dex.loader_handle,
                            loader_class: dex.loader_class,
                            output_name: dex.output_name,
                        },
                    },
                }, payload)
                sentCount++
            }
            batch.flush()
            help.runtime.send({
                type: RPCMsgType.DEX_DUMP_END,
                data: {
                    transfer_id: transferId,
                    tag,
                    expected_count: files.length,
                    received_count: sentCount,
                    total_bytes: totalBytes,
                },
            })
        } else {
            for (const dex of files) {
                const payload = dex.base.readByteArray(dex.size)
                if (payload === null) {
                    help.$warn(`[DexTools] failed to read dex bytes for ${dex.name}`)
                    continue
                }
                const relativeOutput = tag.length > 0
                    ? help.fs.joinPath(tag, dex.output_name)
                    : dex.output_name
                const outputPath = help.fs.joinPath(localOutputDir, relativeOutput)
                help.fs.save(outputPath, payload, "wb", saveFileSource.dexFile)
            }
        }

        return {
            transferId,
            tag,
            dexCount: files.length,
            totalBytes,
            mode,
            dumpDir: Config.OnRPC ? (options.dumpDir || undefined) : localOutputDir,
        }
    }
}

setGlobalProperties({
    DexTools,
})

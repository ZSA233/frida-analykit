import { TextEncoder } from "../../internal/text/encoder.js"
import { saveFileSource, RPCMsgType } from "../../internal/rpc/messages.js"
import { libc } from "../../native/libc/libc.js"
import { NativePointerObject } from "../pointer.js"

declare class File {
    constructor(filePath: string, mode: string)
    static readAllText(filePath: string): string
    static readAllBytes(filePath: string): ArrayBuffer
    write(data: string | ArrayBuffer | number[]): void
    flush(): void
    close(): void
}

export class FileHelper extends NativePointerObject {
    private isClosed = false
    private readonly weakRefId: WeakRefId

    constructor(pathname: string, mode: string) {
        const handle = libc.fopen(pathname, mode)
        if (handle.isNull()) {
            throw new Error(`can't open file[${pathname}], mode[${mode}]`)
        }
        super(handle)
        const weakRef = ptr(handle.toString())
        this.weakRefId = Script.bindWeak(this.$handle, () => libc.fclose(weakRef))
    }

    close(): number {
        if (this.isClosed) {
            return 0
        }
        this.isClosed = true
        Script.unbindWeak(this.weakRefId)
        return libc.fclose(this.$handle)
    }

    writeLine(data: string, append = "\n"): number {
        return libc.fputs(data + append, this.$handle)
    }

    flush(): number {
        return libc.fflush(this.$handle)
    }
}

export function walkDir(path: string, fn: AnyFunction): null | void {
    const dir = libc.opendir(path)
    if (dir.isNull()) {
        console.error(`[walkDir] path[${path}] 打开失败.`)
        return null
    }
    const nameOffset = Process.pointerSize * 2 + 2 + 1
    let dirent: NativePointer
    while (!(dirent = libc.readdir(dir)).isNull()) {
        const name = dirent.add(nameOffset).readCString()
        const fp = `${path}/${name}`
        const link = libc.readlink(fp)
        if (!fn(name, link)) {
            break
        }
    }
    libc.closedir(dir)
}

export function read(path: string): ArrayBuffer {
    return File.readAllBytes(path)
}

export function readText(path: string): string {
    return File.readAllText(path)
}

export function write(path: string, data: string | ArrayBuffer | number[], mode: string = typeof data === "string" ? "w" : "wb"): void {
    const savedFile = new File(path, mode)
    savedFile.write(data)
    savedFile.close()
}

export function open(pathname: string, mode: string): FileHelper {
    return new FileHelper(pathname, mode)
}

export function isFilePath(str: string): boolean {
    return str.length > 0 && str[0] === "/" && str[str.length - 1] !== "/"
}

export function joinPath(dir: string, file: string): string {
    if (!dir.length) {
        return dir
    }
    return dir.replace(/\/+$/, "") + "/" + file.replace(/^\/+/, "")
}

function normalizeSaveData(data: string | ArrayBuffer | number[]): ArrayBuffer | number[] {
    if (typeof data === "string") {
        return new TextEncoder().encode(data).buffer as ArrayBuffer
    }
    return data
}

export type HelperFsContext = {
    getOutputDir: () => string
    logFiles: Record<string, FileHelper>
    isRpcEnabled: () => boolean
    send: (message: any, data?: ArrayBuffer | number[] | null) => void
}

export function createFsFacade(context: HelperFsContext) {
    return {
        read,
        readText,
        write,
        open,
        save(tag: string, data: string | ArrayBuffer | number[] | null, mode: string, source: saveFileSource | string): boolean {
            if (data === null || data === undefined) {
                return false
            }
            const filepath = isFilePath(tag) ? tag : joinPath(context.getOutputDir(), tag)

            if (context.isRpcEnabled()) {
                context.send({
                    type: RPCMsgType.SAVE_FILE,
                    data: {
                        source,
                        filepath,
                        mode,
                    },
                }, normalizeSaveData(data))
                return true
            }

            write(filepath, data, mode)
            return true
        },
        getLogFile(tag: string, mode: string): FileHelper {
            const filepath = isFilePath(tag) ? tag : joinPath(context.getOutputDir(), tag)
            let fp = context.logFiles[filepath]
            if (!fp) {
                fp = open(filepath, mode)
                context.logFiles[filepath] = fp
            }
            return fp
        },
        joinPath,
        isFilePath,
    } as const
}

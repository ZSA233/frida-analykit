import { BatchSender } from "../internal/rpc/batch_sender.js"
import { setGlobalProperties } from "../config/index.js"
import { help, type HelperFacade, print, printErr } from "./facade.js"

export { BatchSender }
export { FileHelper, isFilePath, joinPath, open, read, readText, walkDir, write } from "./fs/index.js"
export { LoggerState } from "./log/index.js"
export type { MemoryPage, MemoryProtect } from "./mem/index.js"
export { downAlign, page_end, page_start, pageEnd, pageStart, scan, upAlign, withReadablePages, withReadableRange } from "./mem/index.js"
export { ProgressNotify } from "./progress/index.js"
export { NativePointerObject } from "./pointer.js"
export { createHelperRuntimeContext } from "./runtime/index.js"
export { help, print, printErr }

declare global {
    const help: HelperFacade
    function print(...args: any[]): void
    function printErr(...args: any[]): void
}

setGlobalProperties({
    help,
    print,
    printErr,
})

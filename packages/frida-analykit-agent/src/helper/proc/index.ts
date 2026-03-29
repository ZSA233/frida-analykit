import { libc } from "../../native/libc/libc.js"
import { read, readText } from "../fs/index.js"

export function getFdLink(fd: number): string | null {
    return libc.readlink(`/proc/self/fd/${fd}`)
}

export function getFileStreamLink(stream: NativePointer): string | null {
    const fd = libc.fileno(stream)
    if (fd < 0) {
        return null
    }
    return libc.readlink(`/proc/self/fd/${fd}`)
}

export function readMaps(pid: number | string = "self"): string {
    return readText(`/proc/${pid}/maps`)
}

export function readCmdline(pid: number | string = "self"): string {
    const cmdline = read(`/proc/${pid}/cmdline`)
    const sepList: string[] = []
    let lastIdx = 0
    const bytes = new Uint8Array(cmdline)
    for (let i = 0; i < bytes.byteLength; i++) {
        const byte = bytes[i]
        if (byte === 0) {
            if (lastIdx < i - 1) {
                let result = ""
                const view = bytes.slice(lastIdx, i)
                for (let j = 0; j < view.length; j++) {
                    result += String.fromCharCode(view[j])
                }
                if (result.length > 0) {
                    sepList.push(result)
                }
            }
            lastIdx = i
        }
    }
    return sepList.join(" ")
}

export function createProcFacade() {
    return {
        readMaps,
        readCmdline,
        getFdLink,
        getFileStreamLink,
    } as const
}

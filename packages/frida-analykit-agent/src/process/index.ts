import { setGlobalProperties } from "../config/index.js"
import { help } from "../helper/index.js"
import { ProcMap } from "./maps.js"

interface RangeDetails {
    base: NativePointer
    size: number
    protection: PageProtection
    file?: FileMapping | undefined
}

class Proc {
    private static _mapCache: RangeDetails[] = []

    static findMapCache(addr: NativePointer): RangeDetails | null {
        const result = this._mapCache.find((v) => addr >= v.base && addr < v.base.add(v.size))
        if (result) {
            return result
        }
        const range = Process.findRangeByAddress(addr)
        if (!range) {
            return null
        }
        let hitIndex = -1
        this._mapCache.find((v, i) => {
            const ok = v.base == range.base
            if (ok) {
                hitIndex = i
            }
            return ok
        })
        if (hitIndex !== -1) {
            this._mapCache[hitIndex] = range
        } else {
            this._mapCache.push(range)
        }
        return range
    }

    static loadProcMap(pid: number | string = "self"): ProcMap {
        return new ProcMap(help.proc.readMaps(pid))
    }
}

export { Proc as proc }
export { ProcMap, ProcMapItem } from "./maps.js"

declare global {
    const proc: typeof Proc
}

setGlobalProperties({
    proc: Proc,
})

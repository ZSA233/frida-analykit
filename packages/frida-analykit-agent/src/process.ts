import { help  } from "./helper.js";


// frida-gum/index.d.ts
interface RangeDetails {
    /**
     * Base address.
     */
    base: NativePointer;

    /**
     * Size in bytes.
     */
    size: number;

    /**
     * Protection.
     */
    protection: PageProtection;

    /**
     * File mapping details, if available.
     */
    file?: FileMapping | undefined;

}


export class ProcMapItem {
    start_page: NativePointer
    end_page: NativePointer
    prots: string
    offset: number
    main_dev: string
    slave_dev: string
    inode: number
    pathname: string

    constructor(
        start_page: string,
        end_page: string,
        prots: string,
        offset: string,
        main_dev: string,
        slave_dev: string,
        inode: string,
        pathname: string,
    ) {
        this.start_page = ptr(parseInt(start_page, 16))
        this.end_page = ptr(parseInt(end_page, 16))
        this.prots = prots
        this.offset = parseInt(offset, 16)
        this.main_dev = main_dev
        this.slave_dev = slave_dev
        this.inode = parseInt(inode)
        this.pathname = pathname.trim()
    }

    toString(): string {
        return `${this.start_page.toString(16)}-${this.end_page.toString(16)} ${this.prots} ${this.offset.toString(16)} ${this.main_dev}:${this.slave_dev} ${this.inode} ${this.pathname}`
    }
}

const REGEXP_PROC_MAPS_LINE = /^([a-fA-F0-9]+)-([a-fA-F0-9]+)\s+([rwx\-p]+)\s+(\w+)\s+(\w+):(\d+)\s+(\d+)\s+(.*)$/

export class ProcMap {
    public text: string
    public items: ProcMapItem[]

    constructor(text: string) {
        this.text = text
        this.items = []
        const lines = text.split('\n')
        for (const line of lines) {
            if (!line.trim()) continue
            const result = ProcMap.parseLine(line)
            if (!result || result.length !== 8) continue
            const item = new ProcMapItem(
                ...result as [string, string, string, string, string, string, string, string]
            )
            this.items.push(item)
        }
    }

    static parseLine(line: string): string[] | null {
        const m = REGEXP_PROC_MAPS_LINE.exec(line)
        if (!m) return null
        return m.slice(1)
    }

    find(start_addr: NativePointer, end_addr: NativePointer): ProcMapItem[] {
        return this.items.filter(item => {
            return !(item.start_page >= end_addr || item.end_page <= start_addr)
        })
    }
}



class Proc {
    private static _mapCache: RangeDetails[] = []


    static findMapCache(addr: NativePointer): RangeDetails | null {
        const result = this._mapCache.find((v, i) => {
            return addr >= v.base && addr < v.base.add(v.size)
        })
        if (result) {
            return result || null
        }
        const range = Process.findRangeByAddress(addr)
        if(!range) {
            return null
        } 
        let hitIndex = -1
        const hit = this._mapCache.find((v, i) => {
            const ok = v.base == range.base
            if (ok) hitIndex = i
            return ok
        })
        if (hitIndex !== -1) {
            this._mapCache[hitIndex] = range
        }else{
            this._mapCache.push(range)
        }
        return range
    }


    static loadProcMap(pid: number | string = 'self'): ProcMap{
        return new ProcMap(help.readProcMaps(pid))
    }

}


export { Proc as proc }
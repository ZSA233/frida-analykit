import { ProgressNotify } from "../progress/index.js"

export function downAlign(value: number, alignTo: number): number {
    return Math.floor(value / alignTo) * alignTo
}

export function upAlign(value: number, alignTo: number): number {
    return Math.ceil(value / alignTo) * alignTo
}

export function pageStart(value: number): number {
    return downAlign(value, Process.pageSize)
}

export function pageEnd(value: number): number {
    return upAlign(value, Process.pageSize)
}

export const page_start = pageStart
export const page_end = pageEnd

export type MemoryProtect = {
    originProts: string
    newProts: string
    range: RangeDetails | null
    protectResult?: boolean
    recoverResult?: boolean
    readable: boolean
}

export type MemoryPage = {
    base: NativePointer
    size: number
} & MemoryProtect

function getScanPatternSize(pattern: string): number {
    if (pattern.startsWith("/") && pattern.endsWith("/")) {
        throw new Error("Regular expression patterns are not allowed")
    }

    const bytesPart = pattern.split(":", 1)[0].trim()
    if (bytesPart === "") {
        return 0
    }
    return bytesPart.split(/\s+/).length
}

export function backtrace({
    context = undefined,
    addrHandler = DebugSymbol.fromAddress,
    backtracer = Backtracer.ACCURATE,
}: {
    context?: CpuContext | undefined
    addrHandler?: (addr: NativePointer) => unknown
    backtracer?: Backtracer
} = {}): void {
    const prog = new ProgressNotify("help.mem.backtrace")
    const stacks = Thread.backtrace(context, backtracer).map((addr) => `${addrHandler(addr)}`)
    prog.log(Process.getCurrentThreadId(), "", stacks)
}

export function withReadableRange(
    address: NativePointer,
    size: number,
    use: (makeReadable: () => MemoryProtect[], makeRecovery: () => MemoryProtect[]) => void,
): void {
    const pageInfos: MemoryProtect[] = []
    const makeReadable = () => {
        let cur = address
        const end = address.add(size)
        while (cur < end) {
            const range = Process.findRangeByAddress(cur)
            let originProts = ""
            let newProts = ""
            let readable = false
            if (range !== null) {
                cur = range.base.add(range.size)
                originProts = range.protection
                if (range.protection[0] !== "r") {
                    newProts = "r" + originProts.slice(1)
                } else {
                    readable = true
                }
            } else {
                // Frida-managed allocations or holes may not resolve to a range; advance by page to avoid hanging.
                cur = cur.and(ptr(Process.pageSize - 1).not()).add(Process.pageSize)
            }
            pageInfos.push({
                readable,
                originProts,
                newProts,
                range,
            })
        }

        for (const pageInfo of pageInfos) {
            if (pageInfo.range && pageInfo.newProts !== "") {
                pageInfo.protectResult = Memory.protect(pageInfo.range.base, pageInfo.range.size, pageInfo.newProts)
                if (pageInfo.protectResult) {
                    pageInfo.readable = true
                }
            }
        }
        return pageInfos
    }

    const makeRecovery = () => {
        for (const pageInfo of pageInfos) {
            if (pageInfo.range && pageInfo.newProts !== "" && pageInfo.protectResult) {
                pageInfo.recoverResult = Memory.protect(pageInfo.range.base, pageInfo.range.size, pageInfo.originProts)
            }
        }
        return pageInfos
    }

    use(makeReadable, makeRecovery)
}

export function withReadablePages(base: NativePointer, size: number, use: (page: MemoryPage) => boolean): MemoryPage[] {
    const pageInfos: MemoryPage[] = []
    let cur = base
    const end = base.add(size)
    let isAbort = false

    while (!isAbort && cur < end) {
        const range = Process.findRangeByAddress(cur)
        const page: MemoryPage = {
            base: cur.and(ptr(Process.pageSize - 1).not()),
            size: Process.pageSize,
            protectResult: false,
            originProts: "",
            newProts: "",
            readable: false,
            range,
        }

        if (range !== null) {
            page.originProts = range.protection
            if (range.protection[0] !== "r") {
                page.newProts = "r" + page.originProts.slice(1)
                page.protectResult = Memory.protect(page.base, page.size, page.newProts)
                if (page.protectResult) {
                    page.readable = true
                }
            } else {
                page.readable = true
            }
            isAbort = use(page)
            if (page.protectResult) {
                page.recoverResult = Memory.protect(page.base, page.size, page.originProts)
            }
        }
        pageInfos.push(page)
        cur = page.base.add(page.size)
    }

    return pageInfos
}

export function scan(
    scanRange: { base: NativePointer, size: number },
    pattern: string,
    {
        limit = Process.pageSize,
        maxMatchNum = -1,
        onMatch,
    }: {
        limit?: number
        maxMatchNum?: number
        onMatch?: (match: MemoryScanMatch) => boolean
    },
): MemoryScanMatch[] {
    const patternSize = getScanPatternSize(pattern)
    const { base, size } = scanRange
    const end = base.add(size)
    let cursor = base
    const scanResults: MemoryScanMatch[] = []

    withReadableRange(base, size, (makeReadable, makeRecovery) => {
        makeReadable()
        while (cursor < end) {
            const nextCur = cursor.add(Math.min(Number(end.sub(cursor)), limit))
            const cur = Number(cursor.sub(base)) > patternSize ? cursor.sub(patternSize) : cursor
            let results: MemoryScanMatch[]
            try {
                results = Memory.scanSync(cur, Number(nextCur.sub(cur)), pattern)
                if (onMatch) {
                    results = results.filter((value) => onMatch(value))
                }
                scanResults.push(...results)
            } catch (error) {
                console.error(`[help.mem.scan] e[${error}]`)
            } finally {
                if (maxMatchNum > 0 && scanResults.length >= maxMatchNum) {
                    break
                }
                cursor = nextCur
            }
        }
        makeRecovery()
    })

    return scanResults
}

export function createMemFacade() {
    return {
        scan,
        withReadableRange,
        withReadablePages,
        backtrace,
        downAlign,
        upAlign,
        pageStart,
        pageEnd,
    } as const
}

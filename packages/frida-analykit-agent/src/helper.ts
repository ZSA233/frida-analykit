import { Libc } from './lib/libc.js'
import { FixedQueue } from './utils/queue.js'
import { RPCMsgType, saveFileSource } from './message.js'
import { Config, LogLevel, setGlobalProperties } from './config.js'
import { TextEncoder } from './utils/text_endec.js'


export class NativePointerObject {
    protected readonly _handle: NativePointer

    constructor(handle: NativePointer){
        this._handle = handle
    }

    get $handle(): NativePointer {
        return this._handle
    }

    $isNull(): boolean {
        return this.$handle.isNull()
    }

}


declare class File {
    constructor(filePath: string, mode: string)
    static readAllText(filePath: string): string
    static readAllBytes(filePath: string): ArrayBuffer
    write(data: string | ArrayBuffer | number[]): void
    flush(): void;
    close(): void;
}


export function downAlign(value: number, alignTo: number) { return Math.floor(value / alignTo) * alignTo }
export function upAlign(value: number, alignTo: number) { return Math.ceil(value / alignTo) * alignTo }
export function page_start(value: number) { return downAlign(value, Process.pageSize) }
export function page_end(value: number) { return upAlign(value, Process.pageSize) }


export class LoggerState {
    private msgs: FixedQueue<string>
    private base_msgs: FixedQueue<string>
    private match_offset: number = 0

    private depth: number = 1
    private counter: number = 1
    private index: number = 0

    constructor(depth: number = 1) {
        this.depth = depth
        this.index = 0
        this.msgs = new FixedQueue<string>(depth)
        this.base_msgs = new FixedQueue<string>(depth)
    }


    onLog(msg: string): string[] {
        this.index++

        const earliest_msg = this.msgs.push(msg)
        if (earliest_msg === undefined) {
            this.base_msgs.push(msg)
            return [msg]
        } else {
            let outMsgs: string[] = []

            if (this.base_msgs.index(this.match_offset) === msg) {
                this.match_offset++
                if (this.match_offset === this.depth) {
                    this.counter++
                    this.match_offset = 0
                }
            } else {
                if (this.counter > 1) {
                    outMsgs = (this.base_msgs.list as string[]).map(v => `#${this.counter}# | ${v}`)
                    outMsgs.push(msg)
                    this.base_msgs.clear()
                } else {
                    outMsgs = [msg]
                }
                this.base_msgs.push(msg)
                this.match_offset = 0
                this.counter = 1
            }
            return outMsgs
        }
    }

}


const AID_USER_OFFSET = 100000

function multiuser_get_user_id(uid: number){
    return Math.floor(uid / AID_USER_OFFSET)
}



export class FileHelper extends NativePointerObject {
    private _isClosed: boolean = false
    private readonly _weakRefId: WeakRefId 
    constructor(pathname: string, mode: string) {
        const handle = Helper.libc.fopen(pathname, mode)
        if(handle.isNull()) {
            throw new Error(`can't open file[${pathname}], mode[${mode}]`)
        }
        super(handle)
        const weakRef = ptr(handle.toString())
        this._weakRefId = Script.bindWeak(this.$handle, () => {
            return Helper.libc.fclose(weakRef)
        })
    }

    close() {
        return this._isClosed ? 0 : (this._isClosed = true, Script.unbindWeak(this._weakRefId), Helper.libc.fclose(this.$handle))
    }

    writeLine(data: string, append='\n'){
        return Helper.libc.fputs(data + append, this.$handle)
    }

    flush() {
        return Helper.libc.fflush(this.$handle)
    }
}


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


export class BatchSender {
    private _source: string
    private _batch_list: {
        message: any,
        data?: ArrayBuffer | null,
    }[] = []

    constructor(source: string) {
        this._source = source
    }

    send(message: any, data?: ArrayBuffer | null) {
        this._batch_list.push({
            message: message,
            data: data,
        })
    }

    rpcResponse() {
        if (!this._batch_list.length) {
            return []
        }
        let totalBuffLen = this._batch_list.reduce((acc, cur) => acc + (cur.data?.byteLength || 0), 0)
        const batchBuff = new Uint8Array(totalBuffLen)
        const buffSizeList = []
        const messageList = []
        let buffIndex = 0
        for (let i = 0; i < this._batch_list.length; i++) {
            const data = this._batch_list[i]
            messageList.push(data.message)
            const buffSize = data.data?.byteLength || 0
            buffSizeList.push(buffSize)
            if (data.data && buffSize > 0) {
                batchBuff.set(new Uint8Array(data.data), buffIndex)
                buffIndex += buffSize
            }
        }
        return [{
            type: RPCMsgType.BATCH,
            source: this._source,
            data: {
                message_list: messageList,
                data_sizes: buffSizeList,
            }
        }, batchBuff.buffer]
    }

    clear(){
        this._batch_list = []
    }

    flush(){
        const [message, buff] = this.rpcResponse()
        if(!message && !buff) {
            return 
        }
        Helper.$send(message, buff as ArrayBuffer)
        this.clear()
    }

}


let PROGRESS_INC: number = 0

export class ProgressNotify {
    private readonly ID: number
    readonly tag: string
    private step: number = 0
    private startTime: Date

    constructor(tag: string) {
        PROGRESS_INC++
        this.ID = PROGRESS_INC
        this.tag = tag
        this.startTime = new Date()
    }

    notify(extra: { [key: string]: any } = {}, err?: Error){
        sendProgressMsg(this.tag, this.ID, this.step, extra, err)
        this.step ++
    }

    log(name: any, extra: any, lines?: string[]) {
        const now = new Date()
        console.error(`[+] | ${this.tag} | <${name}> - ${extra} (${now.getTime() - this.startTime.getTime()} ms)`)
        if(lines?.length) {
            console.error('[>] ' + lines.map(v => `${v}`).join('\n'))
        }
        this.startTime = now
    }

}


function sendProgressMsg(tag: string, id: number, step: number, extra: { [key: string]: any } = {}, err?: Error){
    Helper.$send({
        type: RPCMsgType.PROGRESSING,
        data: {
            tag: tag,
            id: id,
            step: step,
            time: new Date().getTime(),
            extra: extra,
            error: err ? {
                message: err?.message,
                stack: err?.stack
            }: null,
        }
    })
}



function getScanPatternSize(pattern: string): number {
    if (pattern.startsWith('/') && pattern.endsWith('/')) {
        throw new Error("Regular expression patterns are not allowed")
    }

    const bytesPart = pattern.split(':', 1)[0].trim()
    if (bytesPart === '') {
        return 0
    }

    const bytes = bytesPart.split(/\s+/)
    return bytes.length
}


class Helper {
    public static libc = new Libc()
    private static _logStates: { [key: string]: LoggerState } = {}
    private static _android_api_level?: number
    private static _dataDir: string
    private static _logfiles: {[key: string]: FileHelper}

    static get dataDir(): string {
        if (!Helper._dataDir) {
            const cmdline = this.readCmdline(Process.id)
            const uid = this.libc.getuid()
            const dataDir = `/data/user/${multiuser_get_user_id(uid)}/${cmdline}`
            Helper._dataDir = dataDir
        }
        return Helper._dataDir
    }

    static setOutputDir(dir: string) {
        Config.OutputDir = dir
    }

    static get outputDir(): string {
        return Config.OutputDir ? Config.OutputDir : this.dataDir
    }

    private static _loggerPrefix(): any {
        return String(Process.getCurrentThreadId())
    }

    private static _prelog(states: { [key: string]: LoggerState }, prefix: string, ...args: any[]) {
        let state = states[prefix]
        const msg = Array.from(args).map(v => String(v)).join(' ')
        if (!state) {
            state = new LoggerState(6)
            states[prefix] = state
        }
        return state.onLog(msg)
    }

    static assert(cond: any) {
        if (!cond) {
            throw new Error(`assert false`)
        }
    }

    static $log(level: LogLevel, logger: (...args: any[]) => void, ...args: any) {
        if (level < Config.LogLevel) {
            return
        }

        const prefix = this._loggerPrefix()
        if (Config.LogCollapse) {
            const msgs = this._prelog(this._logStates, prefix, ...args)
            for (let v of msgs) {
                logger(`${prefix}|`, v)
            }
        }else{
            logger(`${prefix}|`, ...args)
        }
    }

    static $debug(...args: any) {
        this.$log(LogLevel.DEBUG, console.log, ...args)
    }

    static $info(...args: any) {
        this.$log(LogLevel.INFO, console.log, ...args)
    }

    static $warn(...args: any) {
        this.$log(LogLevel.WARN, console.log, ...args)
    }

    static $error(...args: any) {
        this.$log(LogLevel.WARN, console.error, ...args)
    }

    static walkDir(path: string, fn: AnyFunction) {
        const libc = this.libc
        const dir = libc.opendir(path)
        if (dir.isNull()) {
            console.error(`[walkDir] path[${path}] 打开失败.`)
            return null
        }
        const nameOffset = Process.pointerSize * 2 + 2 + 1
        let dirent: any
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

    static getFdLinked(fd: number) {
        return this.libc.readlink(`/proc/self/fd/${fd}`)
    }

    static getFileStreamLinked(stream: any) {
        const libc = this.libc
        const fd = libc.fileno(stream)
        let link: string | null = null
        if (fd >= 0) {
            link = libc.readlink(`/proc/self/fd/${fd}`)
        }
        return link
    }

    static readProcMaps(pid: number | string = 'self') {
        return this.readTextFile(`/proc/${pid}/maps`)
    }

    static readCmdline(pid: number | string = 'self') {
        const cmdline = this.readFile(`/proc/${pid}/cmdline`)
        const sepList = []
        let lastIdx = 0
        const u8bs = new Uint8Array(cmdline)
        for (let i = 0; i < u8bs.byteLength; i ++) {
            const b = u8bs[i]
            if (b === 0) {
                if (lastIdx < i-1) {
                    let result = ''
                    const view = u8bs.slice(lastIdx, i)
                    for (let i = 0; i < view.length; i++) {
                        result += String.fromCharCode(view[i])
                    }
                    if(result.length > 0) sepList.push(result)
                }
                lastIdx = i
            }
        }
        return sepList.join(' ')
    }

    static readFile(path: string) {
        return File.readAllBytes(path)
    }


    static openFile(pathname: string, mode: string): FileHelper {
        return new FileHelper(pathname, mode)
    }

    static isFilePath(str: string): boolean {
        if(!str.length) {
            return false
        }
        return str[0] === '/' && str[str.length - 1] !== '/'
    }

    static joinPath(dir: string, file: string): string {
        if(!dir.length){
            return dir
        }
        return dir.replace(/\/+$/, '') + '/' + file.replace(/^\/+/, '')
    }


    static readTextFile(path: string) {
        return File.readAllText(path)
    }

    static dumpProcMaps(tag: string, pid: number | string = 'self') {
        const prog = new ProgressNotify('Helper.dumpProcMaps')
        const sm = this.readProcMaps(pid)
        this.saveFile(tag, sm, 'w', saveFileSource.procMaps)
        prog.log(pid, `[${sm.length}]${tag}`)
    }

    static dumpTextFile(tag: string, srcPath: string) {
        const prog = new ProgressNotify('Helper.dumpTextFile')
        const sm = File.readAllText(srcPath)
        this.saveFile(tag, sm, 'w', saveFileSource.textFile)
        prog.log(srcPath, `[${sm.length}](${tag})`)
    }

    static backtrace({ context = undefined, addrHandler = DebugSymbol.fromAddress, backtracer = Backtracer.ACCURATE }: {
        context?: undefined | CpuContext,
        addrHandler?: (addr: any) => any,
        backtracer?: Backtracer,
    } = {}) {
        const prog = new ProgressNotify('Helper.backtrace')
        const stacks = Thread.backtrace(context, backtracer).map(addr => {
            return `${addrHandler(addr)}`
        })
        prog.log(Process.getCurrentThreadId(), '', stacks)
    }


    static saveFile(tag: string, bs: string | ArrayBuffer | null, mode: string, source: string) {
        if (bs === null || bs === undefined) {
            return false
        }

        if (Config.OnRPC) {
            let buff: ArrayBuffer
            if(bs instanceof String) {
                const enc = new TextEncoder()
                const view = enc.encode(bs as string)
                buff = view.buffer as ArrayBuffer
            }else{
                buff = bs as ArrayBuffer
            }
            Helper.$send({
                type: RPCMsgType.SAVE_FILE,
                data: {
                    source,
                    filepath: Helper.joinPath(this.outputDir, tag),
                    mode,
                }
            }, buff)
        }else{
            const savedFile = new File(tag, mode)
            savedFile.write(bs)
            savedFile.close()
        }
    }


    static androidGetApiLevel(): number {
        if (this._android_api_level === undefined) {
            this._android_api_level = parseInt(this.libc.__system_property_get('ro.build.version.sdk'))
        }
        return this._android_api_level
    }

    static memoryReadDo(address: NativePointer, size: number, doFunc: (makeReadable: () => MemoryProtect[], makeRecovery: ()=>MemoryProtect[])=>void ) {
        const page_infos: MemoryProtect[] = []
        const makeReadable = () => {
            let cur = address
            const end = address.add(size)
            while (cur < end) {
                const range = Process.findRangeByAddress(cur)
                let originProts = ''
                let newProts = ''
                let readable = false
                if(range !== null) {
                    cur = range.base.add(range.size)
                    originProts = range.protection
                    if(range.protection[0] !== 'r') {
                        newProts = 'r' + originProts.slice(1)
                    }else{
                        readable = true
                    }
                }
                page_infos.push({
                    readable,
                    originProts,
                    newProts,
                    range,
                })
            }
            for(let v of page_infos) {
                if(v.range && v.newProts !== '') {
                    v.protectResult = Memory.protect(v.range.base, v.range.size, v.newProts)
                    if(v.protectResult) {
                        v.readable = true
                    }
                }
            }
            return page_infos
        }

        const makeRecovery = () => {
            for (let v of page_infos) {
                if (v.range && v.newProts !== '' && v.protectResult) {
                    v.recoverResult = Memory.protect(v.range.base, v.range.size, v.originProts)
                }
            }
            return page_infos
        }

        doFunc(makeReadable, makeRecovery)
    }


    static memoryReadPageDo(base: NativePointer, size: number, doFunc: (page: MemoryPage)=>boolean){
        const page_infos: MemoryPage[] = []
        let cur = base
        const end = base.add(size)
        let isAbort = false

        while (!isAbort && cur < end) {
            const range = Process.findRangeByAddress(cur)
            let mp: MemoryPage = {
                base: cur.and(ptr(Process.pageSize-1).not()),
                size: Process.pageSize,
                protectResult: false,
                originProts: '',
                newProts: '',
                readable: false,
                range,
            }

            if (range !== null) {
                mp.originProts = range.protection
                if (range.protection[0] !== 'r') {
                    mp.newProts = 'r' + mp.originProts.slice(1)
                    mp.protectResult = Memory.protect(mp.base, mp.size, mp.newProts)
                    if(mp.protectResult) {
                        mp.readable = true
                    }
                }else{
                    mp.readable = true
                }
                isAbort = doFunc(mp)
                if(mp.protectResult) {
                    mp.recoverResult = Memory.protect(mp.base, mp.size, mp.originProts)
                }
            }
            page_infos.push(mp)
            cur = mp.base.add(mp.size)
        }

        return page_infos
    }

    static newBatchSender(source: string): BatchSender {
        return new BatchSender(source)
    }

    static getLogfile(tag: string, mode: string): FileHelper {
        const filepath = Helper.isFilePath(tag) ? tag : Helper.joinPath(Helper.outputDir, tag)
        let fp = Helper._logfiles[filepath]
        if (!fp) {
            fp = Helper.openFile(filepath, mode)
            Helper._logfiles[filepath] = fp
        }
        return fp
    }

    static $send(message: any, data?: ArrayBuffer | number[] | null): void {
        send(message, data)
    }


    static scanMemory(
        scanRange: { base: NativePointer, size: number },
        pattern: string,
        { limit = Process.pageSize, maxMatchNum = -1, onMatch }: {
            limit?: number,
            maxMatchNum?: number,
            onMatch?: (match: MemoryScanMatch) => boolean,
        },
    ) {
        const patternSize = getScanPatternSize(pattern)
        const { base, size } = scanRange
        const end = base.add(size)
        let cursor = base

        const scanResults: MemoryScanMatch[] = []
        this.memoryReadDo(base, size, (makeReadable, makeRecovery) => {
            makeReadable()
            while (cursor < end) {
                const nextCur = cursor.add(Math.min(Number(end.sub(cursor)), limit))
                const cur = Number(cursor.sub(base)) > patternSize ? cursor.sub(patternSize) : cursor
                let results: MemoryScanMatch[]
                try {
                    results = Memory.scanSync(cur, Number(nextCur.sub(cur)), pattern)
                    if (onMatch) {
                        results = results.filter(v => onMatch(v))
                    }
                    scanResults.push(...results)
                } catch (e) {
                    // TODO: Error: access violation accessing 0xxxxxx
                    console.error(`[scanMemory] e[${e}]`)
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

}


export { Helper as help }





declare global {
    const help: Helper
}


export const print = Helper.$log.bind(Helper, LogLevel._MUST_LOG, console.log)
export const printErr = Helper.$log.bind(Helper, LogLevel._MUST_LOG, console.error)


declare global {
    function print(...args: any): void
    function printErr(...args: any): void
}

setGlobalProperties({
    'help': Helper,
    'print': print,
    'printErr': printErr,
})


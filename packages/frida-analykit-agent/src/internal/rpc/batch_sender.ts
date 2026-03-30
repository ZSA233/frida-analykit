import { Config } from "../../config/index.js"
import { RPCMsgType } from "./messages.js"

type BatchItem = {
    message: any
    data?: ArrayBuffer | null
}

export type BatchSenderSendFn = (message: any, data: ArrayBuffer) => void

export type BatchSenderOptions = {
    maxBatchBytes?: number
    sender?: BatchSenderSendFn
}

export class BatchSender {
    private readonly _source: string
    private readonly _maxBatchBytes: number | null
    private readonly _sender?: BatchSenderSendFn
    private _batchByteLength = 0
    private _batchList: BatchItem[] = []

    constructor(source: string, options: BatchSenderOptions = {}) {
        this._source = source
        this._maxBatchBytes = normalizeMaxBatchBytes(options.maxBatchBytes ?? Config.BatchMaxBytes)
        this._sender = options.sender
    }

    send(message: any, data?: ArrayBuffer | null): void {
        const payloadSize = data?.byteLength || 0
        if (
            this._maxBatchBytes !== null &&
            this._batchList.length > 0 &&
            this._batchByteLength + payloadSize > this._maxBatchBytes
        ) {
            this.flush()
        }

        this._batchList.push({
            message,
            data,
        })
        this._batchByteLength += payloadSize

        if (
            this._maxBatchBytes !== null &&
            this._batchList.length === 1 &&
            payloadSize > this._maxBatchBytes
        ) {
            this.flush()
        }
    }

    rpcResponse(): [] | [any, ArrayBuffer] {
        if (!this._batchList.length) {
            return []
        }
        const totalBuffLen = this._batchList.reduce((acc, cur) => acc + (cur.data?.byteLength || 0), 0)
        const batchBuff = new Uint8Array(totalBuffLen)
        const buffSizeList = []
        const messageList = []
        let buffIndex = 0

        for (const data of this._batchList) {
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
            },
        }, batchBuff.buffer]
    }

    clear(): void {
        this._batchList = []
        this._batchByteLength = 0
    }

    flush(): void {
        const [message, buff] = this.rpcResponse()
        if (!message || buff === undefined) {
            return
        }
        const sender = this._sender ?? send
        sender(message, buff)
        this.clear()
    }
}

function normalizeMaxBatchBytes(value?: number): number | null {
    if (value === undefined) {
        return null
    }
    if (!Number.isFinite(value) || value <= 0) {
        return null
    }
    return Math.floor(value)
}

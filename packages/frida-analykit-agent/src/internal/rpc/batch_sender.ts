import { RPCMsgType } from "./messages.js"

export class BatchSender {
    private readonly _source: string
    private _batchList: {
        message: any
        data?: ArrayBuffer | null
    }[] = []

    constructor(source: string) {
        this._source = source
    }

    send(message: any, data?: ArrayBuffer | null): void {
        this._batchList.push({
            message,
            data,
        })
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
    }

    flush(): void {
        const [message, buff] = this.rpcResponse()
        if (!message || !buff) {
            return
        }
        send(message, buff)
        this.clear()
    }
}

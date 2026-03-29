import { RPCMsgType } from "../../internal/rpc/messages.js"

export type ProgressMessageSender = (tag: string, id: number, step: number, extra?: Record<string, unknown>, err?: Error) => void

let progressInc = 0

function defaultSendProgress(tag: string, id: number, step: number, extra: Record<string, unknown> = {}, err?: Error): void {
    send({
        type: RPCMsgType.PROGRESSING,
        data: {
            tag,
            id,
            step,
            time: Date.now(),
            extra,
            error: err ? {
                message: err.message,
                stack: err.stack,
            } : null,
        },
    })
}

export class ProgressNotify {
    private readonly id: number
    readonly tag: string
    private step = 0
    private startTime: Date
    private readonly sendProgress: ProgressMessageSender

    constructor(tag: string, sendProgress: ProgressMessageSender = defaultSendProgress) {
        progressInc++
        this.id = progressInc
        this.tag = tag
        this.startTime = new Date()
        this.sendProgress = sendProgress
    }

    notify(extra: Record<string, unknown> = {}, err?: Error): void {
        this.sendProgress(this.tag, this.id, this.step, extra, err)
        this.step++
    }

    log(name: unknown, extra: unknown, lines?: string[]): void {
        const now = new Date()
        console.error(`[+] | ${this.tag} | <${name}> - ${extra} (${now.getTime() - this.startTime.getTime()} ms)`)
        if (lines?.length) {
            console.error("[>] " + lines.map((value) => `${value}`).join("\n"))
        }
        this.startTime = now
    }
}

export function createProgressFacade(sendProgress?: ProgressMessageSender) {
    return {
        create: (tag: string) => new ProgressNotify(tag, sendProgress),
    } as const
}

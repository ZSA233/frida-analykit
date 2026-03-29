import { Config, LogLevel } from "../../config/index.js"
import { FixedQueue } from "../../internal/collections/fixed_queue.js"

export class LoggerState {
    private readonly msgs: FixedQueue<string>
    private readonly baseMsgs: FixedQueue<string>
    private matchOffset = 0
    private readonly depth: number
    private counter = 1

    constructor(depth: number = 1) {
        this.depth = depth
        this.msgs = new FixedQueue<string>(depth)
        this.baseMsgs = new FixedQueue<string>(depth)
    }

    onLog(msg: string): string[] {
        const earliestMsg = this.msgs.push(msg)
        if (earliestMsg === undefined) {
            this.baseMsgs.push(msg)
            return [msg]
        }

        let outMsgs: string[] = []
        if (this.baseMsgs.index(this.matchOffset) === msg) {
            this.matchOffset++
            if (this.matchOffset === this.depth) {
                this.counter++
                this.matchOffset = 0
            }
        } else {
            if (this.counter > 1) {
                outMsgs = (this.baseMsgs.list as string[]).map((value) => `#${this.counter}# | ${value}`)
                outMsgs.push(msg)
                this.baseMsgs.clear()
            } else {
                outMsgs = [msg]
            }
            this.baseMsgs.push(msg)
            this.matchOffset = 0
            this.counter = 1
        }
        return outMsgs
    }
}

export type HelperLogContext = {
    logStates: Record<string, LoggerState>
}

function loggerPrefix(): string {
    return String(Process.getCurrentThreadId())
}

function prelog(states: Record<string, LoggerState>, prefix: string, ...args: unknown[]): string[] {
    let state = states[prefix]
    const msg = Array.from(args).map((value) => String(value)).join(" ")
    if (!state) {
        state = new LoggerState(6)
        states[prefix] = state
    }
    return state.onLog(msg)
}

export function logMessage(
    context: HelperLogContext,
    level: LogLevel,
    logger: (...args: unknown[]) => void,
    ...args: unknown[]
): void {
    if (level < Config.LogLevel) {
        return
    }

    const prefix = loggerPrefix()
    if (Config.LogCollapse) {
        const msgs = prelog(context.logStates, prefix, ...args)
        for (const value of msgs) {
            logger(`${prefix}|`, value)
        }
        return
    }

    logger(`${prefix}|`, ...args)
}

export function createLogFacade(context: HelperLogContext) {
    return {
        debug: (...args: unknown[]) => logMessage(context, LogLevel.DEBUG, console.log, ...args),
        info: (...args: unknown[]) => logMessage(context, LogLevel.INFO, console.log, ...args),
        warn: (...args: unknown[]) => logMessage(context, LogLevel.WARN, console.log, ...args),
        error: (...args: unknown[]) => logMessage(context, LogLevel.ERROR, console.error, ...args),
    } as const
}

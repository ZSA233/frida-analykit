import { Config } from "../../config/index.js"
import { BatchSender } from "../../internal/rpc/batch_sender.js"
import { libc } from "../../native/libc/libc.js"
import type { FileHelper } from "../fs/index.js"
import type { LoggerState } from "../log/index.js"
import { readCmdline } from "../proc/index.js"

const AID_USER_OFFSET = 100000

function multiuserGetUserId(uid: number): number {
    return Math.floor(uid / AID_USER_OFFSET)
}

export type HelperRuntimeContext = {
    logStates: Record<string, LoggerState>
    logFiles: Record<string, FileHelper>
    androidApiLevel?: number
    dataDir?: string
}

export function createHelperRuntimeContext(): HelperRuntimeContext {
    return {
        logStates: {},
        logFiles: {},
    }
}

export function createRuntimeFacade(context: HelperRuntimeContext) {
    const getDataDir = (): string => {
        if (!context.dataDir) {
            const cmdline = readCmdline(Process.id)
            const uid = libc.getuid()
            context.dataDir = `/data/user/${multiuserGetUserId(uid)}/${cmdline}`
        }
        return context.dataDir
    }

    return {
        assert(condition: unknown, message = "assert false"): void {
            if (!condition) {
                throw new Error(message)
            }
        },
        send(message: any, data?: ArrayBuffer | number[] | null): void {
            send(message, data)
        },
        setOutputDir(dir: string): void {
            Config.OutputDir = dir
        },
        getOutputDir(): string {
            return Config.OutputDir ? Config.OutputDir : getDataDir()
        },
        getDataDir,
        androidApiLevel(): number {
            if (context.androidApiLevel === undefined) {
                context.androidApiLevel = parseInt(libc.__system_property_get("ro.build.version.sdk"))
            }
            return context.androidApiLevel
        },
        newBatchSender(source: string): BatchSender {
            return new BatchSender(source)
        },
    } as const
}

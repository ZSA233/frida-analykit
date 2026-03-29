import { Config, LogLevel } from "../config/index.js"
import { createFsFacade } from "./fs/index.js"
import { createLogFacade, logMessage } from "./log/index.js"
import { createMemFacade } from "./mem/index.js"
import { createProcFacade } from "./proc/index.js"
import { createProgressFacade } from "./progress/index.js"
import { createHelperRuntimeContext, createRuntimeFacade } from "./runtime/index.js"

const helperContext = createHelperRuntimeContext()
const log = createLogFacade(helperContext)
const runtime = createRuntimeFacade(helperContext)
const progress = createProgressFacade()
const proc = createProcFacade()
const mem = createMemFacade()
const fs = createFsFacade({
    getOutputDir: runtime.getOutputDir,
    logFiles: helperContext.logFiles,
    isRpcEnabled: () => Config.OnRPC,
    send: runtime.send,
})

export const help = {
    log,
    progress,
    fs,
    proc,
    mem,
    runtime,
    $debug: log.debug,
    $info: log.info,
    $warn: log.warn,
    $error: log.error,
    assert: runtime.assert,
    $send: runtime.send,
} as const

export type HelperFacade = typeof help

export const print = (...args: unknown[]): void => {
    logMessage(helperContext, LogLevel._MUST_LOG, console.log, ...args)
}

export const printErr = (...args: unknown[]): void => {
    logMessage(helperContext, LogLevel._MUST_LOG, console.error, ...args)
}

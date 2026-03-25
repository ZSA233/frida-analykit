type InjectedConfig = {
    OnRPC?: boolean
    OutputDir?: string
    LogLevel?: number
    LogCollapse?: boolean
}

const injectedConfig = ((globalThis as typeof globalThis & {
    __FRIDA_ANALYKIT_CONFIG__?: InjectedConfig
}).__FRIDA_ANALYKIT_CONFIG__) || {}

export function setGlobalProperties(keyValues: { [key: string]: any }): void {
    for (let [k, v] of Object.entries(keyValues)) {
        if (k in globalThis) {
            throw new Error(`global property[${k}] exists already`)
        }
        ;(globalThis as typeof globalThis & { [key: string]: unknown })[k] = v
    }
}



export const enum LogLevel {
    DEBUG = 0,
    INFO = 1,
    WARN = 2,
    ERROR = 3,


    _MUST_LOG = 9999999,
}



declare global {
    const enum LogLevel {
        DEBUG = 0,
        INFO = 1,
        WARN = 2,
        ERROR = 3,
    }

}

export class Config {
    static OnRPC: boolean = injectedConfig.OnRPC ?? false
    static OutputDir?: string = injectedConfig.OutputDir
    static LogLevel: number = injectedConfig.LogLevel ?? LogLevel.INFO
    static LogCollapse: boolean = injectedConfig.LogCollapse ?? true
}



setGlobalProperties({
    'Config': Config,
})

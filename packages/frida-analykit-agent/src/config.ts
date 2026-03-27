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


export const LogLevel = {
    DEBUG: 0,
    INFO: 1,
    WARN: 2,
    ERROR: 3,
    _MUST_LOG: 9999999,
} as const

export type LogLevel = (typeof LogLevel)[keyof typeof LogLevel]



declare global {
    const LogLevel: {
        DEBUG: number
        INFO: number
        WARN: number
        ERROR: number
        _MUST_LOG: number
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
    'LogLevel': LogLevel,
})

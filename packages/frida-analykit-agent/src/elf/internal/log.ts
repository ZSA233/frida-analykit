import { Config } from "../../config/index.js"
import { help } from "../../helper/index.js"
import { RPCMsgType } from "../../internal/rpc/messages.js"
import type { ElfModuleX } from "../module.js"

export type ElfSymbolLogFields = Record<string, unknown>

export type ElfSymbolLogContext = {
    tag: string
    module: ElfModuleX
}

let activeLogDepth = 0

export function emitElfSymbolCallLog(context: ElfSymbolLogContext, symbol: string, fields: ElfSymbolLogFields = {}): void {
    if (activeLogDepth > 0) {
        return
    }

    const payload = {
        tag: context.tag,
        module_name: context.module.name,
        module_base: context.module.base,
        symbol,
        fields,
    }

    activeLogDepth += 1
    try {
        // Keep the hook-side logging path minimal. Some presets intentionally wrap libc/process
        // primitives, so avoid extra runtime queries here and only guard against re-entry.
        if (Config.OnRPC) {
            help.runtime.send({
                type: RPCMsgType.ELF_SYMBOL_CALL_LOG,
                data: payload,
            })
            return
        }

        const rendered = Object.entries(fields)
            .map(([key, value]) => `${key}[${String(value)}]`)
            .join(", ")
        help.$info(`[elf][${context.tag}] ${context.module.name}!${symbol}${rendered ? ` ${rendered}` : ""}`)
    } finally {
        activeLogDepth -= 1
    }
}

export function readCStringSafe(value: NativePointer | null | undefined): string {
    if (!value || value.isNull()) {
        return ""
    }
    try {
        return value.readCString() || ""
    } catch {
        return ""
    }
}

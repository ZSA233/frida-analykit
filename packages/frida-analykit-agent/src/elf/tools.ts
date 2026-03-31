import { setGlobalProperties } from "../config/index.js"
import { snapshotElfModule } from "./snapshot.js"
import { ElfSymbolHooks } from "./symbol_hooks.js"
import { ElfFileFixer, ElfModuleX } from "./module.js"
import type { ElfModuleTarget, ElfSnapshotOptions, ElfSnapshotSummary, ElfSymbolHooksOptions } from "./types.js"

function isElfModuleX(value: ElfModuleTarget): value is ElfModuleX {
    return value instanceof ElfModuleX
}

function isModule(value: ElfModuleTarget): value is Module {
    return typeof value === "object" && value !== null && "base" in value && "size" in value
}

export class ElfTools {
    static findModuleByName(name: string, tryFix = false): ElfModuleX | null {
        const mod = Process.findModuleByName(name)
        if (mod === null) {
            return null
        }
        return this.loadFromModule(mod, tryFix)
    }

    static getModuleByName(name: string, tryFix = false): ElfModuleX {
        const modx = this.findModuleByName(name, tryFix)
        if (modx === null) {
            throw new Error(`[ElfTools] module not found: ${name}`)
        }
        return modx
    }

    static loadFromModule(mod: Module, tryFix = false): ElfModuleX {
        const fixers = tryFix ? [new ElfFileFixer(mod.path)] : undefined
        return new ElfModuleX(mod, fixers)
    }

    static createSymbolHooks(target: ElfModuleTarget, options: ElfSymbolHooksOptions = {}): ElfSymbolHooks {
        return new ElfSymbolHooks(this.resolveTarget(target, options.tryFix), options)
    }

    static snapshot(target: ElfModuleTarget, options: ElfSnapshotOptions & { tryFix?: boolean } = {}): ElfSnapshotSummary {
        return snapshotElfModule(this.resolveTarget(target, options.tryFix), options)
    }

    private static resolveTarget(target: ElfModuleTarget, tryFix = false): ElfModuleX {
        if (isElfModuleX(target)) {
            return target
        }
        if (typeof target === "string") {
            return this.getModuleByName(target, tryFix)
        }
        if (isModule(target)) {
            return this.loadFromModule(target, tryFix)
        }
        throw new Error("[ElfTools] unsupported target")
    }
}

setGlobalProperties({
    ElfTools,
})

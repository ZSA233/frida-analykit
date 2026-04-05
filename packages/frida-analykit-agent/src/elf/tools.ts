import { setGlobalProperties } from "../config/index.js"
import { dumpElfModule } from "./dump.js"
import { ElfFileMetadataPatcher } from "./internal/file_metadata_patcher.js"
import { ElfSymbolHooks } from "./symbol_hooks.js"
import { ElfModuleX } from "./module.js"
import type { ElfModuleDumpOptions, ElfModuleDumpSummary, ElfModuleTarget, ElfSymbolHooksOptions } from "./types.js"

function isElfModuleX(value: ElfModuleTarget): value is ElfModuleX {
    return value instanceof ElfModuleX
}

function isModule(value: ElfModuleTarget): value is Module {
    return typeof value === "object" && value !== null && "base" in value && "size" in value
}

export class ElfTools {
    static findModuleByName(name: string, augmentMetadata = false): ElfModuleX | null {
        const mod = Process.findModuleByName(name)
        if (mod === null) {
            return null
        }
        return this.loadFromModule(mod, augmentMetadata)
    }

    static getModuleByName(name: string, augmentMetadata = false): ElfModuleX {
        const modx = this.findModuleByName(name, augmentMetadata)
        if (modx === null) {
            throw new Error(`[ElfTools] module not found: ${name}`)
        }
        return modx
    }

    static loadFromModule(mod: Module, augmentMetadata = false): ElfModuleX {
        const metadataPatchers = augmentMetadata ? [new ElfFileMetadataPatcher(mod.path)] : undefined
        return new ElfModuleX(mod, metadataPatchers)
    }

    static createSymbolHooks(target: ElfModuleTarget, options: ElfSymbolHooksOptions = {}): ElfSymbolHooks {
        return new ElfSymbolHooks(this.resolveTarget(target, options.augmentMetadata), options)
    }

    static dumpModule(target: ElfModuleTarget, options: ElfModuleDumpOptions = {}): ElfModuleDumpSummary {
        return dumpElfModule(this.resolveTarget(target, options.augmentMetadata), options)
    }

    private static resolveTarget(target: ElfModuleTarget, augmentMetadata = false): ElfModuleX {
        if (isElfModuleX(target)) {
            return target
        }
        if (typeof target === "string") {
            return this.getModuleByName(target, augmentMetadata)
        }
        if (isModule(target)) {
            return this.loadFromModule(target, augmentMetadata)
        }
        throw new Error("[ElfTools] unsupported target")
    }
}

setGlobalProperties({
    ElfTools,
})

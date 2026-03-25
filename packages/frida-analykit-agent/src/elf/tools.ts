import { setGlobalProperties } from "../config.js"
import { ElfFileFixer, ElfModuleX } from "./module.js"



export class ElfTools {

    static findModuleByName(name: string, tryFix: boolean = false): ElfModuleX | null {
        const mod = Process.findModuleByName(name)
        if (mod === null) {
            return null
        }
        return this.loadFromModule(mod, tryFix)
    }

    static getModuleByName(name: string, tryFix: boolean = false): ElfModuleX { 
        const modx = this.findModuleByName(name, tryFix)
        if (modx === null) {
            throw new Error(`[getModuleByName] ${name} module not found.`)
        }
        return modx
    }

    static loadFromModule(mod: Module, tryFix: boolean = false): ElfModuleX {
        const fixers = tryFix ? [new ElfFileFixer(mod.path)] : undefined
        return new ElfModuleX(mod, fixers)
    }
}


setGlobalProperties({
    ElfTools,
})
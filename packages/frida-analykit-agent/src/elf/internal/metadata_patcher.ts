import type { ElfModuleX } from "../module.js"

export interface ElfModuleMetadataPatcher {
    patch(modx: ElfModuleX): boolean
}

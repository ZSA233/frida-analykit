import { ElfSymbolHooks } from "../src/elf/index.js";
import { castElfSymbolHooks, type EnhancedElfSymbolHooks } from "../src/elf/enhanced/index.js";

declare const hooks: ElfSymbolHooks;

const enhanced: EnhancedElfSymbolHooks = castElfSymbolHooks(hooks);

enhanced.getpid();
enhanced.gettid();
enhanced.dlopen();
enhanced.open();
enhanced.__system_property_get();

void enhanced;

import { ElfSymbolHooks, ElfTools, type ElfResolvedSymbol, type ElfSnapshotSummary } from "../src/elf/index.js";

declare const mod: Module;

const hooks: ElfSymbolHooks = ElfTools.createSymbolHooks(mod, { logTag: "sample" });
const summary: ElfSnapshotSummary = ElfTools.snapshot("libc.so", { tag: "sample" });
const resolved: ElfResolvedSymbol | null = hooks.resolve("getpid");
const found: ElfResolvedSymbol | null = hooks.findSymbol("gettid");
const listed: ElfResolvedSymbol[] = hooks.listSymbols();
const addressMap: Record<string, ElfResolvedSymbol> = hooks.addressMap();

hooks.attach("getpid", function (impl: AnyFunction) {
    return impl();
}, "uint", []);

void summary;
void resolved;
void found;
void listed;
void addressMap;

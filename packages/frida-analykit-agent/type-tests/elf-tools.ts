import { ElfSymbolHooks, ElfTools, type ElfModuleDumpSummary, type ElfResolvedSymbol } from "../src/elf/index.js";

declare const mod: Module;

const hooks: ElfSymbolHooks = ElfTools.createSymbolHooks(mod, { logTag: "sample", augmentMetadata: true });
const summary: ElfModuleDumpSummary = ElfTools.dumpModule("libc.so", { tag: "sample", augmentMetadata: true });
const resolved: ElfResolvedSymbol | null = hooks.resolve("getpid");
const found: ElfResolvedSymbol | null = hooks.findSymbol("gettid");
const listed: ElfResolvedSymbol[] = hooks.listSymbols();
const addressMap: Record<string, ElfResolvedSymbol> = hooks.addressMap();
const dumpKinds = summary.artifacts.map((item) => item.kind);
const fixupsArtifactKind: Extract<(typeof dumpKinds)[number], "fixups"> = "fixups";

// @ts-expect-error legacy option was removed
ElfTools.createSymbolHooks(mod, { tryFix: true });

// @ts-expect-error legacy option was removed
ElfTools.dumpModule("libc.so", { tag: "sample", tryFix: true });

// @ts-expect-error rebuilt dump artifact is no longer public
const legacyArtifactKind: Extract<(typeof dumpKinds)[number], "rebuilt"> = "rebuilt";

hooks.attach("getpid", function (impl: AnyFunction) {
    return impl();
}, "uint", []);

void summary;
void resolved;
void found;
void listed;
void addressMap;
void fixupsArtifactKind;
void legacyArtifactKind;

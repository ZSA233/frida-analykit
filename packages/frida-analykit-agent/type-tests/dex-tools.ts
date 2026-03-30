import { DexTools, type DexDumpSummary } from "../src/dex/index.js";

const summary: DexDumpSummary = DexTools.dumpAllDex({ tag: "sample", maxBatchBytes: 4096 });
const loaders = DexTools.enumerateClassLoaderDexFiles();

void summary;
void loaders;

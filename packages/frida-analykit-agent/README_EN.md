# @zsa233/frida-analykit-agent

🌍 Language: [中文](https://github.com/ZSA233/frida-analykit/blob/stable/packages/frida-analykit-agent/README.md) | English

`@zsa233/frida-analykit-agent` is the runtime package for custom TypeScript Frida agents. It is typically consumed by workspaces generated with `frida-analykit gen dev`, but it can also be used manually in any `frida-compile` project.

## Package Positioning

- The package root `@zsa233/frida-analykit-agent` is a slim entry that only keeps lightweight foundational capabilities.
- Heavier capabilities are exposed through explicit subpaths so `/rpc` does not pull the entire runtime by default.
- The public capability surface is organized around RPC, helper, process, JNI, ELF, SSL, Dex, and selected native bindings.

## Install

Install it in your agent workspace:

```sh
npm install @zsa233/frida-analykit-agent
```

Then build with `frida-compile`:

```sh
npx frida-compile index.ts -o _agent.js -c
```

## Capability Overview Table

| Capability | Import Path | Primary Use | Visible From Slim Root Entry |
|:---|:---|:---|:---|
| `config` | `@zsa233/frida-analykit-agent/config` | Access foundational config objects such as `Config` and `LogLevel` | Yes |
| `rpc` | `@zsa233/frida-analykit-agent/rpc` | Install the minimal RPC / REPL runtime | No |
| `helper` | `@zsa233/frida-analykit-agent/helper` | Use the `help` facade for logging, file, memory, and runtime helpers | Yes |
| `process` | `@zsa233/frida-analykit-agent/process` | Use `proc` and process-map helper capabilities | Yes |
| `bridges` | `@zsa233/frida-analykit-agent/bridges` | Access Java / ObjC / Swift bridge wrappers | No |
| `jni` | `@zsa233/frida-analykit-agent/jni` | Use `JNIEnv`, JNI wrappers, and explicit-signature calls | No |
| `ssl` | `@zsa233/frida-analykit-agent/ssl` | Use `SSLTools`, BoringSSL locating, and keylog helpers | No |
| `elf` | `@zsa233/frida-analykit-agent/elf` | Parse ELF files, create `ElfSymbolHooks`, and stream raw/fixed dumps plus `fixups.json` | No |
| `elf/enhanced` | `@zsa233/frida-analykit-agent/elf/enhanced` | Manually import common symbol-hook presets without bloating the core bundle | No |
| `dex` | `@zsa233/frida-analykit-agent/dex` | Enumerate class-loader dex files and dump them to Python in streaming mode | No |
| `native/libart` | `@zsa233/frida-analykit-agent/native/libart` | Access low-level ART symbol bindings | No |
| `native/libssl` | `@zsa233/frida-analykit-agent/native/libssl` | Access low-level OpenSSL / BoringSSL symbol bindings | No |
| `native/libc` | `@zsa233/frida-analykit-agent/native/libc` | Access low-level libc wrappers and common syscalls | No |

## Common Usage

### Minimal Agent

The minimal agent only needs `/rpc`:

```ts
import "@zsa233/frida-analykit-agent/rpc"

setImmediate(() => {
  console.log("pid =", Process.id)
})
```

### Import Capabilities On Demand

If you need more capabilities, explicit capability imports are recommended:

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help } from "@zsa233/frida-analykit-agent/helper"
import "@zsa233/frida-analykit-agent/process"
import { JNIEnv } from "@zsa233/frida-analykit-agent/jni"
import { SSLTools } from "@zsa233/frida-analykit-agent/ssl"
import { ElfTools } from "@zsa233/frida-analykit-agent/elf"
import { castElfSymbolHooks } from "@zsa233/frida-analykit-agent/elf/enhanced"
import { DexTools } from "@zsa233/frida-analykit-agent/dex"
import { Libart } from "@zsa233/frida-analykit-agent/native/libart"
import { Libssl } from "@zsa233/frida-analykit-agent/native/libssl"
import { libc } from "@zsa233/frida-analykit-agent/native/libc"

setImmediate(() => {
  console.log("api level =", help.runtime.androidApiLevel())
  console.log("maps =", proc.loadProcMap().items.length)
  console.log("cmdline =", help.proc.readCmdline())
  console.log("jni env =", JNIEnv.$handle)
  console.log("ssl guesses =", SSLTools.guess().length)
  console.log("main module =", ElfTools.findModuleByName("libc.so")?.name)
  console.log("elf hook facade =", castElfSymbolHooks(ElfTools.createSymbolHooks("libc.so", { observeDlsym: false })).findSymbol("getpid")?.name)
  console.log("dex loaders =", DexTools.enumerateClassLoaderDexFiles().length)
  console.log("libart loaded =", Libart.$getModule().name)
  console.log("libssl module =", Libssl.$getModule().name)
  console.log("cwd =", libc.getcwd())
})
```

If you only need lightweight foundational capabilities, you can also import from the package root:

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help, proc } from "@zsa233/frida-analykit-agent"
```

Explicit subpaths are still the recommended default because they make bundle size and import boundaries easier to control.

## Advanced Capabilities

### RPC / REPL

After `/rpc` is installed, the agent exposes structured RPC exports for Python CLI calls such as `script.eval(...)`, `script.jsh(...)`, REPL handle access, and scope calls.

- The RPC eval context reads `globalThis` dynamically on every execution.
- Whether a capability is visible depends on whether you explicitly imported the corresponding module in `index.ts`.
- `/rpc` no longer pulls the full runtime by default and only keeps the minimal foundation.
- `Libart`, `Libssl`, and `Libc` follow the same on-demand visibility rules.

### ElfTools / SymbolHooks

After explicit import, you can use `/elf` as the core capability and `/elf/enhanced` as the optional preset layer:

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { ElfTools } from "@zsa233/frida-analykit-agent/elf"
import { castElfSymbolHooks } from "@zsa233/frida-analykit-agent/elf/enhanced"

setImmediate(() => {
  const hooks = ElfTools.createSymbolHooks("libc.so", { logTag: "demo", observeDlsym: false })
  const enhanced = castElfSymbolHooks(hooks)
  enhanced.getpid()
  const summary = ElfTools.dumpModule("libc.so", { tag: "manual" })
  console.log("dump =", summary.dumpId, summary.moduleName, summary.relativeDumpDir)
})
```

- `/elf` now provides `ElfTools.createSymbolHooks(...)`, `ElfTools.dumpModule(...)`, and the existing module-resolution APIs.
- `ElfSymbolHooks` is a module-level symbol-hook state object with lazy symbol registry support, `dlsym` coordination, and explicit-signature `attach(...)`.
- `/elf/enhanced` only adds common presets when you import it manually; it does not auto-register into `globalThis` or the core bundle.
- `dumpModule()` sends `ELF_MODULE_DUMP_BEGIN -> BATCH(ELF_MODULE_DUMP_CHUNKS) -> ELF_MODULE_DUMP_END`.
- Python writes ELF outputs to `script.elftools.output_dir` first, then falls back to `agent.datadir/elftools`, using `<output-root>/<tag?>/`; symbol call logs go to `symbols.log` in the same leaf directory.
- In RPC mode, `outputDir` and `relative_dump_dir` are still forwarded, but the host only records them in `manifest.json`; the actual directory is still chosen from `script.elftools.output_dir` plus a single-level `tag`.
- Each dump now exports `*.raw.so`, `*.fixed.so`, `fixups.json`, `symbols.json`, `proc_maps.txt`, and `manifest.json` by default.
- `fixups.json` records the stage-owned patches needed to replay `raw` into `fixed`; each stage is emitted by the real repair step, which makes replay possible and patch ownership easier to inspect.
- For the `fixups.json` field legend, stage semantics, and replay rules, see [docs/elf-fixups.md](https://github.com/ZSA233/frida-analykit/blob/stable/docs/elf-fixups.md).

### DexTools

After explicit import, you can use:

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { DexTools } from "@zsa233/frida-analykit-agent/dex"

setImmediate(() => {
  const loaders = DexTools.enumerateClassLoaderDexFiles()
  console.log("dex loaders =", loaders.length)
  DexTools.dumpAllDex({ tag: "manual" })
})
```

- `DexTools` currently provides `enumerateClassLoaderDexFiles()` and `dumpAllDex(...)`.
- `dumpAllDex()` sends `DEX_DUMP_BEGIN -> BATCH(DEX_DUMP_FILES) -> DEX_DUMP_END`.
- The default max batch size comes from Python config `script.rpc.batch_max_bytes`, and on the agent side this maps to `Config.BatchMaxBytes`.
- A single oversized dex is still sent as its own batch without further slicing, and Python writes to `script.dextools.output_dir` first, then falls back to `agent.datadir/dextools`.
- In RPC mode, `dumpDir` is still forwarded, but the host only records it in `manifest.json`; the actual directory is still chosen from `script.dextools.output_dir` plus a single-level `tag`.
- Python writes one `manifest.json` for each dex dump and stores the exported dex file list in its `files` field; the old `classes.json` file is no longer kept.

### JNI / Native Bindings

The `jni` and `native/*` capabilities are intended for cases where you need direct ART, JNI, or libc/libssl symbol access.

```ts
import { JNIEnv } from "@zsa233/frida-analykit-agent/jni"
import { Libart } from "@zsa233/frida-analykit-agent/native/libart"
import { Libssl } from "@zsa233/frida-analykit-agent/native/libssl"
import { libc } from "@zsa233/frida-analykit-agent/native/libc"

setImmediate(() => {
  console.log("jni env =", JNIEnv.$handle)
  console.log("libart =", Libart.$getModule().name)
  console.log("libssl =", Libssl.$getModule().name)
  console.log("pid =", libc.getpid())
})
```

- Member facades such as `jobject.$method(name, sig)`, `.$call(name, sig, ...args)`, and `jclass.$staticMethod(name, sig)` all require an explicit `sig`.
- JNI returns wrappers by default and does not automatically convert to JS primitives or strings.
- Accessors provide `withLocal(...)` to scope local-reference lifetimes.
- Importing `native/libart`, `native/libssl`, or `native/libc` registers the corresponding global object on demand.

## Debugging And Non-Public Content

- Wildcard `./*` exports are no longer provided, and deep internal path compatibility is not promised.
- `src/internal/*` and other deep internal paths are not public APIs and should not be used directly in production agents.
- The repository contains a private package, `@zsa233/frida-analykit-agent-device-tests`, which only serves `tests/device` regression coverage and is not included in this package's `dependencies` or `exports`.
- If you need to debug bundle contents, export boundaries, or device behavior, prefer the repository README files, type tests, and device tests over unpublished internal paths.

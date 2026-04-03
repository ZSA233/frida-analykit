# MCP Quickstart

## Recommended first step

- Start the server with a user-prepared startup TOML, then read `frida://service/config`.
- Confirm `frida://service/config` reports `quick_path.state == "ready"` before calling `session_open_quick`.
- Use `session_open_quick` as the default MCP entrypoint.
- Do not hand-write `config.toml`, `package.json`, `index.ts`, or `_agent.js` unless you need advanced customization outside the quick path.

## What `session_open_quick` does

1. Validates the target app, mode, template, and official capability list.
2. Generates a minimal TypeScript workspace that always imports `@zsa233/frida-analykit-agent/rpc` first.
3. Resolves `template` as a curated preset and `capabilities` as additive preload globals, then emits explicit original binding references for those imports in the generated `index.ts`.
4. Either copies `bootstrap_path` as a separate imported file or inlines `bootstrap_source` directly into the generated `index.ts`.
5. Reuses one shared lightweight runtime toolchain cache for the current agent package spec instead of running `npm install` for every signature workspace.
6. Builds `_agent.js` with `frida-compile` from the current MCP environment `PATH`.
7. Writes a matching `config.toml` from the fixed MCP startup config.
8. Reuses the cached workspace on later calls with the same signature.
9. Copies the effective workspace into a dedicated session-history directory named `{yyyyMMdd-HHMMSS-shortid}`.
10. Opens or reuses the Frida session through the normal MCP session manager.

Before the server even reaches this point, MCP startup already performs one host-side warmup:

- verifies `prepared_cache_root` is writable
- verifies `frida-compile` is available in the MCP process `PATH`
- verifies `npm` when the shared runtime toolchain cache must be installed or repaired
- prepares or reuses the shared runtime toolchain cache
- runs one minimal compile sanity probe

If startup warmup fails, MCP exits before serving stdio instead of exposing a degraded quick path.

## Important inputs

- `app`: target package name or remembered attach target identifier.
- `mode`: `attach` or `spawn`.
- `template`: one of `minimal`, `process_probe`, `java_bridge`, `dex_probe`, `ssl_probe`, or `elf_probe`. Template is a curated preset.
- `capabilities`: official runtime capability names only. Capabilities are additive preload globals on top of the template preset.
- `bootstrap_path`: optional local `.ts` or `.js` file to copy into the prepared workspace and import during bundle startup.
- `bootstrap_source`: optional inline module-level initialization code for hooks that must be registered immediately after injection.
- Server and output defaults are inherited from `frida://service/config`, not from per-call parameters.
- `frida-compile` must already be available in the MCP process `PATH`. `npm` is also required whenever MCP must install or repair the shared quick runtime toolchain cache. Quick path does not install either tool for you.

## Template, capabilities, and bootstrap

- The generated `index.ts` is the effective quick compile entry. Open it when you need to confirm the exact imports and bootstrap code that MCP compiled.
- Use `template + capabilities` when quick session itself should preload globals that later `eval_js`, `/rpc`, or a small bootstrap module will read directly.
- Quick capability retention now comes from explicit original binding references in the generated `index.ts`, not from hidden agent-side retain helpers.
- bootstrap_source is inlined directly into that generated `index.ts`.
- bootstrap_path remains a separate import, but quick path only copies that one file into the prepared workspace.
- Keep quick bootstrap_path files self-contained. If they need sibling relative imports or a larger local dependency graph, use `session_open(config_path, ...)` instead.
- If `bootstrap_path` is the main script you want to maintain in your repo, prefer `template="minimal"` and keep the real imports in that file.
- If you maintain `bootstrap_path` or your own workspace, prefer explicit imports plus an explicit reference such as `void DexTools` instead of relying on a bare import to survive bundler pruning.
- `session_open_quick` is not a general import injection mechanism.
- `elf_enhanced` is not a quick capability. Import `@zsa233/frida-analykit-agent/elf/enhanced` from `bootstrap_path`, `bootstrap_source`, or a custom workspace when needed.

## What quick globals to expect

- Quick `minimal` only gives you `/rpc` and normal Frida globals. Do not assume analykit globals such as `Config`, `help`, `proc`, `DexTools`, `SSLTools`, or `ElfTools`.
- `template` is the main quick-session discovery mechanism for LLM use. Read `frida://docs/mcp/tools` when you need the stable mapping from template or capability name to usable globals.
- Many non-minimal capabilities pull helper/config bindings transitively. Treat only the documented primary globals as the stable contract.
- On Android, `Java` often exists even without `bridges` because it is a Frida bridge global, not a quick-capability guarantee.

## Common starter recipes

These snippets assume the session is already open.

### Dex dump

Use `template="dex_probe"` when the task is dex enumeration or dumping.

```js
DexTools.enumerateClassLoaderDexFiles().length
DexTools.dumpAllDex("case-001")
```

### Process and helper probes

Use `template="process_probe"` when you want fast process-state checks.

```js
help.proc.readCmdline()
proc.loadProcMap().items.length
```

### Java and JNI inspection

Use `template="java_bridge"` when you need explicit JNI wrappers in addition to the normal Android `Java` bridge.

```js
JNIEnv.$handle
Java.performNow(() => Java.use("android.app.ActivityThread").currentPackageName())
```

### SSL keylog and BoringSSL scans

Use `template="ssl_probe"` for libssl or BoringSSL-oriented validation.

```js
SSLTools.attachLibsslKeylogFunc("sslkey.log")
BoringSSL.loadFromModule(Process.getModuleByName("libsscronet.so")).scanKeylogFunc()
```

### ELF snapshot and symbol work

Use `template="elf_probe"` for module-level ELF inspection.

```js
ElfTools.findModuleByName("libc.so")?.name
ElfTools.snapshot("libc.so", { tag: "manual" })
```

### Native bindings

Use additive native capabilities when you only need the low-level binding.

```js
Libart.$getModule().name
Libssl.$getModule().name
(new Libc()).getpid()
```

`native_libc` exposes `Libc` in `eval_js`, not the exported `libc` instance. Create an instance yourself inside the JavaScript snippet when needed.

## Cache behavior

- Quick-session artifacts are stored under the MCP prepared cache directory and keyed by a deterministic signature.
- Quick path keeps a shared lightweight `node_modules` cache for runtime dependencies under `prepared_cache_root/_toolchains/<digest>` and reuses `prepared_cache_root/npm-cache` as the npm cache root.
- This sharing is keyed by prepared cache root plus agent package spec, not by Python virtual environment.
- Quick path does not install `frida-compile`, `frida`, or `@types/node` inside each prepared workspace.
- The signature includes the bootstrap mode, bootstrap file content hash when `bootstrap_path` is used, and the effective startup-config defaults that affect generated files.
- Same signature means the same generated workspace and compiled `_agent.js`.
- Prepared cache is internal. The live MCP session still gets its own copied archive directory under `session_history_root`, and that copied `workspace/` tree is the one users should browse later.
- Use `prepared_session_inspect` to inspect generated imports, config summary, and the last build outcome.
- Use `prepared_session_prune` to remove old or unused cached workspaces.

## When to use the low-level path

- Use `session_open` only when you already maintain your own workspace and want MCP to consume that explicit `config.toml` or legacy YAML config.
- `session_open` is a low-level session tool after MCP has started successfully; it is not a bypass for quick-path startup warmup failures.
- If `frida-compile` is missing, or if `npm` is missing when MCP must install or repair the shared quick runtime toolchain cache, MCP startup itself fails fast. Fix the MCP environment and restart the server before using any MCP tool.
- After a quick session is open, continue normal MCP work with `eval_js`, `install_snippet`, `call_snippet`, and `session_recover`.

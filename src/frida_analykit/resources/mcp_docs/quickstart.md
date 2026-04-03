# MCP Quickstart

## Recommended first step

- Start the server with a user-prepared startup TOML, then read `frida://service/config`.
- Confirm `frida://service/config` reports `quick_path.state == "ready"` before calling `session_open_quick`.
- Use `session_open_quick` as the default MCP entrypoint.
- Do not hand-write `config.toml`, `package.json`, `index.ts`, or `_agent.js` unless you need advanced customization outside the quick path.

## What `session_open_quick` does

1. Validates the target app, mode, template, and official capability list.
2. Generates a minimal TypeScript workspace that always imports `@zsa233/frida-analykit-agent/rpc` first.
3. Applies `template`, `capabilities`, `bootstrap_path`, and `bootstrap_source` to the generated `index.ts`.
4. Builds `_agent.js` with `frida-compile` from the current MCP environment `PATH`.
5. Writes a matching `config.toml` from the fixed MCP startup config.
6. Reuses cached quick-session artifacts when the same signature is requested again.
7. Creates a `session_root/{yyyyMMdd-HHMMSS-shortid}` directory for the live session.
8. Opens or reuses the Frida session through the normal MCP session manager.

Before the server even reaches this point, MCP startup already performs one host-side warmup:

- verifies `prepared_cache_root` is writable
- verifies `frida-compile` and `npm` are available in the MCP process `PATH`
- runs one quick build sanity check

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
- bootstrap_source is inlined directly into that generated `index.ts`.
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
const summary = DexTools.dumpAllDex("case-001")
summary.transferId
```

- `DexTools.dumpAllDex()` returns after the agent has finished streaming RPC payloads, not after the host has definitely flushed every file to disk.
- Use the returned `transferId` with `tail_logs` or `frida://session/logs`.
- Wait for a `source="host"` log entry that matches `[dex] complete <transferId>` before treating the dump as finished.
- Treat `[dex] incomplete transfer ...` or `size mismatch` messages as failures.

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
- Prepared cache is internal.
- Use `session_root` for the current session record and `session_workspace` for the runtime workspace and output files of the current session.
- Use `prepared_session_inspect` to inspect generated imports, config summary, and the last build outcome.
- Use `prepared_session_prune` to remove old or unused cached workspaces.

## When to use the low-level path

- Use `session_open` only when you already maintain your own workspace and want MCP to consume that explicit `config.toml` or legacy YAML config.
- `session_open` is a low-level session tool after MCP has started successfully; it is not a bypass for quick-path startup warmup failures.
- If `frida-compile` is missing, or if `npm` is missing when MCP must install or repair the shared quick runtime toolchain cache, MCP startup itself fails fast. Fix the MCP environment and restart the server before using any MCP tool.
- After a quick session is open, continue normal MCP work with `eval_js`, `install_snippet`, `call_snippet`, and `session_recover`.

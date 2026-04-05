# Tool Guide

## Session tools

- `session_open_quick`: prepare or reuse a cached minimal workspace, always import `/rpc`, preload the template preset plus additive global capabilities, optionally import a copied `bootstrap_path` file or inline `bootstrap_source` into the generated `index.ts`, build with `frida-compile` from MCP `PATH`, write `config.toml` from the fixed startup config, then open or reuse the session.
- `session_open`: open or reuse the current device session from an explicit workspace config.
- `session_status`: inspect current state without mutating snippet state.
- `session_close`: detach, clear scope, and stop owned remote resources.
- `session_recover`: reopen a broken session for the same remembered target.
- `prepared_session_inspect`: inspect the current or named quick-session artifact.
- `prepared_session_prune`: delete unused quick-session cache entries without touching the active session.

## Execution tools

- `eval_js`: one-off JavaScript execution through the async, Promise-aware RPC path. Use this first for fast validation.
- `install_snippet`: install a named snippet and keep its root handle alive through the async session manager.
- Successful installs also persist the snippet source under `session_root/snippets/...` for later audit, but that archive is not auto-replayed.
- `call_snippet`: call the snippet root or one of its dotted methods through the same Promise-aware async path.
- `inspect_snippet`: inspect the last known root snapshot and state.
- `remove_snippet`: call `dispose()` when present, then release the handle.
- `list_snippets`: list tracked snippet metadata for the current session.
- `tail_logs`: read recent session logs from both the script logger and host-side MCP handlers. Each entry includes `source = "script"` or `source = "host"`.

## Usage advice for LLMs

- Prefer `eval_js` for quick exploration.
- Prefer `session_open_quick` over hand-written workspace setup when operating as an LLM through MCP.
- Read `frida://service/config` first, then treat server/output defaults as fixed for this MCP process.
- Confirm `frida://service/config` reports `quick_path.state == "ready"` before assuming quick build inputs are usable.
- Treat `frida://service/config.session_root` as the configured parent root for user-facing MCP session records.
- Treat `session_status.session_root` as the actual directory for the current session record, and `session_status.session_workspace` as the runtime workspace copied there.
- `template` is a curated preset and `capabilities` are additive preload globals.
- The generated `index.ts` is the effective quick compile entry for `session_open_quick`.
- Quick path assumes both `frida-compile` and `npm` are already installed in the MCP environment `PATH`.
- `prepared_cache_root` is internal cache; inspect the current session through `session_root` and `session_workspace`.
- Prefer `bootstrap_path` when the initialization hook should be editable in a normal repo file.
- Prefer `template="minimal"` when `bootstrap_path` already owns the real imports.
- Keep quick `bootstrap_path` files self-contained. If they need sibling relative imports or a local dependency graph, use `session_open(config_path, ...)`.
- In `bootstrap_path` or a custom workspace, prefer explicit imports plus an explicit reference over relying on a bare import to stay in the final bundle.
- bootstrap_source is inlined into the generated `index.ts`; use it only for small inline hook logic that must exist as soon as the quick bundle loads.
- `session_open_quick` is not a general import injection interface.
- `elf_enhanced` is not a quick capability; import it from `bootstrap_path`, `bootstrap_source`, or a custom workspace instead.
- If you need `a.b.c` style access, encode it in JavaScript or in a snippet method instead of assuming REPL-style sync property chaining.
- Promote stable logic to `install_snippet` once repeated calls are likely.
- `frida://session/snippets` and `list_snippets` still describe live in-memory snippet state, not the durable snippet archive on disk.
- Do not turn `install_snippet` into a pre-open bootstrap mechanism; snippets are session-managed runtime controllers, not quick-session build inputs.
- In REPL, sync handles are usually better for object browsing; in MCP, assume async-only semantics and Promise-aware results.
- After each disruptive attempt, check `session_status` before continuing.
- If `_agent.js` is missing `/rpc`, either reopen through `session_open_quick` or rebuild the local runtime bundle before retrying `session_open`.
- For dex dump flows, treat `DexTools.dumpAllDex()` as the start of a host-side transfer. Read `tail_logs` and wait for a `source="host"` entry like `[dex] complete <transferId>` before declaring success.

## Quick capability catalog

Treat the items below as the stable quick-session contract for `eval_js` and snippet code.

- Some presets also expose extra globals transitively, but only the documented primary globals below should be treated as stable.
- On Android, `Java` usually exists even in `minimal` because it comes from Frida itself. `java_bridge` is mainly about JNI helpers such as `JNIEnv`, `jobject`, and `jclass`.
- `native_libc` exposes `Libc` in the eval context, not the exported `libc` singleton.

### Templates

| Template | Primary globals to assume | Typical `eval_js` probes | Notes |
|:---|:---|:---|:---|
| `minimal` | no extra analykit globals | `Process.id` | Use when `bootstrap_path` owns the real imports. |
| `process_probe` | `help`, `proc` | `help.proc.readCmdline()`, `proc.loadProcMap().items.length` | Good first stop for maps, cmdline, and runtime output helpers. |
| `java_bridge` | `JNIEnv`, `jobject`, `jclass` | `JNIEnv.$handle`, `Java.performNow(() => Java.use("android.app.ActivityThread").currentPackageName())` | `Java` may already exist on Android even without this template. |
| `dex_probe` | `DexTools` | `DexTools.enumerateClassLoaderDexFiles().length`, `DexTools.dumpAllDex("case-001").transferId` | Also brings the JNI/ART helpers needed by dex flows. |
| `ssl_probe` | `SSLTools`, `BoringSSL` | `SSLTools.attachLibsslKeylogFunc("manual")`, `BoringSSL.loadFromModule(Process.getModuleByName("libsscronet.so")).scanKeylogFunc()` | Useful for libssl and BoringSSL keylog validation. |
| `elf_probe` | `ElfTools` | `ElfTools.findModuleByName("libc.so")?.name`, `ElfTools.dumpModule("libc.so", { tag: "manual" })` | Use `bootstrap_path` for `elf/enhanced` imports. |

### Additive capabilities

| Capability | Primary globals to assume | Typical `eval_js` probes | Notes |
|:---|:---|:---|:---|
| `config` | `Config`, `LogLevel` | `Config.OnRPC`, `LogLevel.INFO` | Useful when a probe wants runtime config values. |
| `helper` | `help`, `print`, `printErr` | `help.runtime.getOutputDir()`, `print("hello")` | File, runtime, memory, and logging facade. |
| `process` | `proc` | `proc.loadProcMap().items.length` | Pulls process-map helpers; helper globals are usually present transitively. |
| `bridges` | no extra analykit globals beyond normal Frida bridge globals | `Java.available` | Mostly ensures the bridge import is present for bootstrap code. |
| `jni` | `JNIEnv`, `jobject`, `jclass` | `JNIEnv.$handle` | Use when explicit JNI wrappers are required. |
| `dex` | `DexTools` | `DexTools.dumpAllDex("case-001").transferId` | Also makes the ART binding available transitively. |
| `ssl` | `SSLTools`, `BoringSSL`, `Libssl` | `SSLTools.attachLibsslKeylogFunc("manual")` | Best fit for SSL secret logging and BoringSSL scans. |
| `elf` | `ElfTools` | `ElfTools.dumpModule("libc.so", { tag: "manual" })` | Module, symbol, and dump exploration. |
| `native_libart` | `Libart` | `Libart.$getModule().name` | Low-level ART binding only. |
| `native_libssl` | `Libssl` | `Libssl.$getModule().name` | Low-level libssl binding only. |
| `native_libc` | `Libc` | `(new Libc()).getpid()` | The `libc` instance export is not placed in `eval_js` globals. |

## Capability selection advice

- Choose a preset template when the workflow is obvious: `dex_probe`, `ssl_probe`, `elf_probe`, `process_probe`, or `java_bridge`.
- Add capabilities on top of the template only when later `eval_js`, snippets, or a small bootstrap module need those globals directly.
- If the main logic lives in a repo-managed `bootstrap_path`, prefer `template="minimal"` and import the real dependencies in that file.
- Do not rely on undocumented transitive globals just because they happen to be visible in one runtime build.

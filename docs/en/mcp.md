# Frida-Analykit MCP

This document is for users who run `frida-analykit-mcp` and want to expose an already prepared Frida debugging flow to an MCP client or an LLM tool workflow.

`frida-analykit-mcp` is not a replacement for the `frida-analykit` CLI. The CLI still owns environment setup, builds, server management, and the normal injection flow; the MCP server exposes debugging, logs, scripts, and recovery inside a long-lived session.

## Use Cases

- You have already installed and configured `frida-analykit`.
- The target device is connected, and the remote `frida-server` is prepared for the current environment.
- You want an MCP client or LLM to run repeated dynamic checks instead of recreating a workspace every time.
- You want to validate static-analysis findings on a real device, for example alongside JADX, IDA, or Ghidra MCP services.

Poor fits:

- Switching Frida versions from inside MCP at runtime.
- Letting MCP choose or install arbitrary `frida-server` versions.
- Treating quick sessions as a general npm package manager or hot-reload workspace.

## Prerequisites

Before starting MCP, confirm:

- The Frida version in the current Python environment is ready.
- The target device is reachable, with a fixed serial when needed.
- The remote `frida-server` is installed or reachable through the existing configuration.
- The MCP process `PATH` can find `npm` and `frida-compile`; quick sessions depend on them.

By default, a failed quick-toolchain warmup does not prevent the stdio server from starting. The failed state appears in the startup banner and in `frida://service/config.quick_path`; `session_open_quick(...)` is unavailable, but `session_open(config_path, ...)` still works for a prepared workspace.

Strict deployments can pass `--require-quick-ready` to exit non-zero when the quick path is unavailable.

## Startup Config

Minimal startup command:

```sh
frida-analykit-mcp --config ./mcp.toml
```

`mcp.toml` is a service-level config file, not the same thing as a normal agent workspace `config.toml`. It fixes defaults that should stay stable for the lifetime of the MCP process.

```toml
[mcp]
idle_timeout_seconds = 1200
session_root = "./sessions"

[server]
host = "127.0.0.1:27042"
device = "emulator-5554"
path = "/data/local/tmp/frida-server"

[agent]
datadir = "./data"
stdout = "./logs/stdout.log"
stderr = "./logs/stderr.log"

[script.dextools]
output_dir = "./data/dextools"

[script.elftools]
output_dir = "./data/elftools"

[script.nettools]
output_dir = "./data/nettools"
```

Common constraints:

- `server.path` is the current primary field; old `server.servername` is only read for compatibility.
- `--idle-timeout` can override the configured idle timeout.
- Without `--config`, MCP starts with built-in defaults.
- `frida://service/config` exposes the resolved config, `session_root`, and quick-path readiness.

## MCP Client Setup

Only `stdio` transport is currently supported. MCP clients usually register a local command:

```json
{
  "command": "frida-analykit-mcp",
  "args": ["--config", "/absolute/path/to/mcp.toml"]
}
```

Client-specific config formats differ, but they all start this local command and communicate over stdio.

## Recommended Workflow

Recommended order:

1. Read `frida://service/config` to confirm fixed config and quick-path status.
2. Read `frida://docs/mcp/index`, `frida://docs/mcp/config`, and `frida://docs/mcp/quickstart`.
3. Prefer `session_open_quick(...)` by default.
4. After the session opens, use `eval_js(...)` for one-off checks.
5. When state should be reused, install a named snippet with `install_snippet(...)`, then call it through `call_snippet(...)`.
6. Close explicitly with `session_close(...)`.

If the app crashes, detaches, or the script becomes invalid:

1. Check `session_status(...)`.
2. Then check `tail_logs(...)` or `frida://session/logs`.
3. Call `session_recover(...)` when needed.
4. Reinstall required snippets after recovery; snippets are not replayed automatically.

## Quick Session

`session_open_quick(...)` is for quickly opening a verifiable session. It automatically:

- Generates a minimal TypeScript workspace.
- Imports `@zsa233/frida-analykit-agent/rpc` and selected official capabilities.
- Compiles `_agent.js` with the `frida-compile` found in the MCP process `PATH`.
- Writes a `config.toml` that inherits defaults from `mcp.toml`.
- Reuses prepared-cache artifacts for the same parameter signature.
- Copies the prepared artifact into `session_root/{yyyyMMdd-HHMMSS-shortid}/workspace` before opening the real session.

Common inputs:

- `app`: target package name, or the attach lookup target.
- `mode`: only `attach` or `spawn`.
- `template`: an official quick preset.
- `capabilities`: official capabilities to preload on top of the template.
- `pid`: explicit process id for attach.
- `bootstrap_path` / `bootstrap_source`: initialization logic that runs before normal session use.
- `force_replace`: replace an existing live session when it targets something different.

`session_open(config_path, ...)` is the low-level entrypoint for a fully maintained workspace that MCP should consume directly.

## Bootstrap And Snippet

`bootstrap_path` and `bootstrap_source` are for initialization that must run as soon as the script is injected:

- `bootstrap_path` is best for a real `.ts` or `.js` file in your repository that should be versioned.
- `bootstrap_source` is best for short one-off inline initialization.

`install_snippet(...)` is for managed logic after the session has opened:

- Install a named controller.
- Preserve object state across repeated experiments.
- Call it repeatedly through `call_snippet(...)`.
- Clean it up explicitly with `remove_snippet(...)`.

Snippet source is archived under the current session directory in `snippets/`, but it is not replayed automatically in a new session.

## Capabilities And Globals

For MCP use, separate three layers of objects:

- Frida built-ins such as `Process` and `Module`, plus `Java` on most Android targets.
- Analykit objects explicitly promised by the selected quick template or capability.
- Transitive globals that appear as a side effect of runtime internals.

Only the second layer is a stable contract. Read `frida://docs/mcp/tools` when you need the capability mapping.

Common starter probes:

```js
help.proc.readCmdline()
proc.loadProcMap().items.length
JNIEnv.$handle
DexTools.enumerateClassLoaderDexFiles().length
ElfTools.findModuleByName("libc.so")?.name
```

Enhanced modules that do not register globals, such as `@zsa233/frida-analykit-agent/elf/enhanced`, should be imported from `bootstrap_path`, `bootstrap_source`, or a custom workspace instead of being treated as a quick capability.

## Logs And Session Directory

Each real MCP session gets its own directory under `session_root`, named like `{yyyyMMdd-HHMMSS-shortid}`.

Main contents:

- `workspace/`: the workspace used by the current session.
- `session.json`: session summary.
- `events.jsonl`: session event log.
- `snippets/`: archived source for installed snippets.

`tail_logs(...)` and `frida://session/logs` contain:

- `source="script"`: agent script logs.
- `source="host"`: MCP host-handler logs, such as dex/elf file writes, progress, and exception summaries.

For flows such as dex dump, where host-side file writes must finish, wait for the `source="host"` completion event instead of relying only on the agent-side return value.

## Limits

- Only `stdio` is supported.
- One MCP process maintains one active debug session.
- Quick sessions only allow official capability subpaths and template names.
- Quick sessions depend on external `npm` and `frida-compile`.
- Quick sessions do not manage watch or hot reload.
- Broken sessions do not recover automatically.
- Snippets are not reinstalled automatically after recovery.
- Prepared workspace caches remain on disk until pruned explicitly.

## Related Documents

- Getting started: [../../README_EN.md](../../README_EN.md)
- Workspace config: [../../src/frida_analykit/resources/scaffold/README_EN.md](../../src/frida_analykit/resources/scaffold/README_EN.md)
- Agent runtime: [../../packages/frida-analykit-agent/README_EN.md](../../packages/frida-analykit-agent/README_EN.md)
- MCP built-in resources: [../../src/frida_analykit/resources/mcp_docs](../../src/frida_analykit/resources/mcp_docs)

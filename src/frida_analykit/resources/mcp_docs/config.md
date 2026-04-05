# MCP Startup Config

`frida-analykit-mcp` can load a startup TOML with `--config <mcp.toml>`.

## What belongs in startup config

- Fixed service defaults that should not be chosen by the LLM at session-open time.
- Server connection fields such as `host`, `device`, and `path`.
- Quick-session output paths such as `agent.stdout`, `agent.stderr`, `script.dextools.output_dir`, and `script.nettools.output_dir`.
- MCP process defaults such as `idle_timeout_seconds`, `prepared_cache_root`, and `session_root`.

## Recommended flow

1. The user prepares the Frida Python environment and matching remote `frida-server`.
2. The user starts `frida-analykit-mcp --config ./mcp.toml`.
3. MCP startup runs quick-path preflight + warmup and fails fast if the host-side toolchain is not ready.
4. The MCP client reads `frida://service/config`.
5. The MCP client uses `session_open_quick(...)` without trying to override server or output paths.

## Example shape

```toml
[mcp]
idle_timeout_seconds = 1200
session_root = "./sessions"

[server]
host = "127.0.0.1:27042"
path = "/data/local/tmp/frida-server"

[agent]
stdout = "./logs/outerr.log"
stderr = "./logs/outerr.log"

[script.nettools]
output_dir = "./data/nettools"
```

## Important limits

- Startup config is fixed for the lifetime of one MCP server process.
- `frida://service/config` includes a structured `quick_path` readiness summary for normal MCP use.
- `frida://service/config` also exposes both `config_path_raw` and the resolved absolute `config_path`.
- `frida://service/config.session_root` is the configured parent root where per-session `{yyyyMMdd-HHMMSS-shortid}` directories will be created.
- `session_open_quick` inherits these defaults; it does not accept `host`, `device`, `path`, or version-selection fields.
- `session_status.session_root` is the current session directory.
- `session_status.session_workspace` is the runtime `workspace/` subdirectory for that session.
- If `session_root` is omitted, MCP defaults it to `<prepared_cache_root>/sessions`.
- `bootstrap_path` and `bootstrap_source` are still per-session quick-open inputs because they are target-specific initialization code, not service-wide defaults.
- Quick-session `template` and `capabilities` only control preload globals from official runtime entrypoints; they are not an arbitrary import injection channel.
- Quick path requires `frida-compile` and `npm` in the MCP environment `PATH`.
- Prepared cache stays internal. Use `session_workspace` to inspect the files for the current quick session.
- `session_open(config_path, ...)` is a low-level session tool after MCP has started successfully; it is not a startup-bypass path when quick warmup fails.
- That explicit low-level path still expects your own `config.toml` or legacy YAML config plus a ready `_agent.js` bundle.

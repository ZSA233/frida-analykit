# MCP Startup Config

`frida-analykit-mcp` can load a startup TOML with `--config <mcp.toml>`.

## What belongs in startup config

- Fixed service defaults that should not be chosen by the LLM at session-open time.
- Server connection fields such as `host`, `device`, and `path`.
- Quick-session output paths such as `agent.stdout`, `agent.stderr`, `script.dextools.output_dir`, and `script.nettools.ssl_log_secret`.
- MCP process defaults such as `idle_timeout_seconds`, `prepared_cache_root`, and `session_history_root`.

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
session_history_root = "./session-history"

[server]
host = "127.0.0.1:27042"
path = "/data/local/tmp/frida-server"

[agent]
stdout = "./logs/outerr.log"
stderr = "./logs/outerr.log"

[script.nettools]
ssl_log_secret = "./data/nettools/sslkey"
```

## Important limits

- Startup config is fixed for the lifetime of one MCP server process.
- `frida://service/config` includes a structured `quick_path` readiness summary for normal MCP use.
- `frida://service/config` also exposes the effective `session_history_root`.
- `session_open_quick` inherits these defaults; it does not accept `host`, `device`, `path`, or version-selection fields.
- `session_history_root` is the user-facing archive root for MCP sessions.
- Each real MCP session gets a dedicated `{yyyyMMdd-HHMMSS-shortid}` directory under `session_history_root`.
- If `session_history_root` is omitted, MCP defaults it to `<prepared_cache_root>/sessions`.
- `bootstrap_path` and `bootstrap_source` are still per-session quick-open inputs because they are target-specific initialization code, not service-wide defaults.
- Quick-session `template` and `capabilities` only control preload globals from official runtime entrypoints; they are not an arbitrary import injection channel.
- Quick-path startup warmup reuses `prepared_cache_root/npm-cache` and `prepared_cache_root/_toolchains/<digest>`; this cache sharing is keyed by prepared cache root plus agent package spec, not by Python virtual environment.
- Prepared cache stays internal. The copied session-history workspace is the user-facing place to inspect effective session files later.
- `session_open(config_path, ...)` is a low-level session tool after MCP has started successfully; it is not a startup-bypass path when quick warmup fails.
- That explicit low-level path still expects your own `config.toml` or legacy YAML config plus a ready `_agent.js` bundle.
- `npm` may be reported as skipped in `quick_path` when MCP can reuse a ready shared toolchain cache without reinstalling anything.

# MCP Startup Config

`frida-analykit-mcp` can load a startup TOML with `--config <mcp.toml>`.

## What belongs in startup config

- Fixed service defaults that should not be chosen by the LLM at session-open time.
- Server connection fields such as `host`, `device`, and `path`.
- Quick-session output paths such as `agent.stdout`, `agent.stderr`, `script.dextools.output_dir`, and `script.nettools.ssl_log_secret`.
- MCP process defaults such as `idle_timeout_seconds` and `prepared_cache_root`.

## Recommended flow

1. The user prepares the Frida Python environment and matching remote `frida-server`.
2. The user starts `frida-analykit-mcp --config ./mcp.toml`.
3. The MCP client reads `frida://service/config`.
4. The MCP client uses `session_open_quick(...)` without trying to override server or output paths.

## Example shape

```toml
[mcp]
idle_timeout_seconds = 1200

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
- `session_open_quick` inherits these defaults; it does not accept `host`, `device`, `path`, or version-selection fields.
- `bootstrap_path` and `bootstrap_source` are still per-session quick-open inputs because they are target-specific initialization code, not service-wide defaults.
- Use `session_open(config_path, ...)` only when you already maintain a fully explicit workspace and `config.toml` or legacy YAML config.

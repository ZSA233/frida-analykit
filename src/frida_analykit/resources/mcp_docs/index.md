# Frida-Analykit MCP

`frida-analykit-mcp` is a stdio MCP server for long-lived Frida validation sessions on a real device.

## Preconditions

- Prefer reading `frida://service/config` before opening a quick session.
- Prefer `session_open_quick` unless you already manage a custom `config.toml` or legacy YAML config together with `_agent.js`.
- The injected `_agent.js` must import `@zsa233/frida-analykit-agent/rpc`. The quick path guarantees this automatically.
- Use one active target per MCP server process.

## Recommended sequence

1. Read `frida://service/config`, `frida://docs/mcp/config`, `frida://docs/mcp/quickstart`, and `frida://docs/mcp/workflow`.
2. Call `session_open_quick`.
3. Use `eval_js` for one-off probes.
4. Use `install_snippet` when the same controller will be reused.
5. Use `tail_logs`, `inspect_snippet`, and the session resources between attempts.
6. Call `session_close` when the task is finished.

## Important limits

- The server keeps one active debug session only.
- The MCP public surface is async-core only; the old sync compatibility manager is not part of the supported API anymore.
- MCP tools always use the async, Promise-aware RPC path instead of the REPL-style sync handle browsing path.
- `session_open` is still available as the low-level explicit path when you already prepared your own workspace.
- `session_open_quick` inherits server and output defaults from the fixed startup TOML loaded at process start.
- Quick-session cache entries stay on disk until `prepared_session_prune` removes them.
- MCP quick session does not become a general package manager; it only imports official `@zsa233/frida-analykit-agent` subpaths.
- It does not watch or hot reload the TypeScript workspace.
- It does not auto-recover a broken session.
- It does not auto-reinstall snippets after `session_recover`.

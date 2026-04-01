# Frida-Analykit MCP

`frida-analykit-mcp` is a stdio MCP server for long-lived Frida validation sessions on a real device.

## Preconditions

- Build `config.jsfile` before opening a session.
- The injected `_agent.js` must import `@zsa233/frida-analykit-agent/rpc`.
- Use one active target per MCP server process.

## Recommended sequence

1. Read `frida://docs/mcp/workflow`.
2. Call `session_open`.
3. Use `eval_js` for one-off probes.
4. Use `install_snippet` when the same controller will be reused.
5. Use `tail_logs`, `inspect_snippet`, and the session resources between attempts.
6. Call `session_close` when the task is finished.

## Important limits

- The server keeps one active debug session only.
- It does not build, watch, or hot reload the TypeScript workspace.
- It does not auto-recover a broken session.
- It does not auto-reinstall snippets after `session_recover`.

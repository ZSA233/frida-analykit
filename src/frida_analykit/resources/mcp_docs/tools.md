# Tool Guide

## Session tools

- `session_open_quick`: prepare or reuse a cached minimal workspace, optionally import `bootstrap_path` or compile `bootstrap_source`, write `config.toml` from the fixed startup config, then open or reuse the session.
- `session_open`: open or reuse the current device session.
- `session_status`: inspect current state without mutating snippet state.
- `session_close`: detach, clear scope, and stop owned remote resources.
- `session_recover`: reopen a broken session for the same remembered target.
- `prepared_session_inspect`: inspect the current or named quick-session artifact.
- `prepared_session_prune`: delete unused quick-session cache entries without touching the active session.

## Execution tools

- `eval_js`: one-off JavaScript execution through the async, Promise-aware RPC path. Use this first for fast validation.
- `install_snippet`: install a named snippet and keep its root handle alive through the async session manager.
- `call_snippet`: call the snippet root or one of its dotted methods through the same Promise-aware async path.
- `inspect_snippet`: inspect the last known root snapshot and state.
- `remove_snippet`: call `dispose()` when present, then release the handle.
- `list_snippets`: list tracked snippet metadata for the current session.
- `tail_logs`: read recent logs captured from the script logger.

## Usage advice for LLMs

- Prefer `eval_js` for quick exploration.
- Prefer `session_open_quick` over hand-written workspace setup when operating as an LLM through MCP.
- Read `frida://service/config` first, then treat server/output defaults as fixed for this MCP process.
- Prefer `bootstrap_path` when the initialization hook should be editable in a normal repo file.
- Use `bootstrap_source` only for small inline hook logic that must exist as soon as the quick bundle loads.
- If you need `a.b.c` style access, encode it in JavaScript or in a snippet method instead of assuming REPL-style sync property chaining.
- Promote stable logic to `install_snippet` once repeated calls are likely.
- Do not turn `install_snippet` into a pre-open bootstrap mechanism; snippets are session-managed runtime controllers, not quick-session build inputs.
- In REPL, sync handles are usually better for object browsing; in MCP, assume async-only semantics and Promise-aware results.
- Do not rely on removed compat owners such as a sync MCP manager or a mixed sync/async wrapper facade.
- After each disruptive attempt, check `session_status` before continuing.
- If `_agent.js` is missing `/rpc`, either reopen through `session_open_quick` or rebuild the local runtime bundle before retrying `session_open`.

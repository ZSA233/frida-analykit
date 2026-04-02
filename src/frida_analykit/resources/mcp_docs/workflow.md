# MCP Workflow

## Open and reuse

- Start by reading `frida://service/config`.
- Start with `session_open_quick(app, mode, capabilities?, template?, bootstrap_path?, bootstrap_source?, ...)` unless a custom workspace already exists.
- Use `session_open(config_path, mode, pid?)` only for explicit advanced workspaces that you prepared yourself.
- Reuse the same session for follow-up validation instead of reopening it.
- If the target changes, either call `session_close` first or reopen with `force_replace=true`.
- Inspect `frida://session/prepared` or call `prepared_session_inspect` when you need to confirm which quick artifact is currently active.

## Probe vs managed snippet

- Use `eval_js` for short, disposable checks.
- Put dotted access such as `a.b.c`, getter reads, and small projections directly inside the JavaScript source instead of assuming REPL-style handle browsing.
- Use `bootstrap_path` when the bootstrap logic should live in a user-visible repo file.
- Use `bootstrap_source` only for small inline code that must run as soon as the quick bundle loads, such as early `spawn`-time hooks.
- Use `install_snippet(name, source)` when the logic should stay installed across multiple calls.
- Use `call_snippet(name, method?, args?)` to drive the installed controller.
- When repeated inspection is needed, prefer a snippet method that returns a structured plain object over many small handle traversals.
- Use `remove_snippet(name)` to dispose managed state deterministically.

## State inspection

- Read `frida://session/current` for current target and state.
- Read `frida://session/snippets` for retained snippet metadata.
- Read `frida://session/logs` or call `tail_logs(limit)` for recent script logs.

## Finish cleanly

- Prefer `session_close` when analysis ends.
- Idle timeout is a fallback cleanup path, not the primary one.
- Prepared quick-session cache is retained after close; prune it explicitly when it is no longer useful.

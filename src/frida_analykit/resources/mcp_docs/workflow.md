# MCP Workflow

## Open and reuse

- Start with `session_open(config_path, mode, pid?)`.
- Reuse the same session for follow-up validation instead of reopening it.
- If the target changes, either call `session_close` first or reopen with `force_replace=true`.

## Probe vs managed snippet

- Use `eval_js` for short, disposable checks.
- Use `install_snippet(name, source)` when the logic should stay installed across multiple calls.
- Use `call_snippet(name, method?, args?)` to drive the installed controller.
- Use `remove_snippet(name)` to dispose managed state deterministically.

## State inspection

- Read `frida://session/current` for current target and state.
- Read `frida://session/snippets` for retained snippet metadata.
- Read `frida://session/logs` or call `tail_logs(limit)` for recent script logs.

## Finish cleanly

- Prefer `session_close` when analysis ends.
- Idle timeout is a fallback cleanup path, not the primary one.

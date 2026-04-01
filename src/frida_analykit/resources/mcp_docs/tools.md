# Tool Guide

## Session tools

- `session_open`: open or reuse the current device session.
- `session_status`: inspect current state without mutating snippet state.
- `session_close`: detach, clear scope, and stop owned remote resources.
- `session_recover`: reopen a broken session for the same remembered target.

## Execution tools

- `eval_js`: one-off JavaScript execution. Use this first for fast validation.
- `install_snippet`: install a named snippet and keep its root handle alive.
- `call_snippet`: call the snippet root or one of its dotted methods.
- `inspect_snippet`: inspect the last known root snapshot and state.
- `remove_snippet`: call `dispose()` when present, then release the handle.
- `list_snippets`: list tracked snippet metadata for the current session.
- `tail_logs`: read recent logs captured from the script logger.

## Usage advice for LLMs

- Prefer `eval_js` for quick exploration.
- Promote stable logic to `install_snippet` once repeated calls are likely.
- After each disruptive attempt, check `session_status` before continuing.
- If `_agent.js` is missing `/rpc`, rebuild the local runtime bundle before retrying.

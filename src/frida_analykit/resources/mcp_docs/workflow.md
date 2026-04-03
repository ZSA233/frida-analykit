# MCP Workflow

## Open and reuse

- Start by reading `frida://service/config`.
- Confirm `frida://service/config` shows `quick_path.state == "ready"` before assuming `session_open_quick` can compile.
- Read `frida://docs/mcp/tools` when you need the mapping from quick template or capability name to stable `eval_js` globals and example probes.
- Start with `session_open_quick(app, mode, capabilities?, template?, bootstrap_path?, bootstrap_source?, ...)` unless a custom workspace already exists.
- Use `session_open(config_path, mode, pid?)` only for explicit advanced workspaces that you prepared yourself.
- Treat the generated quick `index.ts` as the effective compile entry when you need to inspect what MCP actually built.
- Every real MCP session gets a dedicated `session_root` directory named `{yyyyMMdd-HHMMSS-shortid}`. Read `session_status` or `frida://session/current` to find it.
- Treat `template` as the preset and `capabilities` as additive preload globals for `/rpc`, `eval_js`, or a small bootstrap module.
- Reuse the same session for follow-up validation instead of reopening it.
- If the target changes, either call `session_close` first or reopen with `force_replace=true`.
- Inspect `frida://session/prepared` or call `prepared_session_inspect` when you need to confirm which quick artifact is currently active.

## Probe vs managed snippet

- Use `eval_js` for short, disposable checks.
- Put dotted access such as `a.b.c`, getter reads, and small projections directly inside the JavaScript source instead of assuming REPL-style handle browsing.
- Use `bootstrap_path` when the bootstrap logic should live in a user-visible repo file.
- If `bootstrap_path` owns the main imports, prefer `template="minimal"` and keep the dependencies in that file.
- Keep quick `bootstrap_path` files self-contained. If they need sibling relative imports or a larger local dependency graph, switch to `session_open(config_path, ...)`.
- In bootstrap or custom workspace code, import and reference required bindings explicitly instead of assuming a bare import will always survive bundler pruning.
- bootstrap_source is inlined into the generated `index.ts`; use it only for small inline code that must run as soon as the quick bundle loads, such as early `spawn`-time hooks.
- Keep non-global helpers such as `elf_enhanced` in `bootstrap_path`, `bootstrap_source`, or a custom workspace instead of quick capabilities.
- Use `install_snippet(name, source)` when the logic should stay installed across multiple calls.
- Successful installs also persist the snippet source under the current `session_root/snippets/` directory for later inspection.
- Use `call_snippet(name, method?, args?)` to drive the installed controller.
- When repeated inspection is needed, prefer a snippet method that returns a structured plain object over many small handle traversals.
- Use `remove_snippet(name)` to dispose managed state deterministically.

## State inspection

- Read `frida://session/current` for current target and state.
- Read `frida://session/snippets` for retained live snippet metadata.
- Read `frida://session/logs` or call `tail_logs(limit)` for recent session logs.
- `tail_logs` includes both script-side logs and host-side handler logs, distinguished by `source`.
- For dex dump flows, wait until `tail_logs` shows a host entry like `[dex] complete <transferId>` before treating the output files in `session_workspace` as finished.
- Use `session_workspace` from `frida://session/current` to inspect the runtime workspace, and `session_root` to inspect `session.json`, `events.jsonl`, and `snippets/`.

## Broken and recover

- If `session_status` reports `state == "broken"`, stop issuing more `eval_js` or snippet calls in that session.
- Read `frida://docs/mcp/recovery` or check `tail_logs` before reopening.
- Call `session_recover` explicitly.
- Recover keeps the same `session_root` and `session_workspace`.
- Reinstall only the snippets that are still needed after recover. Snippet metadata may remain visible, but inactive snippets are not auto-replayed.

## Finish cleanly

- Prefer `session_close` when analysis ends.
- Idle timeout is a fallback cleanup path, not the primary one.
- Prepared quick-session cache is retained after close; prune it explicitly when it is no longer useful.

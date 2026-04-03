# Recovery and Failure Handling

## Broken session

When Frida detaches, the MCP session becomes `broken`.

- Existing live handles are invalidated.
- Snippet metadata stays visible, but those snippets become `inactive`.
- The server will not auto-reattach and will not auto-replay snippets.

## Recovery path

1. Read `session_status` or `frida://session/current`.
2. Call `session_recover`.
3. Reinstall only the snippets that are still needed.
4. Continue validation in the recovered session.
5. Call `session_close` when the validation branch is finished.

The session root does not change across recover. Use `session_status.session_root` for the record directory and `session_status.session_workspace` for the runtime workspace before and after recovery.

## Crash and bad snippet behavior

- A snippet may crash the target process after injection.
- Treat every crash as evidence first; do not assume the device or host is the root cause without checking state.
- Use `tail_logs` and the session resources before deciding to reopen or discard the attempt.
- `tail_logs` may include both script logs and host-side processing logs. Host-side entries such as `[dex] ...` can confirm whether file transfers actually completed.

## Missing `/rpc`

If session open fails with an RPC runtime mismatch, the loaded `_agent.js` does not expose the required RPC runtime.

- If possible, switch to `session_open_quick`, which always regenerates a minimal bundle with `/rpc` imported first.
- Check `frida://service/config` if the failure might be caused by an unexpected host, device, or output-path setup on the MCP side.
- Otherwise rebuild `_agent.js` with the local `@zsa233/frida-analykit-agent` runtime from this checkout.
- Re-run the bundle build.
- Retry `session_open` after the rebuilt artifact is ready.

## Missing quick toolchain

If MCP startup fails before the stdio server is ready, the MCP environment may not expose `frida-compile` or `npm` in `PATH`, or the compile sanity probe may have failed.

- Quick path does not install `frida-compile` or `npm` for you.
- Check the startup banner or `frida://service/config` from the next successful boot to inspect the structured `quick_path` summary.
- Fix the MCP process environment first, then restart MCP and retry `session_open_quick`.

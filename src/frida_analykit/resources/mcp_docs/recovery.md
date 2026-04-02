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

## Crash and bad snippet behavior

- A snippet may crash the target process after injection.
- Treat every crash as evidence first; do not assume the device or host is the root cause without checking state.
- Use `tail_logs` and the session resources before deciding to reopen or discard the attempt.

## Missing `/rpc`

If session open fails with an RPC runtime mismatch, the loaded `_agent.js` does not expose the required RPC runtime.

- If possible, switch to `session_open_quick`, which always regenerates a minimal bundle with `/rpc` imported first.
- Check `frida://service/config` if the failure might be caused by an unexpected host, device, or output-path setup on the MCP side.
- Otherwise rebuild `_agent.js` with the local `@zsa233/frida-analykit-agent` runtime from this checkout.
- Re-run the bundle build.
- Retry `session_open` after the rebuilt artifact is ready.

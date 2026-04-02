# MCP Quickstart

## Recommended first step

- Start the server with a user-prepared startup TOML, then read `frida://service/config`.
- Use `session_open_quick` as the default MCP entrypoint.
- Do not hand-write `config.toml`, `package.json`, `index.ts`, or `_agent.js` unless you need advanced customization outside the quick path.

## What `session_open_quick` does

1. Validates the target app, mode, template, and official capability list.
2. Generates a minimal TypeScript workspace that always imports `@zsa233/frida-analykit-agent/rpc` first.
3. Optionally writes a copied bootstrap file from `bootstrap_path` or generated source from `bootstrap_source`, then imports it for earliest hook registration.
4. Builds `_agent.js` with `frida-compile`.
5. Writes a matching `config.toml` from the fixed MCP startup config.
6. Reuses the cached workspace on later calls with the same signature.
7. Opens or reuses the Frida session through the normal MCP session manager.

## Important inputs

- `app`: target package name or remembered attach target identifier.
- `mode`: `attach` or `spawn`.
- `capabilities`: official runtime capability names only.
- `template`: one of `minimal`, `process_probe`, `java_bridge`, `dex_probe`, `ssl_probe`, or `elf_probe`.
- `bootstrap_path`: optional local `.ts` or `.js` file to copy into the prepared workspace and import during bundle startup.
- `bootstrap_source`: optional inline module-level initialization code for hooks that must be registered immediately after injection.
- Server and output defaults are inherited from `frida://service/config`, not from per-call parameters.

## Cache behavior

- Quick-session artifacts are stored under the MCP prepared cache directory and keyed by a deterministic signature.
- The signature includes the bootstrap mode, bootstrap file content hash when `bootstrap_path` is used, and the effective startup-config defaults that affect generated files.
- Same signature means the same generated workspace and compiled `_agent.js`.
- Use `prepared_session_inspect` to inspect generated imports, config summary, and the last build outcome.
- Use `prepared_session_prune` to remove old or unused cached workspaces.

## When to use the low-level path

- Use `session_open` only when you already maintain your own workspace and want MCP to consume that explicit `config.toml` or legacy YAML config.
- After a quick session is open, continue normal MCP work with `eval_js`, `install_snippet`, `call_snippet`, and `session_recover`.

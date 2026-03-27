# Frida-Analykit Agent Rules

## Architecture

- Python is the orchestration layer. Device selection, config loading, server boot, logging, file persistence, and REPL integration stay in `src/frida_analykit/`.
- Agent runtime code lives in `packages/frida-analykit-agent/`. Generated user workspaces consume that package; they must not import repo-relative runtime paths.
- Any Frida-version-specific branching belongs in `src/frida_analykit/compat.py`. Do not scatter version checks across CLI, session, or RPC code.
- Config is loaded explicitly from YAML into `AppConfig`. Do not reintroduce global config singletons or import-time side effects.

## Wire Protocol

- The Python RPC models in `src/frida_analykit/rpc/` and the TypeScript message/runtime code in `packages/frida-analykit-agent/src/` are one protocol surface.
- Any wire-protocol change must update Python models, TypeScript emitters, tests, and both READMEs in the same change.
- Default message handling is owned by `HandlerRegistry`. Do not add hidden decorator side effects or module-import registration patterns.

## Runtime / Templates

- The generated dev scaffold must stay installable with `frida-analykit gen dev` and must resolve the runtime through `@zsa233/frida-analykit-agent`.
- CLI-driven compile flow is part of the public contract. `frida-analykit build` / `watch` and `attach` / `spawn --build|--watch` must keep working by reusing the scaffold `npm run build` / `npm run watch` scripts.
- Android-oriented templates may depend on `frida-java-bridge`. ObjC/Swift support remains opt-in and must not become an implicit dependency of every scaffold.
- Environment injection must continue to work for compiled bundles by using `globalThis.__FRIDA_ANALYKIT_CONFIG__`; do not hardcode old repo-relative module paths.

## Release Discipline

- Python and npm package versions must stay identical and match the git tag used for release.
- `uv.lock`, `compat_profiles.json`, GitHub workflows, and tests are part of the release contract. Do not update release ranges or tooling without updating those files together.

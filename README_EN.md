# Frida-Analykit

[![GitHub Stars](https://img.shields.io/github/stars/zsa233/frida-analykit)](https://github.com/zsa233/frida-analykit/stargazers)
[![License](https://img.shields.io/github/license/zsa233/frida-analykit)](LICENSE)

🌍 Language: [中文](README.md) | English

Frida-Analykit v2 is a dual-artifact repository:

- Python CLI for device/session orchestration, `frida-server` bootstrapping, log and binary persistence, REPL, and project scaffolding.
- npm runtime package for custom TypeScript agents: `@zsa233/frida-analykit-agent`.

## Compatibility

- Python dependency range: `frida>=16.5.9,<18`
- Tested profile pins: `16.5.9` and `17.8.2`
- `frida-analykit doctor` classifies the current environment as `tested`, `supported but untested`, or `unsupported`

Check the current environment with:

```sh
frida-analykit doctor
```

## Install The Python CLI

The Python package is distributed through GitHub only, not PyPI.

Recommended installation with `uv`:

```sh
uv tool install "git+https://github.com/ZSA233/frida-analykit@v2.0.0"
```

This path keeps the tag-defined range dependency from `pyproject.toml`, which is currently `frida>=16.5.9,<18`.

If you prefer an exact Frida pin, install into an isolated environment explicitly:

```sh
uv venv .venv-frida-17.8.2
uv pip install --python .venv-frida-17.8.2/bin/python \
  "frida==17.8.2" \
  "git+https://github.com/ZSA233/frida-analykit@v2.0.0"
```

If `frida --version` does not change after you switch environments, you are usually still hitting a global `frida-tools` binary. Managed environments install `frida`, `frida-tools`, and `frida-analykit` together so the shell command follows the selected environment.

For local development, the repository helper keeps this workflow reproducible:

```sh
make dev-env
make dev-env-list
make dev-env-gen FRIDA_VERSION=16.5.9
make dev-env-gen FRIDA_VERSION=16.5.9 NO_REPL=1
make dev-env-gen FRIDA_VERSION=16.5.9 ENV_NAME=frida-16.5.9
make dev-env-enter ENV_NAME=frida-16.5.9
make dev-env-remove ENV_NAME=frida-16.5.9
```

The general CLI exposes the same workflow:

```sh
frida-analykit env create --frida-version 16.5.9 --name frida-16.5.9
frida-analykit env create --frida-version 16.5.9 --no-repl
frida-analykit env list
frida-analykit env use frida-16.5.9
frida-analykit env shell
frida-analykit env remove frida-16.5.9
frida-analykit env install-frida --version 16.5.9
```

`make dev-env` only prints help. `make dev-env-gen` installs the repo-oriented `dev + repl` dependencies by default, requires an explicit `FRIDA_VERSION`, keeps `ENV_NAME` optional, and accepts `NO_REPL=1` to skip the REPL extra. `frida-analykit env create` installs `repl` by default but does not install the repo `dev` group, and accepts `--no-repl` to skip it. `make dev-env-enter` and `frida-analykit env shell` open a child shell; `frida-analykit env use <name>` only switches the current environment pointer and does not modify the current shell. Inside the child shell you can directly run `uv pip install ...`, `python`, `frida`, and `frida-analykit`; if you want `uv run` / `uv sync` to prefer the active environment, use `--active` explicitly. Exit a child shell with `exit`. If you activate manually with `source .../bin/activate`, leave it with `deactivate`.

`env create` and `dev-env-gen` now pass through the native `uv` output during environment preparation, so the built-in `uv venv`, `uv sync`, and `uv pip install` progress remains visible. These managed-environment commands require a working `uv` binary on `PATH`; if `uv` is missing, the CLI now fails with an explicit install hint instead of a raw traceback.

## Flow 1: Use It As A CLI Tool

Create `config.yml`:

```yml
app: com.example.demo
jsfile: ./_agent.js

server:
  servername: /data/local/tmp/frida-server
  host: 127.0.0.1:27042
  device:
  version:

agent:
  datadir: ./data
  stdout: ./logs/stdout.log
  stderr: ./logs/stderr.log

script:
  nettools:
    ssl_log_secret: ./data/nettools/sslkey
```

Typical commands:

```sh
frida-analykit server boot --config config.yml
frida-analykit server boot --config config.yml --force-restart
frida-analykit server stop --config config.yml
frida-analykit doctor --config config.yml
frida-analykit doctor --config config.yml --verbose
frida-analykit server install --config config.yml
frida-analykit server install --config config.yml --verbose
frida-analykit server install --config config.yml --version 17.8.2
frida-analykit server install --config config.yml --local-server ./frida-server-17.8.2-android-arm64.xz
frida-analykit build --config config.yml
frida-analykit spawn --config config.yml
frida-analykit attach --config config.yml --pid 12345
frida-analykit attach --config config.yml --build --repl
frida-analykit attach --config config.yml --watch --repl
```

Notes:

- `spawn` and `attach` keep the session alive by default so logs and binary payloads continue streaming.
- `--repl` opens `ptpython` and exposes `device`, `session`, `script`, and `config`.
- `--verbose` prints the actual adb/npm subprocess commands, exit codes, and captured stdout/stderr so you can diagnose mismatches between expected and observed device state.
- `server.host` also supports `local` and `usb` shortcuts in addition to `host:port`.
- `server.device` pins the target device serial; `doctor`, `spawn`, `attach`, and the `server` subcommands all prefer it so multi-device setups do not drift onto the wrong target.
- `doctor --config` reads `config.yml`, shows the configured `server.device` and resolved adb target, checks the device-side `server.servername`, reports the detected server version, and shows the resolved asset arch for the current device ABI.
- `server boot` does not kill an existing remote `frida-server` by default. If a matching process is already running, the command fails and points you to `server stop` or `server boot --force-restart`.
- `server stop` is the supported cleanup path. It succeeds even when no matching remote process is running, and still attempts to remove the configured adb forward.
- `server install` supports two sources: `--version` downloads from GitHub with progress output, while `--local-server` pushes a local executable or `.xz` archive. Version-based installs prefer `--version`, then `server.version`, then the installed Python `frida` version. Downloaded archives are cached locally and reused.

## Device Tests

The repository also includes a self-contained Android device test suite. It does not depend on any external example project. Each test generates a temporary `_agent.js + config.yml` pair and only validates the core path: `frida-server` lifecycle, a minimal injection marker, and server installation.

Required environment variables:

- `FRIDA_ANALYKIT_ENABLE_DEVICE=1`
- `FRIDA_ANALYKIT_DEVICE_APP=<package>`
- optional `ANDROID_SERIAL=<serial>`
- optional `FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path>` for `server install --local-server`

Targets:

```sh
make device-check
make device-test-core
make device-test-install
make device-test
```

## Flow 2: Generate A Custom TypeScript Agent Workspace

This is the primary v2 development workflow. The Python CLI handles injection and persistence; you own the TypeScript agent workspace.

### 1. Generate The Workspace

```sh
frida-analykit gen dev --work-dir ./my-agent
```

Generated layout:

```text
my-agent/
├── README.md
├── config.yml
├── index.ts
├── package.json
└── tsconfig.json
```

### 2. Install Dependencies

```sh
cd my-agent
npm install
```

The generated `package.json` pins the exact `@zsa233/frida-analykit-agent` version that matches the current CLI release on npmjs, so a normal `npm install` is enough. No `.npmrc` or extra token is required.

### 3. Customize The Agent

The generated `index.ts` wires in the RPC runtime:

```ts
import "@zsa233/frida-analykit-agent/rpc"
```

Then you can extend it:

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help, proc, SSLTools } from "@zsa233/frida-analykit-agent"

console.log("pid =", Process.id)
console.log("api level =", help.androidGetApiLevel())
console.log("maps =", proc.mapCache.length)
SSLTools.guess().forEach((item) => console.log(item))
```

### 4. Let The CLI Drive The Compile Flow

```sh
frida-analykit build --config ./config.yml
frida-analykit attach --config ./config.yml --build --repl
frida-analykit attach --config ./config.yml --watch --repl
```

The CLI reuses the workspace `npm run build` and `npm run watch` scripts. You can still execute those scripts manually for advanced workflows.

If `config.yml` sets `agent.stdout` / `agent.stderr`, the CLI prints the resolved log paths before injection. In ESM mode the top-level `import` chain runs before later `console.log(...)` statements in `index.ts`, so a missing "first log line" usually means a bootstrap or import failure. Check `logs/outerr.log` first before assuming the log path is wrong.

Run it with the Python CLI:

```sh
frida-analykit attach --config ./config.yml --build --repl
```

## Config Shape

The v2 YAML shape stays close to v1:

- `app`: target application identifier; required for `spawn`, optional for `attach`
- `jsfile`: compiled `_agent.js` bundle path
- `server`: target device and `frida-server` connection settings
  `server.version` is an optional pin for the desired `frida-server` build
- `agent`: Python-side output directories for logs and binary payloads
- `script`: agent-side extension config, currently mainly `nettools.ssl_log_secret`

## Distribution And Repository Layout

- Python package: GitHub Releases
  Each GitHub Release includes one source archive `frida_analykit-X.Y.Z.tar.gz` and one real build wheel
- npm runtime: npmjs
- Versioning: Python and npm share the same version number
- Support-range source of truth: the direct `frida>=...,<...` dependency in `pyproject.toml`
- Tested-profile source of truth: `src/frida_analykit/resources/compat_profiles.json`
- Release automation requires exactly one direct `frida>=...,<...` dependency in `pyproject.toml`; extras, markers, or duplicate `frida` entries are rejected
- Historical multi-wheel releases remain as historical artifacts only; new releases no longer use that distribution model
- The first-release, RC, stable, and development validation runbook lives in `docs/release-process.md`

Key directories:

```text
src/frida_analykit/                # Python CLI and orchestration
packages/frida-analykit-agent/     # npm runtime
scripts/                           # release asset planning / build helpers
tests/                             # Python tests
.github/workflows/                 # CI and release automation
```

## Migrating From v1

v2 is a breaking release. Old script entrypoints are no longer the supported interface.

| v1 | v2 |
|:---|:---|
| `python frida-analykit/main.py ...` | `frida-analykit ...` |
| `python frida-analykit/gen.py dev` | `frida-analykit gen dev` |
| `ptpython_spawn.sh` / `ptpython_attach.sh` | `--repl` |
| repo-relative imports such as `./frida-analykit/script/...` | npm package `@zsa233/frida-analykit-agent` |
| `requirements.txt` | `pyproject.toml` + `uv.lock` |

## Example Repository

- [android-reverse-examples](https://github.com/ZSA233/android-reverse-examples)

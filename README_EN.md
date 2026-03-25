# Frida-Analykit

[![GitHub Stars](https://img.shields.io/github/stars/zsa233/frida-analykit)](https://github.com/zsa233/frida-analykit/stargazers)
[![License](https://img.shields.io/github/license/zsa233/frida-analykit)](LICENSE)

🌍 Language: [中文](README.md) | English

Frida-Analykit v2 is a dual-artifact repository:

- Python CLI for device/session orchestration, `frida-server` bootstrapping, log and binary persistence, REPL, and project scaffolding.
- npm runtime package for custom TypeScript agents: `@zsa233/frida-analykit-agent`.

## Compatibility

- Supported tracks: `16.6.x` and `17.x`
- Tested profile pins: `16.6.6` and `17.8.2`

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

You can also install a wheel from a GitHub Release asset if you prefer pinned binaries.

## Flow 1: Use It As A CLI Tool

Create `config.yml`:

```yml
app: com.example.demo
jsfile: ./_agent.js

server:
  servername: /data/local/tmp/frida-server
  host: 127.0.0.1:27042
  device:

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
frida-analykit build --config config.yml
frida-analykit spawn --config config.yml
frida-analykit attach --config config.yml --pid 12345
frida-analykit attach --config config.yml --build --repl
frida-analykit attach --config config.yml --watch --repl
```

Notes:

- `spawn` and `attach` keep the session alive by default so logs and binary payloads continue streaming.
- `--repl` opens `ptpython` and exposes `device`, `session`, `script`, and `config`.
- `server.host` also supports `local` and `usb` shortcuts in addition to `host:port`.

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

The generated `package.json` depends on the matching `@zsa233/frida-analykit-agent` version from npmjs, so a normal `npm install` is enough. No `.npmrc` or extra token is required.

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

Run it with the Python CLI:

```sh
frida-analykit attach --config ./config.yml --build --repl
```

## Config Shape

The v2 YAML shape stays close to v1:

- `app`: target application identifier; required for `spawn`, optional for `attach`
- `jsfile`: compiled `_agent.js` bundle path
- `server`: target device and `frida-server` connection settings
- `agent`: Python-side output directories for logs and binary payloads
- `script`: agent-side extension config, currently mainly `nettools.ssl_log_secret`

## Distribution And Repository Layout

- Python package: GitHub Releases
- npm runtime: npmjs
- Versioning: Python and npm share the same version number

Key directories:

```text
src/frida_analykit/                # Python CLI and orchestration
packages/frida-analykit-agent/     # npm runtime
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

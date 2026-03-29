# Frida-Analykit

[![GitHub Stars](https://img.shields.io/github/stars/zsa233/frida-analykit)](https://github.com/zsa233/frida-analykit/stargazers)
[![License](https://img.shields.io/github/license/zsa233/frida-analykit)](LICENSE)

🌍 语言: 中文 | [English](README_EN.md)

`frida-analykit` v2 是一个双产物仓库：

- Python CLI：负责 `frida-server` 生命周期、设备连接、构建编排、attach/spawn、REPL、日志与二进制数据归档。
- npm runtime：发布为 `@zsa233/frida-analykit-agent`，提供给自定义 TypeScript Frida agent 的 runtime、RPC 和逆向辅助能力。

## 兼容策略

- Python 依赖范围：`frida>=16.5.9,<18`
- 当前受测 profile：`16.5.9` 与 `17.8.2`
- `frida-analykit doctor` 会把当前环境标记为 `tested`、`supported but untested` 或 `unsupported`

先检查当前环境：

```sh
frida-analykit doctor
```

## 安装 Python CLI

Python 包只通过 GitHub 仓库 / GitHub Release 分发，不发布到 PyPI。

推荐直接用 `uv` 安装：

```sh
uv tool install "git+https://github.com/ZSA233/frida-analykit@v2.0.3"
```

如果你希望锁定到某个精确 Frida 版本，推荐在独立环境里显式安装：

```sh
uv venv .venv-frida-17.8.2
uv pip install --python .venv-frida-17.8.2/bin/python \
  "frida==17.8.2" \
  "git+https://github.com/ZSA233/frida-analykit@v2.0.3"
```

也可以用内置环境管理来维护多套 Frida 版本环境：

```sh
frida-analykit env create --frida-version 16.5.9 --name legacy-16
frida-analykit env create --frida-version 17.8.2 --name current-17
frida-analykit env list
frida-analykit env use legacy-16
frida-analykit env shell
frida-analykit env remove legacy-16
```

仓库开发时也可以用 repo-local helper：

```sh
make dev-env-gen FRIDA_VERSION=16.5.9 ENV_NAME=legacy-16
make dev-env-gen FRIDA_VERSION=17.8.2 ENV_NAME=current-17
make dev-env-enter ENV_NAME=legacy-16
```

## 主线工作流

推荐开发链路：

1. 创建并进入与目标 Frida 版本匹配的 Python 环境。
2. 生成独立的 TypeScript agent 工作区：

```sh
frida-analykit gen dev --work-dir ./my-agent
```

3. 进入工作区并安装前端依赖：

```sh
cd my-agent
npm install
```

4. 按目标应用和输出路径调整 `config.yml`。
5. 先跑一次环境与设备检查：

```sh
frida-analykit doctor --config ./config.yml
```

6. 如有需要，安装并启动设备端 `frida-server`：

```sh
frida-analykit server install --config ./config.yml
frida-analykit server boot --config ./config.yml
```

7. 编译并注入：

```sh
frida-analykit build --config ./config.yml
frida-analykit attach --config ./config.yml --build --repl
```

常用命令：

```sh
frida-analykit build --config ./config.yml
frida-analykit watch --config ./config.yml
frida-analykit spawn --config ./config.yml
frida-analykit attach --config ./config.yml --pid 12345
frida-analykit attach --config ./config.yml --watch --repl
frida-analykit doctor --config ./config.yml --verbose
frida-analykit server stop --config ./config.yml
frida-analykit server install --config ./config.yml --version 17.8.2
frida-analykit server install --config ./config.yml --local-server ./frida-server-17.8.2-android-arm64.xz
```

当前行为要点：

- `spawn` 要求 `config.app` 必填；`attach` 可显式传 `--pid`
- `--build` / `--watch` 会复用工作区里的 `npm run build` / `npm run watch`
- `attach --watch` / `spawn --watch` 是“等待首个成功构建后再注入”，不会自动热重载已加载 session
- `server.host` 支持 `host:port`、`local`、`usb`
- `server.device` 用于固定目标设备序列号，避免多设备场景串到错误目标
- `server boot` 默认不会杀掉已有远端 `frida-server`；如需强制替换，使用 `--force-restart`
- `server stop` 是幂等清理入口，即使远端当前没有匹配进程也会返回成功

## REPL 与远端对象访问

`--repl` 会进入 async `ptpython`，并注入：

- `config`
- `device`
- `pid`
- `session`
- `script`

此外，REPL 还会按 `script.repl.globals` 懒注入一组 JS seed handle。当前模板默认值为：

- `Process`
- `Module`
- `Memory`
- `Java`
- `ObjC`
- `Swift`

这些名字不会在进入 REPL 时立刻触发 RPC enumerate，而是在首次真实使用时才 materialize 成 `script.jsh(name)` 对应句柄。

当前 REPL 句柄支持：

- `script.jsh("Process")`
- `script.eval("Process.arch")`
- `await script.eval_async("Promise.resolve(Process.arch)")`
- `handle.value_`
- `handle.type_`
- `await handle.call_async(...)`
- `await handle.resolve_async()`

当前需要特别记住的约束：

- 句柄元信息使用 `.value_` / `.type_`，不再占用真实 JS 属性 `.value` / `.type`
- `JsHandle.value_` 除了 primitive/plain-object 结果外，也会尽量把 Frida 常见 getter-backed 对象投影成有界的 JSON-safe snapshot，例如 `Process.mainModule.value_`
- 如果某个句柄值仍无法被投影到 RPC bridge，应继续使用链式句柄访问，或显式 `await handle.resolve_async()`
- 如果设备上加载的是旧 `_agent.js`，Python 侧会直接抛出 `RPC runtime mismatch`，要求用户用当前仓库重新打包 runtime 并 rebuild

## TypeScript Agent 工作区

这是 v2 的主线开发模式。`frida-analykit gen dev` 会生成：

```text
my-agent/
├── README.md
├── config.yml
├── index.ts
├── package.json
└── tsconfig.json
```

生成后的 `index.ts` 默认只安装最小 RPC / REPL runtime：

```ts
import "@zsa233/frida-analykit-agent/rpc"
```

如果要引入更多 runtime 能力，推荐显式使用 capability subpath：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help } from "@zsa233/frida-analykit-agent/helper"
import "@zsa233/frida-analykit-agent/process"
import { JNIEnv } from "@zsa233/frida-analykit-agent/jni"
import { SSLTools } from "@zsa233/frida-analykit-agent/ssl"

setImmediate(() => {
  console.log("pid =", Process.id)
  console.log("api level =", help.androidGetApiLevel())
  console.log("env =", JNIEnv.$handle)
  console.log("ssl guesses =", SSLTools.guess().length)
  console.log("maps =", proc.loadProcMap().items.length)
})
```

当前导入边界：

- `@zsa233/frida-analykit-agent/rpc` 只安装最小 RPC / REPL 基础
- 它不会再自动 import `help`、`proc`、`JNIEnv`、`SSLTools`、`ElfTools`、`Libssl`
- 只有在你自己的 `index.ts` 中显式 import 对应 capability 后，这些能力才会进入 bundle，并出现在 RPC eval context

这意味着 `_agent.js` 的体积主要由你的显式导入面决定，而不是被 `/rpc` 默认拖重。

## 配置说明

`config.yml` 顶层结构：

- `app`：目标包名；`spawn` 时必须提供，`attach` 时可作为 PID 自动解析依据
- `jsfile`：编译产物 `_agent.js` 路径
- `server`：设备与 `frida-server` 连接信息
- `agent`：Python 侧日志与二进制数据输出路径
- `script`：agent 侧扩展配置；当前主要是 `nettools.ssl_log_secret` 和 `repl.globals`

示例：

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
  repl:
    globals:
      - Process
      - Module
      - Memory
      - Java
      - ObjC
      - Swift
  nettools:
    ssl_log_secret: ./data/nettools/sslkey
```

## 真机测试

仓库内置了一组 Android 真机测试，不依赖外部示例工程。它们会在临时目录里生成最小 `_agent.js + config.yml`，验证：

- `frida-server` 生命周期
- 最小注入与 attach/spawn 链路
- REPL / `JsHandle` 核心路径
- 本地 runtime tarball 与私有 agent 单测包的真机回归

运行前需要：

- `FRIDA_ANALYKIT_ENABLE_DEVICE=1`
- `FRIDA_ANALYKIT_DEVICE_APP=<package>`
- 可选 `ANDROID_SERIAL=<serial>`
- 可选 `FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path>`

命令：

```sh
make device-check
make device-test-core
make device-test-install
make device-test-repl-handlers
make device-test
```

## 发布与仓库结构

- Python 包通过 GitHub Release 分发
- npm runtime 通过 npmjs 分发
- Python 与 npm 共用同一个版本号
- 版本真源在 `release-version.toml`
- 支持范围真源在 `pyproject.toml` 中的 `frida>=...,<...`
- 受测 profile 真源在 `src/frida_analykit/resources/compat_profiles.json`
- release runbook 在 `docs/release-process.md`

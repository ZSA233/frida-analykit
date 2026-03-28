# Frida-Analykit

[![GitHub Stars](https://img.shields.io/github/stars/zsa233/frida-analykit)](https://github.com/zsa233/frida-analykit/stargazers)
[![License](https://img.shields.io/github/license/zsa233/frida-analykit)](LICENSE)

🌍 语言: 中文 | [English](README_EN.md)

Frida-Analykit v2 是一个双产物仓库：

- Python CLI：负责 `frida-server` 启动、设备连接、日志与二进制数据落盘、REPL、脚手架生成。
- npm runtime：提供给用户自定义 TypeScript agent 使用的公共 runtime，包名为 `@zsa233/frida-analykit-agent`。

## 当前兼容策略

- Python 依赖范围：`frida>=16.5.9,<18`
- 当前检查版本：`16.5.9` 与 `17.8.2`
- `frida-analykit doctor` 会把当前环境标记为 `tested`、`supported but untested` 或 `unsupported`
- 使用前可运行：

```sh
frida-analykit doctor
```

## 安装 Python CLI

Python 包只通过 GitHub 仓库 / GitHub Release 分发，不发布到 PyPI。

推荐直接用 `uv` 安装命令行：

```sh
uv tool install "git+https://github.com/ZSA233/frida-analykit@v2.0.0"
```

这个安装方式沿用 tag 对应源码里的范围依赖语义，也就是 `pyproject.toml` 里的 `frida>=16.5.9,<18`。

如果你更希望锁定到某个精确 Frida 版本，推荐在独立环境里显式安装：

```sh
uv venv .venv-frida-17.8.2
uv pip install --python .venv-frida-17.8.2/bin/python \
  "frida==17.8.2" \
  "git+https://github.com/ZSA233/frida-analykit@v2.0.0"
```

如果当前环境里的 `frida --version` 没跟着虚拟环境切换，通常说明你命中的还是全局 `frida-tools`。受管理环境会同时安装 `frida`、`frida-tools` 和 `frida-analykit`，避免这个问题。

开发阶段可以直接用仓库里的 helper：

```sh
make dev-env
make dev-env-list
make dev-env-gen FRIDA_VERSION=16.5.9
make dev-env-gen FRIDA_VERSION=16.5.9 NO_REPL=1
make dev-env-gen FRIDA_VERSION=16.5.9 ENV_NAME=frida-16.5.9
make dev-env-enter ENV_NAME=frida-16.5.9
make dev-env-remove ENV_NAME=frida-16.5.9
```

通用 CLI 也提供同一套环境管理：

```sh
frida-analykit env create --frida-version 16.5.9 --name frida-16.5.9
frida-analykit env create --frida-version 16.5.9 --no-repl
frida-analykit env list
frida-analykit env use frida-16.5.9
frida-analykit env shell
frida-analykit env remove frida-16.5.9
frida-analykit env install-frida --version 16.5.9
```

`make dev-env` 默认只显示帮助。`make dev-env-gen` 默认安装仓库开发所需的 `dev + repl` 依赖，必须显式传入 `FRIDA_VERSION`，`ENV_NAME` 可选，`NO_REPL=1` 可关闭 REPL 依赖；`frida-analykit env create` 默认安装 `repl`，但不会安装仓库的 `dev` 依赖组，可通过 `--no-repl` 关闭。`make dev-env-enter` 和 `frida-analykit env shell` 会打开一个子 shell；`frida-analykit env use <name>` 只切换 current 环境，不会修改当前 shell。进入子 shell 后可以直接执行 `uv pip install ...`、`python`、`frida`、`frida-analykit`；如果要让 `uv run` / `uv sync` 优先作用于当前激活环境，仍建议显式加 `--active`。退出子 shell 用 `exit`；如果你手动 `source .../bin/activate`，则退出时用 `deactivate`。

`env create` / `dev-env-gen` 在安装依赖时会直接透传 `uv` 自己的原始输出，所以你会看到 `uv venv`、`uv sync`、`uv pip install` 的原生进度。这里的受管理环境能力依赖本机存在 `uv` 命令；如果未安装或不在 `PATH` 里，CLI 会给出明确报错并提示先安装 `uv`。

## 用法 1：直接把它当成 CLI 工具

准备一个 `config.yml`：

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

常用命令：

```sh
# 远端 frida-server 启动
frida-analykit server boot --config config.yml
frida-analykit server boot --config config.yml --force-restart
frida-analykit server stop --config config.yml

# 查看当前 Python Frida 与设备端 frida-server 状态
frida-analykit doctor --config config.yml
frida-analykit doctor --config config.yml --verbose

# 下载匹配版本并推送到 config.server.servername
frida-analykit server install --config config.yml
frida-analykit server install --config config.yml --verbose

# 如需手动指定 server 版本
frida-analykit server install --config config.yml --version 17.8.2

# 使用本地 frida-server 或 .xz 资产推送
frida-analykit server install --config config.yml --local-server ./frida-server-17.8.2-android-arm64.xz

# 先编译 index.ts -> _agent.js
frida-analykit build --config config.yml

# spawn 模式
frida-analykit spawn --config config.yml

# attach 模式
frida-analykit attach --config config.yml --pid 12345

# 带 REPL
frida-analykit attach --config config.yml --build --repl

# 持续监听 index.ts 变动，但不会自动热重载已加载 session
frida-analykit attach --config config.yml --watch --repl
```

说明：

- `spawn` / `attach` 默认保持会话存活，适合持续收集日志和 data payload。
- `--repl` 会打开 `ptpython`，可以直接拿到 `device`、`session`、`script` 等对象。
- `--verbose` 会打印实际执行的 adb/npm 子进程命令、退出码和捕获到的 stdout/stderr，适合排查设备端命令判断为什么与预期不一致。
- `server.host` 除了 `host:port`，也支持 `local` 和 `usb` 这类本地/USB 设备简写。
- `server.device` 用来固定目标设备序列号；`doctor`、`spawn`、`attach` 以及 `server` 子命令都会优先使用它，避免多设备场景串到错误目标。
- `doctor --config` 会读取 `config.yml`，显示 `server.device` / 实际 adb 目标设备，检查 `server.servername` 对应的设备端文件、版本、以及当前 ABI 推导出的下载资产类型。
- `server boot` 默认不会自动杀掉已经存在的远端 `frida-server`；检测到同名进程时会直接报错，并提示你执行 `server stop` 或改用 `server boot --force-restart`。
- `server stop` 是正式清理入口；即使设备上当前没有匹配进程，也会返回成功并尝试清理对应的 adb forward。
- `server install` 支持两种来源：`--version` 从 GitHub 下载并显示进度，`--local-server` 直接推送本地可执行文件或 `.xz` 资产。版本模式下会优先使用 `--version`，否则使用 `server.version`，再否则退回当前已安装的 Python `frida` 版本；下载文件会缓存到本机缓存目录，后续重复安装会复用。

## 真机测试

仓库内置了一组自包含的 Android 真机测试，不依赖外部示例工程。测试会在临时目录里生成最小 `_agent.js + config.yml`，只验证最核心的链路：`frida-server` 生命周期、最小日志注入、以及安装命令。

运行前需要：

- `FRIDA_ANALYKIT_ENABLE_DEVICE=1`
- `FRIDA_ANALYKIT_DEVICE_APP=<package>`
- 可选 `ANDROID_SERIAL=<serial>`
- 可选 `FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path>`，用于 `server install --local-server` 测试

命令：

```sh
make device-check
make device-test-core
make device-test-install
make device-test
```

## 用法 2：生成自定义 TypeScript agent 工作区

这是 v2 的主线开发模式。Python CLI 负责注入与日志归档，用户在独立工作区里只维护自己的 TS agent。

### 1. 生成工作区

```sh
frida-analykit gen dev --work-dir ./my-agent
```

生成后目录类似：

```text
my-agent/
├── README.md
├── config.yml
├── index.ts
├── package.json
└── tsconfig.json
```

### 2. 安装依赖

```sh
cd my-agent
npm install
```

默认生成的 `package.json` 会直接精确依赖 npmjs 上与当前 CLI 匹配的 `@zsa233/frida-analykit-agent` 版本，只需要普通的 `npm install`，不需要 `.npmrc` 或额外 token。

### 3. 自定义你的 agent

默认 `index.ts` 会把 runtime 的 RPC 层装进去：

```ts
import "@zsa233/frida-analykit-agent/rpc"
```

你可以继续扩展：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help, proc, SSLTools } from "@zsa233/frida-analykit-agent"

console.log("pid =", Process.id)
console.log("api level =", help.androidGetApiLevel())
console.log("maps =", proc.mapCache.length)
SSLTools.guess().forEach((item) => console.log(item))
```

### 4. 让 CLI 触发编译并运行

```sh
# 一次性编译
frida-analykit build --config ./config.yml

# 编译后注入
frida-analykit attach --config ./config.yml --build --repl

# 持续监听 index.ts 并在首个成功构建后注入
frida-analykit attach --config ./config.yml --watch --repl
```

CLI 会复用工作区中的 `npm run build` / `npm run watch`。如果你更习惯手动调试，也仍然可以直接执行这两个 npm scripts。

如果 `config.yml` 里配置了 `agent.stdout` / `agent.stderr`，CLI 在注入前会打印解析后的日志文件路径。ESM 场景下，`index.ts` 里的顶层 `import` 会先于后面的 `console.log(...)` 执行，所以如果你预期中的“第一行日志”没有出现，优先检查 `logs/outerr.log` 里的 bootstrap / import 错误，而不是先怀疑路径没生效。

然后用同一个 Python CLI 去运行：

```sh
frida-analykit attach --config ./config.yml --build --repl
```

## 配置说明

`config.yml` 顶层结构保持为：

- `app`: 目标包名，`spawn` 时必须提供；`attach` 时可作为 PID 自动解析依据
- `jsfile`: 编译产物 `_agent.js` 路径
- `server`: 设备与 `frida-server` 连接信息
  其中 `server.version` 是可选钉死版本；不填时默认跟随当前 Python `frida` 版本
- `agent`: Python 侧日志/二进制数据输出目录
- `script`: agent 侧扩展配置，目前主要是 `nettools.ssl_log_secret`

## 发布与仓库结构

- Python 包：GitHub Release
  每个 GitHub Release 只包含一份源码包 `frida_analykit-X.Y.Z.tar.gz` 和一份真实构建出的 wheel
- npm runtime：npmjs
- 版本：Python 与 npm 共用同一个版本号
- 支持范围真源：`pyproject.toml` 中的 `frida>=...,<...`
- 受测 profile 真源：`src/frida_analykit/resources/compat_profiles.json`
- Release 契约要求 `pyproject.toml` 中只有一条规范直接依赖 `frida>=...,<...`，不支持 extras、marker 或多条 `frida` 依赖
- 历史上的多 wheel release 资产保持原样，但后续版本不再继续维护这种分发模型
- 首次接入、RC、stable 与开发测试流程见 `docs/release-process.md`

仓库中的关键目录：

```text
src/frida_analykit/                # Python CLI 与运行时编排
packages/frida-analykit-agent/     # npm runtime
scripts/                           # release 资产规划 / 构建脚本
tests/                             # Python tests
.github/workflows/                 # CI / release
```

## 从 v1 迁移到 v2

v2 是破坏性升级，旧入口不再是官方接口。

| v1 | v2 |
|:---|:---|
| `python frida-analykit/main.py ...` | `frida-analykit ...` |
| `python frida-analykit/gen.py dev` | `frida-analykit gen dev` |
| `ptpython_spawn.sh` / `ptpython_attach.sh` | `--repl` |
| repo 相对导入 `./frida-analykit/script/...` | npm 包 `@zsa233/frida-analykit-agent` |
| `requirements.txt` | `pyproject.toml` + `uv.lock` |

## 例子

- [android-reverse-examples](https://github.com/ZSA233/android-reverse-examples)

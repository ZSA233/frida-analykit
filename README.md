# Frida-Analykit

[![GitHub Stars](https://img.shields.io/github/stars/zsa233/frida-analykit)](https://github.com/zsa233/frida-analykit/stargazers)
[![License](https://img.shields.io/github/license/zsa233/frida-analykit)](LICENSE)

🌍 语言: 中文 | [English](README_EN.md)

Frida-Analykit v2 是一个双产物仓库：

- Python CLI：负责 `frida-server` 启动、设备连接、日志与二进制数据落盘、REPL、脚手架生成。
- npm runtime：提供给用户自定义 TypeScript agent 使用的公共 runtime，包名为 `@zsa233/frida-analykit-agent`。

## 当前兼容策略

- 兼容轨道：`16.6.x` 与 `17.x`
- 当前检查版本：`16.6.6` 与 `17.8.2`
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

如果你更希望锁定到某个 release wheel，也可以直接安装 release 附件。

## 用法 1：直接把它当成 CLI 工具

准备一个 `config.yml`：

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

常用命令：

```sh
# 远端 frida-server 启动
frida-analykit server boot --config config.yml

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
- `server.host` 除了 `host:port`，也支持 `local` 和 `usb` 这类本地/USB 设备简写。

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

默认生成的 `package.json` 会直接依赖 npmjs 上对应版本的 `@zsa233/frida-analykit-agent`，只需要普通的 `npm install`，不需要 `.npmrc` 或额外 token。

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

然后用同一个 Python CLI 去运行：

```sh
frida-analykit attach --config ./config.yml --build --repl
```

## 配置说明

`config.yml` 顶层结构保持为：

- `app`: 目标包名，`spawn` 时必须提供；`attach` 时可作为 PID 自动解析依据
- `jsfile`: 编译产物 `_agent.js` 路径
- `server`: 设备与 `frida-server` 连接信息
- `agent`: Python 侧日志/二进制数据输出目录
- `script`: agent 侧扩展配置，目前主要是 `nettools.ssl_log_secret`

## 发布与仓库结构

- Python 包：GitHub Release
- npm runtime：npmjs
- 版本：Python 与 npm 共用同一个版本号

仓库中的关键目录：

```text
src/frida_analykit/                # Python CLI 与运行时编排
packages/frida-analykit-agent/     # npm runtime
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

# Frida-Analykit MCP

本文面向实际使用 `frida-analykit-mcp` 的用户，说明如何把已经准备好的 Frida 调试链路交给 MCP client 或大模型工具流使用。

`frida-analykit-mcp` 不是 `frida-analykit` CLI 的替代品。CLI 仍负责环境、构建、server 和注入主流程；MCP server 负责在一个长期会话中暴露调试、日志、脚本和恢复能力。

## 适用场景

- 你已经安装并配置好 `frida-analykit`。
- 目标设备已经连接，远端 `frida-server` 已按当前环境准备好。
- 你希望 MCP client 或大模型反复执行动态验证，而不是每次从零生成工作区。
- 你希望把静态分析结论快速落到真实设备上验证，例如结合 JADX、IDA 或 Ghidra 的 MCP 服务。

不适合的场景：

- 让 MCP 在运行中切换 Frida 版本。
- 让 MCP 自动挑选或安装任意 `frida-server` 版本。
- 把 quick session 当作通用 npm 包管理器或热重载工作区。

## 使用前提

启动 MCP 前先确认：

- 当前 Python 环境中的 Frida 版本已经准备好。
- 目标设备可连接，必要时已固定设备 serial。
- 远端 `frida-server` 已安装或能通过既有配置访问。
- MCP 进程的 `PATH` 能找到 `npm` 和 `frida-compile`，这样 quick session 才可用。

默认情况下，quick toolchain 预热失败不会阻止 stdio server 启动。失败状态会出现在启动 banner 和 `frida://service/config.quick_path`；此时 `session_open_quick(...)` 不可用，但你仍可用 `session_open(config_path, ...)` 连接已经准备好的工作区。

严格部署场景可以加 `--require-quick-ready`，要求 quick path 不可用时直接非零退出。

## 启动配置

最小启动命令：

```sh
frida-analykit-mcp --config ./mcp.toml
```

`mcp.toml` 是服务级配置，不等同于普通 agent 工作区里的 `config.toml`。它用于固定 MCP 进程生命周期内不会频繁变化的默认值。

```toml
[mcp]
idle_timeout_seconds = 1200
session_root = "./sessions"

[server]
host = "127.0.0.1:27042"
device = "emulator-5554"
path = "/data/local/tmp/frida-server"

[agent]
datadir = "./data"
stdout = "./logs/stdout.log"
stderr = "./logs/stderr.log"

[script.dextools]
output_dir = "./data/dextools"

[script.elftools]
output_dir = "./data/elftools"

[script.nettools]
output_dir = "./data/nettools"
```

常用约束：

- `server.path` 是当前主字段；旧的 `server.servername` 只作为兼容读取。
- `--idle-timeout` 可以覆盖配置中的空闲回收时间。
- 不传 `--config` 时会使用内建默认值。
- `frida://service/config` 会暴露 resolved config、`session_root` 和 quick path readiness。

## 接入 MCP Client

当前只支持 `stdio` transport。MCP client 通常注册一个本地命令：

```json
{
  "command": "frida-analykit-mcp",
  "args": ["--config", "/absolute/path/to/mcp.toml"]
}
```

不同 client 的配置格式不同，但本质都是启动这条本地命令并通过 stdio 通信。

## 推荐工作流

推荐顺序：

1. 读取 `frida://service/config`，确认固定配置和 quick path 状态。
2. 读取 `frida://docs/mcp/index`、`frida://docs/mcp/config`、`frida://docs/mcp/quickstart`。
3. 默认优先调用 `session_open_quick(...)`。
4. 会话打开后，用 `eval_js(...)` 做一次性验证。
5. 需要复用状态时，用 `install_snippet(...)` 安装命名 snippet，再通过 `call_snippet(...)` 调用。
6. 结束时显式调用 `session_close(...)`。

如果 app 崩溃、detach 或脚本失效：

1. 先看 `session_status(...)`。
2. 再看 `tail_logs(...)` 或 `frida://session/logs`。
3. 必要时调用 `session_recover(...)`。
4. recover 后重新安装需要的 snippet；snippet 不会自动重放。

## Quick Session

`session_open_quick(...)` 面向“快速打开一个可验证会话”，它会自动：

- 生成最小 TypeScript 工作区。
- 导入 `@zsa233/frida-analykit-agent/rpc` 和指定官方 capability。
- 用 MCP 进程 `PATH` 里的 `frida-compile` 编译 `_agent.js`。
- 写出继承 `mcp.toml` 默认值的 `config.toml`。
- 复用相同参数签名下的 prepared cache。
- 把 prepared artifact 复制到当前 `session_root/{yyyyMMdd-HHMMSS-shortid}/workspace` 后再打开会话。

常用输入：

- `app`：目标包名，或 attach 时用于识别目标。
- `mode`：只能是 `attach` 或 `spawn`。
- `template`：官方 quick preset。
- `capabilities`：在 template 之上额外预加载的官方能力。
- `pid`：attach 到明确进程时使用。
- `bootstrap_path` / `bootstrap_source`：注入前初始化逻辑。
- `force_replace`：当前已有不匹配 live session 时强制替换。

`session_open(config_path, ...)` 是低层入口，适合你已经维护好完整工作区并希望 MCP 直接消费现成配置的场景。

## Bootstrap 与 Snippet

`bootstrap_path` 和 `bootstrap_source` 用于“脚本刚注入时就要执行”的初始化逻辑：

- `bootstrap_path` 适合复用仓库里真实存在、可版本管理的 `.ts` 或 `.js` 文件。
- `bootstrap_source` 适合很短的一次性内联初始化。

`install_snippet(...)` 用于会话打开后的受管逻辑：

- 安装一个命名 controller。
- 在多次实验之间保留对象状态。
- 通过 `call_snippet(...)` 重复调用。
- 结束时用 `remove_snippet(...)` 显式清理。

snippet 源码会归档到当前会话目录的 `snippets/`，但不会在新会话里自动 replay。

## 能力与全局对象

MCP 使用时要区分三层对象：

- Frida 自带全局对象，例如 `Process`、`Module`，Android 上通常还有 `Java`。
- quick template / capability 明确承诺暴露的 analykit 对象。
- runtime 内部依赖顺带暴露的传递性对象。

只应把第二层当作稳定契约。需要能力映射时，优先读取 `frida://docs/mcp/tools`。

常见起手式：

```js
help.proc.readCmdline()
proc.loadProcMap().items.length
JNIEnv.$handle
DexTools.enumerateClassLoaderDexFiles().length
ElfTools.findModuleByName("libc.so")?.name
```

如果要使用不会注册全局对象的增强模块，例如 `@zsa233/frida-analykit-agent/elf/enhanced`，应放到 `bootstrap_path`、`bootstrap_source` 或自定义 workspace 中自己导入，而不是当作 quick capability。

## 日志与会话目录

每个真实 MCP 会话都会在 `session_root` 下分配独立目录，目录名形如 `{yyyyMMdd-HHMMSS-shortid}`。

主要内容：

- `workspace/`：当前会话实际使用的工作区。
- `session.json`：会话摘要。
- `events.jsonl`：会话事件记录。
- `snippets/`：安装过的 snippet 源码归档。

`tail_logs(...)` 和 `frida://session/logs` 会同时包含：

- `source="script"`：agent 脚本日志。
- `source="host"`：MCP host handler 日志，例如 dex/elf 落盘、progress 和异常摘要。

像 dex dump 这种需要确认 host 侧写盘完成的流程，应等待 `source="host"` 的完成事件，而不是只看 agent 侧返回值。

## 限制

- 当前只支持 `stdio`。
- 一个 MCP 进程只维护一个活动调试会话。
- quick session 只允许官方 capability subpath 和模板名。
- quick session 依赖外部 `npm` 与 `frida-compile`。
- quick session 不接管 watch 或 hot reload。
- broken session 不会自动 recover。
- recover 后不会自动重装 snippet。
- prepared workspace 缓存会保留在磁盘上，直到主动 prune。

## 相关文档

- 入门：[../../README.md](../../README.md)
- 工作区配置：[../../src/frida_analykit/resources/scaffold/README.md](../../src/frida_analykit/resources/scaffold/README.md)
- Agent runtime：[../../packages/frida-analykit-agent/README.md](../../packages/frida-analykit-agent/README.md)
- MCP 内置资源：[../../src/frida_analykit/resources/mcp_docs](../../src/frida_analykit/resources/mcp_docs)


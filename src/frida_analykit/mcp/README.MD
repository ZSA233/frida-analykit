# Frida-Analykit MCP

这份文档面向实际使用 `frida-analykit-mcp` 的用户，而不是面向 AI agent 的内置 docs resource。

如果你想把已经准备好的 Frida 真机调试链路交给 MCP client 或大模型使用，这里是主线说明。

## 这是什么

`frida-analykit-mcp` 是一个基于 `stdio` 的 MCP server，用来把 `frida-analykit` 当前的注入、调试、日志和脚本管理能力暴露给 MCP client。

它的目标不是替代 `frida-analykit` CLI，而是把下面这类流程交给 MCP client：

- 打开一个长期复用的真机会话
- 在同一会话里反复做动态验证
- 临时执行一段 JS
- 安装可复用的命名 snippet 并重复调用
- 在 app 崩溃或 detach 之后查看状态并显式恢复

当前设计重点是长会话和可恢复性，而不是“每次都从头准备环境再注入一次”。

## 适合什么场景

比较典型的使用方式是：

- 你已经安装了 `frida-analykit`
- 你已经接上了目标设备
- 你希望让 MCP client 或大模型辅助你做 Frida 动态验证
- 你不想让模型自己手写一整套 `config.toml`、`index.ts` 和 `_agent.js`

如果你还同时接了 JADX、IDA、Ghidra 一类的 MCP 服务，这个 MCP 就适合拿来做“静态分析结论 -> 真机动态验证”的闭环。

## 使用前提

在启动 `frida-analykit-mcp` 之前，先确认这些前提已经满足：

- 目标设备已经连接，且你知道自己要用哪台设备
- 当前 Python 环境中的 Frida 版本已经准备好
- 远端 `frida-server` 已经按你的环境预先准备好
- 如果需要，远端 `frida-server` 已经被你手动安装、启动或放到固定路径

MCP 不负责在运行时替你切换 Frida 版本，也不负责自动安装或选择 `frida-server` 版本。

## 启动配置

`frida-analykit-mcp` 支持一个独立的启动配置文件：

```sh
frida-analykit-mcp --config ./mcp.toml
```

这个 `mcp.toml` 是服务级配置，和普通工作区里的 `config.toml` 不是一回事。

它的作用是把这些“启动后整段会话都固定不变”的参数在 MCP 进程启动时一次性确定下来：

- 默认连接的 `host`
- 默认设备序列号
- 远端 `frida-server` 路径
- 日志和输出目录
- quick session 的缓存目录
- 空闲回收时间

最小示例：

```toml
[mcp]
idle_timeout_seconds = 1200

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
ssl_log_secret = "./data/nettools/sslkey"
```

补充说明：

- `server.path` 是当前主字段
- 旧的 `server.servername` 仍兼容读取，但新配置应优先写 `path`
- `--idle-timeout` 可以覆盖 `mcp.toml` 里的空闲回收时间
- 如果不传 `--config`，MCP 会使用内建默认值启动

## 如何接入 MCP Client

这个服务当前只支持 `stdio` transport，所以在 MCP client 里通常是把它注册成一个本地命令。

通用写法类似这样：

```json
{
  "command": "frida-analykit-mcp",
  "args": ["--config", "/absolute/path/to/mcp.toml"]
}
```

不同 MCP client 的配置文件格式不一样，但本质上都是让它启动这条本地命令并通过 `stdio` 通信。

## 推荐工作流

推荐让 MCP client 或模型按下面顺序使用：

1. 先读取 `frida://service/config`
2. 再读取 `frida://docs/mcp/index`
3. 再读取 `frida://docs/mcp/config`
4. 再读取 `frida://docs/mcp/quickstart`
5. 然后优先调用 `session_open_quick(...)`
6. 会话打开后，先用 `eval_js(...)` 做一次性验证
7. 需要反复调用时，再用 `install_snippet(...)`
8. 结束时主动调用 `session_close(...)`

如果出现 app 崩溃、detach 或脚本失效：

1. 先看 `session_status(...)`
2. 再看 `tail_logs(...)`
3. 必要时显式调用 `session_recover(...)`
4. recover 之后需要的 snippet 重新安装，不会自动重放

## `session_open_quick` 和 `session_open` 的区别

默认推荐 `session_open_quick(...)`。

它适合大多数 MCP 场景，因为它会自动完成这些事情：

- 生成最小 TypeScript 工作区
- 自动导入 `@zsa233/frida-analykit-agent/rpc`
- 按 capability 导入官方 subpath
- 编译 `_agent.js`
- 生成一份继承 `mcp.toml` 默认值的 `config.toml`
- 复用同参数签名下的缓存结果

只有在你已经自己维护好了工作区，并且明确想让 MCP 直接消费现成 `config.toml` 或 legacy YAML 时，才建议使用低层的 `session_open(...)`。

## Quick Session 能做什么

`session_open_quick(...)` 面向的是“告诉 MCP 你要验证什么”，而不是“让模型从零搭工作区”。

它的主字段通常只有这些：

- `app`
- `mode`
- `capabilities`
- `template`
- `pid`
- `bootstrap_path`
- `bootstrap_source`
- `force_replace`

其中最常用的是：

- `app`：目标包名，或 attach 时用于识别目标
- `mode`：`attach` 或 `spawn`
- `capabilities`：你需要哪些官方能力，比如 `rpc`、`ssl`、`dex`、`elf`
- `template`：使用哪种官方最小模板

## `bootstrap_path` 和 `bootstrap_source`

这两个字段都是给“刚注入就要执行的初始化逻辑”准备的。

推荐分工：

- `bootstrap_path`：适合复用你仓库里真实存在的 `.ts` 或 `.js` 文件
- `bootstrap_source`：适合一次性的内联初始化代码

如果你的早期 hook 需要被用户看见、跟踪、修改、走版本管理，优先用 `bootstrap_path`。

如果只是很短的一次性初始化逻辑，才考虑 `bootstrap_source`。

这两者都属于 quick session 的注入前准备逻辑，不会进入 snippet registry。

## `install_snippet` 适合什么

`install_snippet(...)` 不等价于 bootstrap。

它更适合“会话已经打开之后”的受管验证逻辑，例如：

- 安装一个命名 controller
- 反复调用同一个对象的方法
- 在多次试验之间保留这个对象
- 在结束时用 `remove_snippet(...)` 显式清理

所以这两类能力的分工应该是：

- 最早期注入初始化：`bootstrap_path` / `bootstrap_source`
- 会话内反复复用的调试逻辑：`install_snippet`

## 主要能力概览

从用户角度，可以把 MCP 的能力简单理解成四组：

- 会话管理：`session_open_quick`、`session_open`、`session_status`、`session_close`、`session_recover`
- 一次性执行：`eval_js`
- 受管脚本：`install_snippet`、`call_snippet`、`inspect_snippet`、`remove_snippet`、`list_snippets`
- 辅助信息：`tail_logs`、`prepared_session_inspect`、`prepared_session_prune`

对应资源包括：

- `frida://service/config`
- `frida://session/current`
- `frida://session/prepared`
- `frida://session/snippets`
- `frida://session/logs`
- `frida://docs/mcp/*`

## 你应该预期的行为

有几个重要限制需要明确：

- 当前只支持 `stdio`
- 当前一个 MCP 进程只维护一个活动调试会话
- quick session 不是通用 npm 包管理器，只允许官方 capability subpath
- quick session 不接管 watch / hot reload
- broken session 不会自动 recover
- recover 后不会自动重装 snippet
- prepared workspace 缓存默认会留在磁盘上，直到你主动 prune

## 推荐给用户的实践建议

- 把 `mcp.toml` 当成“服务级环境配置”，不要让模型每次都重新决定 host、device、server path
- 把 `session_open_quick(...)` 当成默认入口
- 让模型先读 `frida://service/config` 和 `frida://docs/mcp/*`
- 早期 hook 尽量用 `bootstrap_path`，这样脚本变更在你的仓库里是可见的
- 把会重复验证的逻辑收敛到 `install_snippet(...)`
- 任务结束时主动 `session_close(...)`，不要单纯依赖 idle timeout

## 相关资料

如果你是用户而不是模型，这几个位置最值得一起看：

- 根文档：[README.md](../../../README.md)
- MCP 内置文档资源目录：[src/frida_analykit/resources/mcp_docs](../resources/mcp_docs)
- scaffold 示例：[src/frida_analykit/resources/scaffold/README.md](../resources/scaffold/README.md)

如果你是通过 MCP client 使用这个服务，建议先把这份 README 给人看，再让模型读取 `frida://docs/mcp/*` 资源。

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
- 当前 MCP 进程环境里的 `PATH` 已经能找到 `frida-compile`
- 当前 MCP 进程环境里的 `PATH` 已经能找到 `npm`
- 远端 `frida-server` 已经按你的环境预先准备好
- 如果需要，远端 `frida-server` 已经被你手动安装、启动或放到固定路径

MCP 不负责在运行时替你切换 Frida 版本，也不负责自动安装或选择 `frida-server` 版本。
从当前版本开始，MCP 也不会带着“不完整但先启动再说”的 degraded quick path 继续服务。quick toolchain 没准备好，服务就直接 fail-fast 退出。

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
- 会话归档目录
- 空闲回收时间

最小示例：

```toml
[mcp]
idle_timeout_seconds = 1200
session_history_root = "./session-history"

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
- 启动时固定先做 `startup preflight -> startup warmup -> stdio serve`
- 预热会验证 `prepared_cache_root` 可写、`frida-compile` 与 `npm` 可用、shared runtime toolchain 可复用或可安装、以及一次最小 compile sanity probe
- 如果以上任一环节失败，MCP 不会进入 serve，而是打印带状态符号的 banner 后直接非零退出
- `frida://service/config` 也会暴露实际生效的 `session_history_root`

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
   这里主要用来读取当前 MCP 进程固定下来的 server/output 默认值，并确认 quick path 是否已经 `ready`
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
- 在生成的 `index.ts` 里直接保留这些 capability 的原始 binding 引用，避免只 import 但未引用时被 bundler 裁剪
- 让生成出来的 `index.ts` 尽量直接表现 MCP 最终实际编译的入口代码
- 复用共享的轻量 runtime `node_modules` 缓存
- 通过 MCP 进程 `PATH` 中的 `frida-compile` 编译 `_agent.js`
- 生成一份继承 `mcp.toml` 默认值的 `config.toml`
- 复用同参数签名下的缓存结果

这里的共享语义需要特别说明：

- quick path 的 `npm_config_cache` 固定落在 `prepared_cache_root/npm-cache`
- shared toolchain 固定落在 `prepared_cache_root/_toolchains/<digest>`
- 因此共享粒度是“同一个 prepared cache root + 同一个 agent package spec”，不是“每个 Python 虚拟环境各自一份”
- 普通工作区里的 `npm install` / `frida-analykit build` 仍然主要使用工作区自己的 `node_modules`，不自动并入 MCP 这套 shared cache
- `prepared_cache_root` 继续只承担内部 quick build/cache 角色，不是给用户直接查阅会话历史的主目录
- 每个真实 MCP 会话都会在 `session_history_root` 下创建一个 `{yyyyMMdd-HHMMSS-shortid}` 目录，里面保存 copied `workspace/`、`session.json`、`events.jsonl` 和 snippet 历史源码

只有在你已经自己维护好了工作区，并且明确想让 MCP 直接消费现成 `config.toml` 或 legacy YAML 时，才建议使用低层的 `session_open(...)`。

还要注意一点：`session_open(...)` 不是 quick-path 启动失败时的绕过通道。`frida-analykit-mcp` 进程本身仍然要求 quick warmup 达到可用状态才会启动；如果启动阶段已经 fail-fast，需要先修 MCP 环境并重启服务。

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
- `template`：使用哪种官方最小模板，它本质上是一个 curated preset
- `capabilities`：在 template 之上额外预加载哪些全局能力

## `bootstrap_path` 和 `bootstrap_source`

这两个字段都是给“刚注入就要执行的初始化逻辑”准备的。

推荐分工：

- `bootstrap_path`：适合复用你仓库里真实存在的 `.ts` 或 `.js` 文件
- `bootstrap_source`：适合一次性的内联初始化代码

如果你的早期 hook 需要被用户看见、跟踪、修改、走版本管理，优先用 `bootstrap_path`。

如果只是很短的一次性初始化逻辑，才考虑 `bootstrap_source`。

这两者都属于 quick session 的注入前准备逻辑，不会进入 snippet registry。

## `template`、`capabilities` 和 bootstrap 的关系

这三者的分工建议固定理解成：

- `template`：官方预设
- `capabilities`：附加 preload globals
- `bootstrap_path` / `bootstrap_source`：目标相关初始化代码

也就是说，`session_open_quick(...)` 里的 `template` 和 `capabilities` 不是通用 import 注入接口。

它们更适合“先把一些会挂到 `globalThis` 或能直接被 `/rpc` 看到的能力预加载起来”，然后再让 bootstrap 或后续 `eval_js(...)` 直接使用。

当前 quick path 会在生成的 `index.ts` 里对这些 capability 做显式本地引用，以避免只 import 不引用时被 `frida-compile` 裁剪。这个 retain 语义现在属于 generated workspace，而不是 agent runtime 内部的隐式契约。

另外，generated quick `index.ts` 本身就是当前 quick session 的最终编译入口：

- capability preload 会直接以真实 import + `void Xxx` 的形式出现在里面
- `bootstrap_source` 会直接内联进这个 `index.ts`
- `bootstrap_path` 仍保持为单独文件 import，但 quick path 只会复制这一个文件进入 prepared workspace

也就是说，quick `bootstrap_path` 应该视为 self-contained 文件：

- 如果它只依赖包导入或文件内自身逻辑，继续用 `session_open_quick(...)`
- 如果它还依赖同目录下的相对 import、局部模块图或完整 workspace，就改用 `session_open(config_path, ...)`

如果你已经有一个主要维护的 `bootstrap_path` 文件，并且真正依赖关系都应该写在那个文件里，那么更建议：

- 用 `template="minimal"`
- 把需要的 import 直接写进 `bootstrap_path`
- 并对关键 binding 做一次显式引用，而不是依赖 bare import 一定会被保留

这样脚本本身的依赖关系会更直观，也更适合让用户和模型一起维护。

像 `@zsa233/frida-analykit-agent/elf/enhanced` 这种不会注册全局能力的模块，就不应该作为 quick capability 使用，而应该放在 `bootstrap_path`、`bootstrap_source` 或自定义 workspace 里自己 import。

## 如何知道 quick session 里能直接用哪些对象

对 MCP client 或大模型来说，最重要的是区分下面三层：

- Frida 自带全局对象，例如 `Process`、`Module`，以及 Android 上通常已经存在的 `Java`
- quick template / capability 明确承诺会出现的 analykit globals
- 某些 capability 因为内部依赖而顺带出现的“传递性全局对象”

推荐只把第二层当作稳定契约。第三层可能会随着 runtime 内部实现调整而变化，不应该当作文档主线依赖。

如果想让模型自己发现这些能力，优先让它读取：

- `frida://docs/mcp/tools`
- `frida://docs/mcp/quickstart`
- `frida://docs/mcp/workflow`

其中 `frida://docs/mcp/tools` 现在会明确说明 template / capability 对应的主要全局对象和示例 `eval_js(...)`。

还需要特别注意一点：

- Android 上即便是 `template="minimal"`，`Java` 也通常已经存在
- 这并不代表 `java_bridge` 没意义
- `java_bridge` / `jni` 的真正价值是把 `JNIEnv`、`jobject`、`jclass` 这类显式 JNI 包装也准备好

另外，`native_libc` 目前暴露的是 `Libc` 类，不是 `libc` 实例。如果你在 `eval_js(...)` 里要用它，写法应是 `const libc = new Libc()`。

## 常见 quick preset / capability 用法

下面这些是更适合写进 MCP 文档主线的高频用法。

### `process_probe`

适合先做“进程是否就绪、maps 长什么样、输出目录在哪里”这类轻量探测：

```js
help.proc.readCmdline()
proc.loadProcMap().items.length
help.runtime.getOutputDir()
```

### `java_bridge`

适合 Java + JNI 混合检查。`Java` 在 Android 上往往本来就有，但这里的关键是 `JNIEnv`：

```js
JNIEnv.$handle
Java.performNow(() => Java.use("android.app.ActivityThread").currentPackageName())
```

### `dex_probe`

适合 dex loader 枚举和整包 dump：

```js
DexTools.enumerateClassLoaderDexFiles().length
DexTools.dumpAllDex("case-001")
```

如果目的是把目标 app 的 dex 全部导出，这通常就是推荐起手式。

### `ssl_probe`

适合 libssl / BoringSSL 相关验证：

```js
SSLTools.attachLibsslKeylogFunc("sslkey.log")
BoringSSL.loadFromModule(Process.getModuleByName("libsscronet.so")).scanKeylogFunc()
```

### `elf_probe`

适合模块、符号和 snapshot 取证：

```js
ElfTools.findModuleByName("libc.so")?.name
ElfTools.snapshot("libc.so", { tag: "manual" })
```

如果你要用 `elf/enhanced` 的额外 helper，不要继续塞进 quick capability，而要放到 `bootstrap_path` 或自定义 workspace import 里。

### 低层 native binding

如果只需要底层绑定，不一定要上完整 preset：

```js
Libart.$getModule().name
Libssl.$getModule().name
(new Libc()).getpid()
```

这类能力更适合“明确知道自己在做什么”的精确验证，而不是通用 quick preset。

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

另外需要明确：

- `install_snippet(...)` 成功后，源码会归档到当前会话目录下的 `snippets/`
- 这只是历史记录，不会在新的会话里自动 replay
- `frida://session/snippets` 仍然只表示当前 live session 的内存状态

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
- quick session 依赖 MCP 运行环境中预装的 `frida-compile`
- quick session 不会在每个 prepared workspace 里安装 `frida-compile`、`frida` 或 `@types/node`
- quick session 不接管 watch / hot reload
- broken session 不会自动 recover
- recover 后不会自动重装 snippet
- prepared workspace 缓存默认会留在磁盘上，直到你主动 prune

## 推荐给用户的实践建议

- 把 `mcp.toml` 当成“服务级环境配置”，不要让模型每次都重新决定 host、device、server path
- 把 `session_open_quick(...)` 当成默认入口
- 让模型先读 `frida://service/config`，再读 `frida://docs/mcp/quickstart`、`frida://docs/mcp/tools` 和 `frida://docs/mcp/workflow`
- 早期 hook 尽量用 `bootstrap_path`，这样脚本变更在你的仓库里是可见的
- 如果 `bootstrap_path` 已经是主脚本，优先 `template="minimal"`，并把真正依赖写在脚本文件里
- 把会重复验证的逻辑收敛到 `install_snippet(...)`
- 任务结束时主动 `session_close(...)`，不要单纯依赖 idle timeout

## 相关资料

如果你是用户而不是模型，这几个位置最值得一起看：

- 根文档：[README.md](../../../README.md)
- MCP 内置文档资源目录：[src/frida_analykit/resources/mcp_docs](../resources/mcp_docs)
- scaffold 示例：[src/frida_analykit/resources/scaffold/README.md](../resources/scaffold/README.md)

如果你是通过 MCP client 使用这个服务，建议先把这份 README 给人看，再让模型读取 `frida://docs/mcp/*` 资源。

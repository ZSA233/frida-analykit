# PRE_README

## 文档定位

本文件是 `README.md` 的实时维护中间文档，也是后续 release 前统一收束 README 的事实基线。

与 `README.md` 的区别：

- `PRE_README.MD` 偏工作文档，要求更完整、更细、更贴近当前仓库真实状态。
- `README.md` 偏对外文档，要求更稳定、更精炼、更强调主线叙述。
- 只要用户可见能力、配置、命令行、接入方式、限制条件发生变化，应先更新本文件。
- release 前收束 `README.md` 时，应基于本文件整体整理，而不是仅把最近一次改动直接拼接进 README。

本文件的初始化快照基于当前仓库状态整理，当前更新快照时间为 `2026-04-01`。

## README 收束风格基线

README 收束时，应同时遵循下面这些约束：

- `PRE_README.MD` 是事实基线，也是 README 风格基线。
- 对外 README 应比 `PRE_README.MD` 更短、更稳、更主线化，不要把本文件中的工作痕迹、排查细节和中间态说明原样搬进去。
- 根 `README.md` 与 `README_EN.md` 必须是严格镜像的中英版本，只允许语言翻译上的差异，不允许一边多写、一边漏写。
- `packages/frida-analykit-agent/README.md` 与 `packages/frida-analykit-agent/README_EN.md` 也必须遵循同样的严格镜像规则。
- 根 README 的默认叙述顺序应为：项目定位与架构图、普通用户安装与使用 CLI、普通用户主线工作流、常用配置与命令、高级/开发能力、调试/测试/发布与仓库结构。
- agent 包 README 的默认叙述顺序应为：包定位、安装、能力总览表、普通使用方式、高级能力、调试与非公共内容。
- 当能力项较多、导入路径较多或需要区分轻入口/显式 capability 时，应优先用表格呈现，而不是散列 bullet。
- 根 README 的架构图必须读取并嵌入 `docs/arch.mermaid` 的 Mermaid 源码；在架构未变时，这个 `.mermaid` 文件视为只读事实源。
- README 收束完成后，必须执行一次二次校对，至少检查标题树、表格、代码块、提示项和限制说明是否在中英文两侧完全同构。

## 当前仓库快照

### 分支与版本状态

- 当前版本真源：`release-version.toml`
- Python 包版本、根 `package.json` 版本和 npm runtime 包 `@zsa233/frida-analykit-agent` 版本，统一由 `release-version.toml` 在 RC / stable 切换时派生，不再手改。

## 项目定义

`frida-analykit` v2 是一个双产物 monorepo：

- Python CLI：负责 `frida-server` 生命周期管理、设备连接、日志与二进制数据落盘、attach/spawn、REPL、脚手架生成、兼容性检查和开发环境管理。
- Python CLI 还额外提供独立的 stdio MCP 命令 `frida-analykit-mcp`，用于把现有 Frida 调试链路暴露给 MCP client / 大模型。
- npm runtime：发布为 `@zsa233/frida-analykit-agent`，提供给用户自定义 TypeScript Frida agent 使用的 runtime、公用 helper、RPC 支撑和部分逆向辅助能力。

v2 的核心设计不是“把所有 agent 代码都塞在 Python 仓库里”，而是把职责拆开：

- Python CLI 负责编排、注入、环境和产物落地。
- 用户在独立 TypeScript 工作区里维护自己的 agent。
- npm runtime 为这些 TS agent 提供统一能力面。

这是一个破坏性升级方向，相比 v1 已经明显改成了：

- monorepo 结构
- Python CLI + npm runtime 双产物
- `gen dev` 生成独立工作区
- `frida-analykit` 命令行成为主入口

## 当前主线工作流

当前用户常用的标准流程，通常应理解为下面这条链路：

1. 先用 `frida-analykit env create --frida-version <version> [--name <env>]` 创建一个与目标 Frida 版本匹配的虚拟环境。
2. 再用 `frida-analykit env shell [name]` 进入该虚拟环境。
3. 在准备好的工作目录中执行 `frida-analykit gen dev --work-dir ./my-agent`，生成独立的 TS agent 工作区。
4. 进入工作区后执行 `npm install`，安装脚本依赖。
5. 根据目标应用、设备和输出路径，补全或调整 `config.toml`。
6. 先执行 `frida-analykit doctor --config ./config.toml`，确认当前 Python Frida、compat 状态、设备连接和远端 `frida-server` 状态。
7. 如果 `doctor` 标出远端 `frida-server` 的安装 / 版本红项，可先执行 `frida-analykit doctor fix --config ./config.toml`；它只修安装 / 版本，不会自动 boot。
8. 如果设备上还没有合适的 `frida-server`，则执行 `frida-analykit server install --config ./config.toml`。
9. 如需显式指定版本，可通过 `config.server.version` 或 `frida-analykit server install --config ./config.toml --version <version>` 控制；安装目标路径由 `config.server.path` 决定。
10. 在一个终端中执行 `frida-analykit server boot --config ./config.toml` 启动远端 `frida-server`。
11. 在另一个终端中执行 `frida-analykit spawn --config ./config.toml` 或 `frida-analykit attach --config ./config.toml` 完成注入。
12. 如果 `index.ts` 还未编译成 `_agent.js`，则应先执行 `frida-analykit build --config ./config.toml`，或者在运行时命令中加 `--build` 让 CLI 先构建后注入。
13. 如果要把当前设备和注入链路交给 MCP client / 大模型，则在宿主机上单独启动 `frida-analykit-mcp --config ./mcp.toml`，由 client 通过 stdio 连接，先读 `frida://service/config` 与 MCP docs resource，再优先走 `session_open_quick(...)` 这条高层入口。

当前 v2 的主线开发模式，应理解为：

- 用户维护独立的 TypeScript agent 工作区
- Python CLI 负责环境、构建编排、server 运维、注入和日志归档

## 当前已实现能力总览

### 1. Python CLI 能力

当前 CLI 顶层命令包括：

- `gen`
- `env`
- `server`
- `build`
- `watch`
- `spawn`
- `attach`
- `doctor`

CLI 还支持顶层 `--version`。

当前还会随 Python 包一起安装一个独立命令：

- `frida-analykit-mcp`

### 2. 生成自定义 TypeScript agent 工作区

命令：

```sh
frida-analykit gen dev --work-dir ./my-agent
```

当前脚手架会生成：

- `README.md`
- `config.toml`
- `index.ts`
- `package.json`
- `tsconfig.json`

当前脚手架特征：

- 生成的 runtime 依赖会固定到当前 Python release 对应的 `@zsa233/frida-analykit-agent` 版本。
- 当前 npm package spec 支持 Python RC 版本映射到 npm RC 版本，例如 `2.0.0rc1 -> 2.0.0-rc.1`。
- 生成的 npm 脚本默认为：

```json
{
  "build": "frida-compile index.ts -o _agent.js -c",
  "watch": "frida-compile index.ts -o _agent.js -w"
}
```

### 3. TypeScript agent 构建与监听

CLI 目前支持两类前端编排动作：

- `frida-analykit build`
- `frida-analykit watch`

以及在运行时命令里复用构建流程：

- `frida-analykit attach --build`
- `frida-analykit attach --watch`
- `frida-analykit spawn --build`
- `frida-analykit spawn --watch`

当前行为要点：

- 默认从 `config.toml` 所在目录推断 TS 工作区根目录。
- 也可以通过 `--project-dir` 覆盖工作区目录。
- `--install` 会在工作区缺失 `node_modules` 时自动执行 `npm install`。
- `build` 会执行 `npm run build`。
- `watch` 会执行 `npm run watch`，并等待首个成功产物生成。
- `config.jsfile` 必须与 npm 构建产物路径一致，否则 CLI 会报错。
- `attach --watch` / `spawn --watch` 的语义是“等首个 bundle 生成后再注入”，不是对已经加载的 session 做自动热重载。

### 4. attach / spawn / REPL

当前运行时注入命令包括：

- `frida-analykit spawn --config config.toml`
- `frida-analykit attach --config config.toml`

当前行为特征：

- `spawn` 要求 `config.app` 必填。
- `attach` 可以显式传 `--pid`。
- 如果 `attach` 未传 `--pid`，且 `config.app` 存在，则会尝试通过应用标识自动解析 PID。
- `--repl` 会进入 `ptpython` REPL。
- REPL 中会注入 `config`、`device`、`pid`、`session`、`script` 等对象。
- 这里注入给普通 CLI / REPL 的 `script` 默认是 sync-first wrapper；async wrapper 只保留给 Promise-aware expert 场景和 MCP 内核。
- REPL 还会按 `script.repl.globals` 懒注入一组 JS seed handle；当前模板默认包括 `Process`、`Module`、`Memory`、`Java`、`ObjC`、`Swift`。
- 这些 REPL 变量不会在进入 REPL 时立刻触发 RPC enumerate，而是在首次真实使用时才 materialize 成 `script.jsh(name)` 对应句柄。
- `--repl` 当前已经切到 async ptpython 模式，但交互建议仍然是“对象浏览默认 sync，Promise-aware 场景再切 async”：由 `script.jsh(...)` / `script.eval(...)` 产生的 sync handle 适合做属性链、getter 和长路径浏览；`await script.eval_async(...)`、`await handle.call_async(...)`、`await handle.resolve_async()` 主要用于需要等待 Promise 的场景。
- `script.eval(...)` / `script.eval_async(...)` 当前会优先把输入当作“表达式”求值，因此像 `Process.arch`、`Promise.resolve(Process.arch)` 这类 REPL 常见写法会直接返回表达式结果；如果输入本身是多语句 body，则会回退到原始函数体执行方式。
- `script.eval("Promise.resolve(Process.arch)")` 这类同步调用会返回 Promise 的句柄，不会自动等待；`await script.eval_async("Promise.resolve(Process.arch)")` 则会在 agent 侧先 await 一层 Promise，再把 resolved value 包成 async handle。
- `JsHandle.value_` 当前除了 primitive/plain-object 结果外，也会尽量把 Frida 侧常见 getter-backed 对象投影成有界的 JSON-safe snapshot，例如 `Process.mainModule.value_`、`Process.findModuleByName("libc.so").value_` 这类模块对象读取路径。
- 如果某个句柄值仍无法被投影到 RPC bridge，则 `value_` 仍会报 `RPCValueUnavailableError`；这种场景应继续使用链式句柄访问，或显式 `await handle.resolve_async()`。
- 当前 `AsyncJsHandle` 不提供和 sync handle 完全对称的属性链体验；如果确实需要在 async handle 上访问子路径，应显式使用 `await handle.resolve_path_async("a.b.c")`，而不是把 async REPL 当作 sync 句柄浏览的等价替代。
- REPL 句柄与 scope 相关调用在首次使用前会先做一次 agent runtime 协议握手。
- 如果加载到设备上的 `_agent.js` 仍是旧 bundle，Python 侧会直接抛出 `RPC runtime mismatch`，提示用户重新用当前仓库打包本地 runtime 并 rebuild `_agent.js`，而不是再把底层 Frida `TypeError: value is not iterable` 直接暴露给用户。
- 如果未开启 `--repl`，CLI 默认保持会话存活，适合持续收集日志和数据。

当前实现里还有一个隐藏参数 `--detach-on-load`，主要用于 smoke/device 测试验证“脚本成功加载后立即退出”，不应作为 README 主线公开能力来强调，但应记得它存在。

### 4.1 MCP 长会话服务

当前 MCP 命令入口：

```sh
frida-analykit-mcp --config ./mcp.toml
```

当前行为特征：

- 当前只支持 stdio transport，不支持 HTTP / SSE。
- 默认只维护一个活动调试会话，不做多会话并存。
- `--config` 是可选的 MCP 启动 TOML；未提供时，MCP 会回退到内建默认值。`--idle-timeout` 继续保留为 CLI override。
- MCP 启动现在固定走三阶段：`startup preflight -> startup warmup -> stdio serve`。只要 quick-path 所需工具链缺失或 warmup 失败，进程就会 fail-fast 非零退出，不会继续进入 serve。
- 启动 banner 会打印一组 quick-path readiness 状态行；如果 `stderr.isatty()`，则用 ANSI 颜色渲染 `✓ / ✗ / ●`，否则保留同样的状态符号但不输出转义序列。
- Python 侧实现已经切到 async-first manager 主线，并且不再保留独立的 sync MCP manager public surface。
- MCP tools 当前统一走 `AsyncScriptWrapper` / `AsyncJsHandle` 这条 Promise-aware agent/RPC 语义，不提供 REPL 里那套以 sync handle 为主的对象浏览体验。
- 因此在 MCP 中如果要访问 `a.b.c` 这类长路径，推荐直接把路径写进 `eval_js` / snippet 源码，或封装成 snippet method 返回结构化值，而不是依赖交互式属性链浏览。
- MCP 启动 TOML 当前固定覆盖这些服务级静态字段：
  - `[mcp]`：`idle_timeout_seconds`、`prepared_cache_root`
  - `[server]`：`host`、`device`、`path`
  - `[agent]`：`datadir`、`stdout`、`stderr`
  - `[script.dextools]`：`output_dir`
  - `[script.elftools]`：`output_dir`
  - `[script.nettools]`：`ssl_log_secret`
- 这些服务级默认值在 MCP 进程启动后固定不变，`session_open_quick` 不再让大模型逐次指定 `host`、`device`、`path`、`server.version` 或 runtime 包版本。
- `session_open` 首次需要 `config_path` 和 `mode`；如果当前 live session 与目标一致，则直接复用；如果目标不同，则需要 `force_replace=true`。
- 推荐入口 `session_open_quick(app, mode, capabilities?, template?, bootstrap_path?, bootstrap_source?, ...)`：它会自动生成最小 `index.ts`、复用共享轻量 runtime cache、使用 MCP 进程 `PATH` 中预装的 `frida-compile` 编译 `_agent.js`、写出继承 startup config 的 `config.toml`，然后复用同一套 session manager 打开会话。
- `session_open` 继续保留为底层显式入口，适用于用户已经自定义维护好的工作区。
- 当前 tool 集合固定为：
  - `session_open`
  - `session_status`
  - `session_open_quick`
  - `session_close`
  - `session_recover`
  - `eval_js`
  - `install_snippet`
  - `call_snippet`
  - `inspect_snippet`
  - `remove_snippet`
  - `list_snippets`
  - `tail_logs`
  - `prepared_session_inspect`
  - `prepared_session_prune`
- 当前 resource 集合固定为：
  - `frida://service/config`
  - `frida://session/current`
  - `frida://session/prepared`
  - `frida://session/snippets`
  - `frida://session/logs`
- `frida://service/config` 现在除了固定 startup config 外，还会返回结构化的 `quick_path` readiness / warmup 摘要，至少覆盖 cache root、`npm`、`frida-compile`、shared toolchain 和 compile probe，并暴露实际生效的 `session_history_root`。
- 当前还会额外暴露六个可查询 Markdown 文档 resource：
  - `frida://docs/mcp/index`
  - `frida://docs/mcp/config`
  - `frida://docs/mcp/quickstart`
  - `frida://docs/mcp/workflow`
  - `frida://docs/mcp/tools`
  - `frida://docs/mcp/recovery`
- 默认 idle timeout 是 `1200` 秒，可通过 `--idle-timeout` 覆盖；超时后会自动回收当前 live session。
- MCP server 不会复用 CLI 的 session banner / 普通 stdout 输出路径，避免污染 stdio 协议通道。
- `eval_js` 只做一次性求值；`install_snippet(name, source)` 会保留返回的根 handle，并按名称管理它，同时把源码归档到当前会话目录下的 `snippets/` 中。
- 如果 snippet 根对象暴露 `dispose` 方法，则 `remove_snippet` 会先尝试调用它，再释放对应 handle。
- `session_open_quick` 会在 MCP 专用缓存目录里自动生成最小 TS workspace，复用一份共享的轻量 runtime 依赖缓存，并通过 MCP 进程 `PATH` 中预装的 `frida-compile` 构建 `_agent.js`；相同参数签名会复用缓存结果。
- 每个真实 MCP 会话都会在 `session_history_root` 下分配独立目录，目录名固定为 `{yyyyMMdd-HHMMSS-shortid}`；这个目录会保存 copied `workspace/`、`session.json`、`events.jsonl` 和 snippet 历史源码。
- quick generator 现在会在生成的 `index.ts` 里对 capability 做显式本地 binding 引用，以避免只 import 但未引用时被 bundler 裁剪；这属于 generated workspace 语义，不再依赖 agent runtime 内部 retain helper。
- `session_open_quick` 同时支持 `bootstrap_path` 和 `bootstrap_source`：前者会复制本地 `.ts` / `.js` 文件到 prepared workspace 并导入，后者则生成一段内联 bootstrap 文件；它们都不进入 snippet registry。
- quick path 只允许官方 `@zsa233/frida-analykit-agent` capability subpath / 模板名，不开放任意 npm 包和任意 import 文本。
- quick path 不会在每个 prepared workspace 里安装 `frida-compile`、`frida` 或 `@types/node`；MCP 会在启动时先检查 `PATH` 里的 `frida-compile` 和 `npm`，并预热一份 shared runtime toolchain 与 compile probe。只要这一步失败，服务就不会启动。
- quick path 的共享粒度不是“按 Python 虚拟环境”，而是“按 `prepared_cache_root` + agent package spec”：`npm_config_cache` 指向 `prepared_cache_root/npm-cache`，shared toolchain 位于 `prepared_cache_root/_toolchains/<digest>`。普通 workspace `npm install` / `build` 仍然是另一条链路。
- `prepared_cache_root` 继续只承担内部 quick build/cache 角色；给用户看的会话记录和持久化 snippet 不放在 signature cache 目录里，而是放到 `session_history_root`。
- `session_open(config_path, ...)` 仍然保留给显式 workspace，但它是 MCP 成功启动后的低层会话入口，不是 quick warmup 失败时的启动绕过路径。
- 当前不会替 MCP 接管 watch / hot reload；`session_open_quick` 只负责一次性 prepare + build，`session_open` 仍要求 `config.jsfile` 已经是可注入的 bundle。
- 当前要求加载到设备上的 `_agent.js` 已导入 `@zsa233/frida-analykit-agent/rpc`；如果 bundle 仍缺 `/rpc`，MCP 会直接返回 `RPC runtime mismatch` 类错误，提示用户 rebuild 本地 runtime。
- `install_snippet` 仍只用于会话已打开后的受管 controller 生命周期，不扩展成 pre-open bootstrap 机制。
- snippet 持久化只是归档，不会自动在后续新会话里 replay；`frida://session/snippets` 仍然只表示当前 live session 的内存状态。
- MCP 不负责运行时切换 Frida / frida-server 版本，也不负责自动安装；这部分环境由用户在启动 MCP 前预先准备。
- 如果会话因为 detach / crash 进入 broken，MCP 不会自动 reattach，也不会自动 replay 已安装 snippet；需要显式调用 `session_recover`，并在恢复后按需重新安装 snippet。
- 给 MCP client / 大模型的推荐顺序是：
  - 先读 `frida://service/config`、`frida://docs/mcp/config`、`frida://docs/mcp/index`、`frida://docs/mcp/quickstart` 和 `frida://docs/mcp/workflow`
  - 使用 `frida://service/config` 读取当前 MCP 进程固定下来的默认值，并检查 `quick_path.state == "ready"`
  - 再 `session_open_quick`
  - 先用 `eval_js` 做一次性验证
  - 需要复用时再切到 `install_snippet` / `call_snippet`
  - 结束时主动 `session_close`，不要只依赖 idle timeout

### 5. 会话 banner、日志与 bootstrap 诊断

当前注入流程会在加载脚本时打印一个 session banner，其中包含：

- 当前版本号
- 当前 host
- 当前 target/app
- 当前脚本路径
- stdout/stderr 路径，或共享日志路径

当前对 ESM agent 的 bootstrap 还做了额外兜底：

- 会在注入包装层中为 `await import("/index.js")` 加上错误捕获。
- 如果 import/bootstrap 阶段出错，会输出 `[frida-analykit/bootstrap] ...` 错误信息和 stack。
- 这使得“顶层 import 失败，但后续 `console.log()` 根本没机会执行”的场景更容易排查。

### 6. RPC、日志归档与二进制数据落盘

Python 侧目前已经有一套 RPC message / handler 体系。

当前结构已经明确拆成：

- `SessionWrapper` + `SyncScriptWrapper` / `AsyncScriptWrapper`：负责会话装配、脚本加载、banner 与 logger 接线。
- `SyncRPCClient` / `AsyncRPCClient`：负责 mode-specific RPC 调用、scope 管理和 runtime 握手。
- `HandleRef` + `SyncJsHandle` / `AsyncJsHandle`：负责 REPL 句柄、链式引用和显式的 sync/async 访问边界。
- async 路径当前改成 capability-based 选择：优先探测已加载 script 的真实 async export 能力；若缺完整 native async surface，则自动回退到 shim async。compat profile 只保留给诊断和文档，不再参与 async 分流决策。
- 当前 breaking cleanup 已经移除了旧的 compat public surface：`ScriptWrapper`、`RPCClient`、`DebugSessionManager` 不再作为对外 owner 保留。

已知消息类型包括：

- `SCOPE_CALL`
- `SCOPE_EVAL`
- `SCOPE_GET`
- `ENUMERATE_OBJ_PROPS`
- `BATCH`
- `INIT_CONFIG`
- `SAVE_FILE`
- `SSL_SECRET`
- `PROGRESSING`

新增的 dex dump 消息链路包括：

- `DEX_DUMP_BEGIN`
- `DUMP_DEX_FILE`
- `DEX_DUMP_END`
- `BATCH(source=DEX_DUMP_FILES)`

当前 `@zsa233/frida-analykit-agent/dex` 已提供 `DexTools` capability：

- `DexTools.enumerateClassLoaderDexFiles()` 返回 plain metadata，不暴露旧版 Java wrapper
- `DexTools.dumpAllDex()` 会按最大批量字节数流式发送 dex 文件
- 默认最大批量上限为 `8 MiB`
- Python 侧默认输出目录优先取 `script.dextools.output_dir`，否则回退到 `agent.datadir/dextools`

- ART 相关 native 符号绑定已抽到共享 `@zsa233/frida-analykit-agent/native/libart`

### 7. DexTools 配置

当前 `config.toml` 已支持：

```toml
[script.rpc]
batch_max_bytes = 8388608

[script.dextools]
output_dir = "./data/dextools/"
```

行为说明：

- `batch_max_bytes` 是通用 RPC batch 传输上限，不只服务于 dex dump
- 它会注入到 agent `Config.BatchMaxBytes`
- `BatchSender` 在未显式覆盖时默认使用这个全局上限
- `output_dir` 为 Python 侧接收 dex dump 的默认目录
- agent 侧 `DexTools.dumpAllDex()` 可通过 `maxBatchBytes` 参数临时覆盖配置值

### 7.1 ElfTools 配置

当前 `config.toml` 已支持：

```toml
[script.elftools]
output_dir = "./data/elftools/"
```

行为说明：

- `output_dir` 为 Python 侧接收 ELF snapshot 与 symbol call log 的默认目录
- `snapshot()` 的产物会写到 `snapshots/<tag-or-id>/`
- `ELF_SYMBOL_CALL_LOG` 会写到 `logs/<tag>.log`
- 如果未配置 `script.elftools.output_dir`，则回退到 `agent.datadir/elftools`

当前默认行为：

- `PROGRESSING` 会被格式化打印到 stdout/stderr。
- `SSL_SECRET` 会落到 `script.nettools.ssl_log_secret` 指定目录。
- 未专门注册的消息会按默认处理器打印摘要。
- 如果消息带有二进制 payload，且 `agent.datadir` 已配置，会把数据落到该目录下，文件名类似 `SAVE_FILE_<timestamp>`。
- 如果未设置 `agent.datadir`，则会提示 payload 被丢弃。
- Python 与 agent runtime 之间现在有显式 `rpcRuntimeInfo()` 协议预检，当前要求的关键特性至少包括结构化 `HandleRef` 和 async scope 镜像能力。

### 7. 设备回归与 pre-release runtime 验证

当前设备测试已不只验证“能注入一段 marker 脚本”，还覆盖了 REPL 核心路径：

- `script.jsh("Process")` 的 seed path 句柄创建
- 同步链式调用和 `.value_` 取值
- `eval_async(...)` + `resolve_async()` 的 Promise-aware 路径
- 私有 JS 单测包驱动的 `JNIEnv` wrapper 回归路径

当前用于 pre-release 协议校验的真机测试原则：

- 不直接复用脚手架默认发布版 `@zsa233/frida-analykit-agent`
- 先对当前仓库内 `packages/frida-analykit-agent` 执行 `npm pack`
- 如需验证 agent 内部单测，还会对 `packages/frida-analykit-agent-device-tests` 执行 `npm pack`
- 再以 `file:<tarball>` 形式生成临时 TS workspace
- 最后 build 出新的 `_agent.js` 后再做真机验证

这样真机测试验证的是“当前 Python 工作树 + 当前 agent 工作树”的真实组合，而不是某个已发布版本的历史 bundle。

当前新增了一条专门的 agent 单测运行方式：

- `packages/frida-analykit-agent-device-tests` 是私有 npm package，只供仓库内 `tests/device` 使用
- 它不会进入正式 runtime 包的 `dependencies` / `exports` / 用户脚手架
- 真机测试会在临时 workspace 中先导入 `@zsa233/frida-analykit-agent/rpc`
- 再导入私有测试包并执行 `installAgentUnitRpcExports()`
- 最后由 Python 侧通过结构化 RPC exports `listAgentUnitSuites()` / `runAgentUnitSuite(name)` 拉起测试并汇总结果

当前私有 agent 单测 suite 已至少包括：

- `helper_core`
- `helper_runtime`
- `jni_env_wrappers`
- `jni_member_facade`
- `jni_member_facade_arrays`
- `jni_member_facade_nonvirtual`

其中 `helper_core` 当前专门覆盖：

- `LoggerState`
- `BatchSender`
- `ProgressNotify` 的注入式 sender
- `help` facade alias 与 grouped API 对齐

其中 `helper_runtime` 当前专门覆盖：

- `help.fs.getLogFile(...)` 的本地文件回归
- `help.proc.readMaps()` / `readCmdline()`
- `help.mem.scan(...)` 与 `withReadableRange(...)`
- `help.runtime.androidApiLevel()` / `newBatchSender(...)`

其中 `jni_member_facade` 当前专门覆盖：

- `jobject` / `jclass` 的 member facade 链式调用
- instance/static method accessor 与 direct shortcut
- constructor accessor 与 `.$new(...)`
- instance/static field get 路径，以及 instance field set 路径
- accessor `withLocal(...)` 的局部引用使用方式
- unbound accessor 漏传 target 时的 fail-fast 保护

其中 `jni_member_facade_arrays` 当前专门覆盖：

- object array 返回值仍按 JNI local ref 语义管理，而不是误当作 element buffer
- primitive array 返回值先得到 array ref wrapper，再通过 `.$elements()` / `withElements(...)` 获取 raw buffer
- array facade 返回值在 `withLocal(...)` 中的自动 `unref` 回归

其中 `jni_member_facade_nonvirtual` 当前专门覆盖：

- `CallNonvirtual*Method` 家族对应的 facade 分派
- `jobject.$nonvirtualMethod(...)` / `.$nonvirtualCall(...)`
- `jclass.$nonvirtualMethod(...)` / `.$nonvirtualCall(...)`
- nonvirtual 路径下 declaring class 暴露与 direct shortcut 回归

当前设备测试额外支持：

- 通过 `FRIDA_ANALYKIT_DEVICE_FRIDA_VERSION=<version>` 指定设备测试所使用的 Frida Python 环境；当前默认回落到 `16.6.6`
- `tests/device` 会优先解析本机 managed env 中与该版本匹配的 Python，可不要求当前 pytest 主进程本身就跑在对应 Frida 版本下
- 生成的 device test config 会自动写入 `server.version=<same version>`，确保 `frida-server` 与 Python 侧 Frida 版本保持一致

这意味着当前 CLI 不只是一个“跑脚本”的入口，它已经承担了：

- 运行期日志归档
- 二进制数据归档
- SSL keylog 持久化
- progress 事件输出

### 7. REPL / JsHandle / 远端对象访问

当前 Python 侧已经实现：

- `SyncJsHandle`
- `AsyncJsHandle`
- `scope_eval`
- `scope_call`
- `enumerate_obj_props`

当前这一层已经补充了 async 镜像：

- `script.eval_async(...)`
- `await async_handle.call_async(...)`
- `await async_handle.resolve_async()`

这套机制允许在 REPL 中通过 `script.eval(...)`、`script.jsh(...)` 等方式走同步句柄主线，并通过 `await script.eval_async(...)` 拿到 async handle 后继续执行 async 调用与取值。

当前还应明确区分两条能力面：

- `script.exports_sync` / `script.exports_async` 仍是公开脚本导出接口，保持近似 Frida 原生的透明返回值语义。
- RPC payload 归一化、`JsHandle` 参数序列化和协议握手只发生在 `SyncRPCClient` / `AsyncRPCClient` 内部链路，不应污染公共 exports 面。
- sync/async 不再共用同一把锁或同一份 handle/client cache，也不再对外暴露混合 facade。

当前需要特别记住的 breaking change：

- 句柄元信息不再使用 `.value` / `.type`。
- 当前元信息访问方式改为 `.value_` / `.type_`。
- `.value` / `.type` 现在重新表示真实 JS 属性，避免占用用户对象字段名。

当前内部实现还做了两点重要调整：

- Python <-> agent 之间传递句柄时，内部已经改为结构化 `HandleRef`，不再依赖旧的 slash-string + JSON monkeypatch 方案。
- `script.jsh("Process/foo/bar")` 这种入口字符串仍然保留，但只在入口做一次 split，后续链式访问都走结构化 ref。
- `script.eval("Process").getCurrentThreadId()` 这类 scope-backed 根句柄的一级方法调用，当前已要求 agent 侧显式绑定到 scope 根对象本身，避免把方法当未绑定函数调用。

这部分能力更偏高级调试/交互辅助，不一定要在对外 README 里大量展开，但在项目能力层面已经存在，后续整理 README 时不应忘记：

- v2 不只有“attach 一个脚本”
- 它还具备一套可交互的 Python <-> JS scope 操作能力

测试组织也已经按这套职责调整：

- RPC / session / REPL 相关 Python 单测当前集中到 `tests/rpc/`
- `tests/rpc/` 当前覆盖 message、exports、registry、resolver、JsHandle、session banner 和 async REPL 路径

### 8. frida-server 生命周期管理

当前 `server` 子命令包括：

- `frida-analykit server boot`
- `frida-analykit server stop`
- `frida-analykit server install`

当前行为要点：

- `server boot` 默认不会杀掉已存在的远端 `frida-server`。
- 如果发现已存在同名进程，会报错并提示使用 `server stop` 或 `server boot --force-restart`。
- `server boot --force-restart` 会先杀旧进程，再启动新进程。
- `server boot` 只会启动设备上当前已经存在的远端 binary，不会自动安装或切换成当前 Python Frida 对应版本。
- `server stop` 是幂等清理入口；即便当前没有匹配进程，也会返回成功并尝试移除 adb forward。
- `server boot` / `stop` / `install` 当前只支持 adb-backed 远端场景，也就是 `server.host` 为 `host:port` 形式的远端链路。
- `server boot` 内部会自动管理 adb forward。
- `server boot` 启动远端进程时会尝试 plain shell 和多种 root 方案。

### 9. frida-server 下载、ABI 识别与本地推送

`server install` 当前支持两种来源：

- 通过版本号从 GitHub 下载匹配资产
- 使用 `--local-server` 推送本地二进制或 `.xz` 资产

当前版本解析优先级：

1. `--version`
2. `config.server.version`
3. 当前 Python 环境中安装的 `frida` 版本

当前 ABI 检测能力：

- 会读取 Android 常见 ABI 属性
- 会回退到 `getprop`
- 会回退到 `uname -m`
- 会回退到 `/proc/cpuinfo`

当前 install 行为细节：

- 下载的 server 资产会缓存到本机缓存目录
- 本地 `.xz` 资产会自动解压
- install 完成后会验证远端 server 是否存在、可执行、版本是否匹配
- `doctor --config` 默认会输出带颜色的精简诊断摘要，直接标出版本错配、host 不可达、协议不兼容等红项；`--verbose` 才展开远端路径、原始 config、设备 ABI、profile 等低层细节
- `doctor fix --config` 会复用这份诊断，只修远端 `frida-server` 的安装 / 版本红项，不会自动 `server boot`

### 10. doctor / 兼容性判断

`frida-analykit doctor` 当前默认会输出面向行动的彩色摘要：

- 当前 Python Frida 版本与支持状态
- 当前目标设备，以及来源是 `config.server.device`、`ANDROID_SERIAL` 还是自动解析
- 当前目标 `frida-server` 版本，以及来源是 `config.server.version` 还是当前 Python Frida
- 远端已安装 `frida-server` 版本
- 关键红项，例如版本不一致、host 不可达、协议不兼容、binary 缺失/不可执行

若提供 `--verbose`，则会进一步展开：

- 当前配置文件路径
- 远端 server 路径
- 配置的 host/device/version
- install target version
- adb target device
- 设备 ABI
- 远端 server 是否存在
- 远端 server 是否可执行
- 远端 server 版本
- 远端 server 是否落在支持 profile 中

`doctor fix` 第一版只处理远端安装 / 版本类红项：

- 远端 binary 缺失
- 远端 binary 不可执行
- 远端版本与当前目标版本不一致

修复完成后会自动重跑诊断；如果剩余红项只是运行态问题，例如 host 不可达、server 未运行或协议仍不兼容，则会明确提示再执行 `server boot`。

`frida-analykit doctor device-compat` 会进一步对真机做最小兼容性探测：

- 支持 `--serial` / `--all-devices`
- 默认从 repo local + global managed env 中收集可用 Frida 版本
- 默认按“最新版 -> 最旧版 -> 最大间隙中点”采样，默认 `3` 次
- 如果显式传入 `--versions`，则按显式版本集完整执行，不再受默认采样轮数裁剪
- 默认会实时打印设备 / 版本 / 阶段进度；`--verbose` 会额外打印默认测试包探测细节
- 每个采样点只做最小链路：
  - 校验或安装对应版本的 `frida-server`
  - 启动远端 server
  - 注入一个最小 agent，并执行一次 `rpc.exports.ping()`
- 每台设备会先探测一次目标 app；优先级为 `--app` -> `config.app` -> 默认测试包 `com.frida_analykit.test`
- 输出会按设备分组，标出 sampled versions、success / fail / unavailable、失败阶段和观察到的兼容边界

### 11. 受管 Frida 开发环境

当前项目有两套环境管理入口：

- 仓库本地开发环境：`make env-*` 和 `scripts/env.py`
- 全局 CLI 环境：`frida-analykit env *`

这两套入口的目标并不完全相同：

- repo-local 环境偏向当前仓库开发，会安装仓库自身依赖，并在 repo 内部维护环境元数据。
- global CLI 环境偏向用户日常切换不同 Frida 版本，使用 `frida-analykit env ...` 管理。

当前 CLI 提供的环境命令：

- `env create`
- `env list`
- `env shell`
- `env remove`
- `env use`
- `env install-frida`

当前行为要点：

- 默认依赖 `uv`
- `env create` 默认会安装 REPL 额外依赖
- `env create --no-repl` 可关闭 REPL 额外依赖
- `env use` 只切换 current 环境，不会修改当前 shell
- `env shell` 会真正进入子 shell
- `env install-frida` 可以对指定 virtualenv Python 显式安装某个精确 Frida 版本

当前兼容 profile 也可直接用来创建环境，例如：

- `legacy-16`
- `current-17`

### 12. npm runtime agent 能力地图

当前 `@zsa233/frida-analykit-agent` 不应再理解为“只有一个 RPC shim 的小包”。从当前仓库代码来看，它已经形成了一套按 capability 拆分的 agent runtime，既包含基础 helper / process / RPC 支撑，也包含 JNI、Dex、ELF、SSL 和 native bindings 等逆向辅助能力。

#### 12.1 核心运行时 / Core Runtime

包根 `@zsa233/frida-analykit-agent` 当前保持瘦入口，只导出轻量基础能力：

- `Config`
- `LogLevel`
- `setGlobalProperties`
- `help`
- `NativePointerObject`
- `BatchSender`
- `ProgressNotify`
- `LoggerState`
- `FileHelper`
- `proc`

当前包根设计的重点不是“把所有东西都从 `.` 导出”，而是：

- 保留最轻、最常用、最稳定的基础能力
- 把较重 capability 留在显式 subpath
- 让 bundle 体积主要由用户自己的 import 面决定

#### 12.2 公共导入面 / Public Surface

当前正式公共导入面已经明确收口为：

- `@zsa233/frida-analykit-agent`
- `@zsa233/frida-analykit-agent/rpc`
- `@zsa233/frida-analykit-agent/config`
- `@zsa233/frida-analykit-agent/bridges`
- `@zsa233/frida-analykit-agent/helper`
- `@zsa233/frida-analykit-agent/process`
- `@zsa233/frida-analykit-agent/jni`
- `@zsa233/frida-analykit-agent/ssl`
- `@zsa233/frida-analykit-agent/elf`
- `@zsa233/frida-analykit-agent/elf/enhanced`
- `@zsa233/frida-analykit-agent/dex`
- `@zsa233/frida-analykit-agent/native/libart`
- `@zsa233/frida-analykit-agent/native/libssl`
- `@zsa233/frida-analykit-agent/native/libc`

需要特别记住：

- 当前 package `exports` 已不再保留 `./*` 通配子路径
- 深层内部文件与 `internal/*` 不再默认属于 public import surface
- `@zsa233/frida-analykit-agent/libssl` 这类旧入口已经退出主线公开形态，当前应使用 `@zsa233/frida-analykit-agent/native/libssl`

#### 12.3 Helper 门面 / Helper Facade

当前 helper 已经从“大静态类 / 大工具袋”收敛为分组 facade。主线接口现在是：

- `help.log.debug/info/warn/error`
- `help.progress.create(tag)`
- `help.fs.read/readText/write/open/save/getLogFile/joinPath/isFilePath`
- `help.proc.readMaps/readCmdline/getFdLink/getFileStreamLink`
- `help.mem.scan/withReadableRange/withReadablePages/backtrace/downAlign/upAlign/pageStart/pageEnd`
- `help.runtime.assert/send/setOutputDir/getOutputDir/getDataDir/androidApiLevel/newBatchSender`

当前仍保留的 flat alias 只包括：

- `help.$debug`
- `help.$info`
- `help.$warn`
- `help.$error`
- `help.assert`
- `help.$send`

这意味着后续 README 收束时，不应再把 helper 描述成“只有若干零散全局函数”，而应强调它现在是一层结构化 facade。

#### 12.4 RPC、REPL 与 HandleRef / RPC / REPL / HandleRef

`@zsa233/frida-analykit-agent/rpc` 当前只安装最小 RPC / REPL 基础能力：

- 它不再为了 eval context 自动 import `JNIEnv`、`SSLTools`、`ElfTools`、`Libart`、`Libssl`、`Libc`、`help`、`proc`
- capability 是否会进入 `_agent.js` 和 RPC eval context，取决于用户是否在自己的 `index.ts` 中显式 import 对应模块
- 这使得 `/rpc` 成为真正的最小副入口，而不是默认拖入整套 runtime 的大桶入口

当前 Python 侧 `script.eval(...)`、`script.jsh(...)`、REPL 句柄链路依赖的不是“魔法字符串协议”，而是一套结构化 RPC 能力面：

- `HandleRef`
- `scope_eval`
- `scope_call`
- `scope_get`
- `enumerate_obj_props`
- `rpcRuntimeInfo()` 协议预检

这里需要在后续 README 收束时保持一个边界感：

- `/rpc` 是最小交互能力面
- capability 模块是按需增强层
- eval context 的可见性取决于显式 import，而不是隐式全局全家桶

#### 12.5 JNI 能力与门面 / JNI / JNI Facade

`@zsa233/frida-analykit-agent/jni` 当前不只是 `JNIEnv` wrapper，还包括：

- `refs`
- `strings`
- `members`
- `signatures`
- `runtime_methods`
- `runtime_fields`

当前 JNI member facade 已经形成了“显式 `sig` 驱动的高层访问面”，主线特征包括：

- `sig` 必填，不做 name-only lookup，也不做 overload 猜测
- 默认返回 JNI wrapper，不自动转 JS primitive / JS string
- object-like 返回值可按 descriptor 收敛到已有 wrapper，例如 `jstring` / `jclass`
- accessor 提供 `withLocal(...)`，用于局部引用生命周期收口
- nonvirtual 路径已经有专门 slice，但仍要求显式传入 declaring class

当前已明确的接口能力包括：

- `jobject.$method(...)` / `.$call(...)`
- `jobject.$field(...)` / `.$getField(...)` / `.$setField(...)`
- `jobject.$nonvirtualMethod(...)` / `.$nonvirtualCall(...)`
- `jclass.$staticMethod(...)` / `.$staticCall(...)`
- `jclass.$constructor(...)` / `.$new(...)`
- `.$methodIdFor(...)` / `.$fieldIdFor(...)`

数组与字符串语义也已经被显式拆分：

- `jobjectArray` 与各类 primitive array wrapper 表示 JNI array ref，本身仍需要按 ref 生命周期管理
- `Get*ArrayElements()` 获取的是独立 raw buffer wrapper，不应与 array ref wrapper 混用
- primitive array ref 提供 `.$elements()` 与 `withElements(...)`
- `GetStringCritical` 回到 JNI 原型语义，必须显式 acquire / release；`jstring.toCriticalUTF16String()` 只是围绕这套语义做封装

当前仍需特别记住一个 breaking change：

- `.$method(name, sig)` 现在返回高层 accessor，而不再直接返回 low-level `jmethodID`
- 旧 lookup 语义已迁移到 `.$methodIdFor(name, sig)`

#### 12.6 Dex 能力 / Dex / DexTools

`@zsa233/frida-analykit-agent/dex` 当前公开的核心 capability 是 `DexTools`：

- `DexTools.enumerateClassLoaderDexFiles()`
- `DexTools.dumpAllDex({ tag?, dumpDir?, maxBatchBytes?, log? })`

当前行为边界：

- `enumerateClassLoaderDexFiles()` 返回 plain metadata，不再回退到旧版 Java wrapper 形态
- `dumpAllDex()` 在 RPC 模式下会走 `DEX_DUMP_BEGIN -> BATCH(DEX_DUMP_FILES) -> DEX_DUMP_END`
- 默认最大批量上限为 `8 MiB`
- 单个超大 dex 会单独成批发送，而不是继续切片
- Python 侧默认写入 `script.dextools.output_dir`，未配置时回退到 `agent.datadir/dextools`

当前 agent 侧还有专门的 type-tests 与 device suite 覆盖 DexTools 的类型面和真实流式落盘行为。

#### 12.7 ELF 能力 / ELF / ElfTools

`@zsa233/frida-analykit-agent/elf` 当前公开的正式入口是 `ElfTools`，当前已确认的主线能力包括：

- `ElfTools.findModuleByName(name, tryFix?)`
- `ElfTools.getModuleByName(name, tryFix?)`
- `ElfTools.loadFromModule(mod, tryFix?)`
- `ElfTools.createSymbolHooks(target, options?)`
- `ElfTools.snapshot(target, options?)`

其中核心 hook 对象已经统一命名为 `ElfSymbolHooks`，不再沿用旧版 `SymbolAttach` 命名。它当前的职责边界是：

- 管理模块级 symbol hook 状态
- 维护 lazy symbol registry
- 在可用时通过 `dlsym` 联动补全 deferred hook
- 提供显式签名 `attach(name, fn, retType, argTypes, options?)`

当前 `/elf/enhanced` 作为手动导入的 preset 增强层存在：

- `@zsa233/frida-analykit-agent/elf/enhanced`
- `castElfSymbolHooks(hooks)`

它只在用户显式 import 时才会进入 bundle，用于提供常见 libc / libdl / pthread / memory / file / android symbol hook preset，不会自动回流到 `/elf` 核心入口或 `globalThis`。

其背后的增强对象是 `ElfModuleX`。从当前 `src/elf/module.ts` 来看，它已经不仅是模块句柄包装，而是带有增强 ELF 解析能力的 module facade，当前至少覆盖：

- ELF header 解析
- program header 解析
- dynamic table 解析
- section header 读取与段查找
- symbol 扫描
- relocation / plt relocation 读取与链接
- `off2addr()` 这类地址映射辅助

当前还存在一个 fixer 扩展点：

- `ElfModuleFixer`
- `ElfFileFixer`

当前 ELF workflow 还补齐了结构化 RPC 链路：

- `ELF_SNAPSHOT_BEGIN`
- `ELF_SNAPSHOT_CHUNK`
- `ELF_SNAPSHOT_END`
- `ELF_SYMBOL_CALL_LOG`
- `BATCH(source=ELF_SNAPSHOT_CHUNKS)`

`snapshot()` 在 RPC 模式下会走上述消息链路；Python 侧默认产物布局是：

- `script.elftools.output_dir/snapshots/<tag-or-id>/`
- `script.elftools.output_dir/logs/<tag>.log`

这说明 README 后续收束时，应把 ELF 能力描述成“增强 ELF 模块分析、symbol hook 与流式 snapshot 辅助”，而不是只写成“能找模块名”的小工具。

#### 12.8 SSL 能力 / SSL / SSLTools / BoringSSL

`@zsa233/frida-analykit-agent/ssl` 当前公开的正式能力包括：

- `SSLTools`
- `BoringSSL`
- `SSLSecretCallbackConsumer`

从当前 `src/ssl/ssl.ts` 来看，这一侧已经至少形成两条工作流：

- `SSLTools.attachLibsslKeylogFunc(tag?)`
  通过 libssl 低层符号绑定挂接 keylog callback，把 `SSL_SECRET` 写回 RPC 或本地日志
- `SSLTools.attachBoringsslKeylogFunc({ mod?, libname? })`
  先定位目标模块，再借助 `BoringSSL.scanKeylogFunc()` 猜测并 attach BoringSSL 的 keylog 函数

其中 `BoringSSL.scanKeylogFunc()` 当前不是简单 symbol lookup，而是一套静态/启发式分析路径：

- 扫描 `CLIENT_RANDOM` 字符串特征
- 对字符串引用做 ADRL xref 扫描
- 从相关指令继续推断 BL 目标
- 再通过 verifier / thunk 判断做函数确认

因此这里的 README 能力描述应强调：

- 不只是“SSL keylog hook”
- 还包括对 BoringSSL keylog 相关函数的静态定位辅助

#### 12.9 原生绑定层 / Native Bindings

当前 `native/*` 家族的职责边界已经明确：

- `native/libart` 提供 `Libart` 这类 ART 低层符号绑定
- `native/libssl` 提供 `Libssl` 这类低层符号绑定
- `native/libc` 提供 `Libc` / `libc`

这三者与高层 capability 的关系应当这样理解：

- 高层 workflow 位于 `ssl`、`jni`、`dex`、`elf` 等 capability 模块
- `native/*` 是低层绑定层，供高层 capability 或用户脚本按需显式 import
- RPC eval context 只有在用户显式 import 对应模块后，才会看到这些低层绑定对象

#### 12.10 私有测试包 / Private Test-only Package

当前仓库里还有一个私有 package：

- `@zsa233/frida-analykit-agent-device-tests`
- `private: true`
- 主入口指向其自身的 `dist/index.js`
- 通过 `peerDependencies` 引用 `@zsa233/frida-analykit-agent`

它的定位不是正式 runtime capability，而是仓库内真机回归与 agent 单测桥接层。当前已知用途包括：

- 在临时 workspace 中安装私有测试导出
- 通过 `installAgentUnitRpcExports()` 暴露测试 RPC 入口
- 由 Python 侧 `tests/device` 调用 `listAgentUnitSuites()` / `runAgentUnitSuite(name)` 拉起 suite

当前至少包含这些 suite：

- `dex_tools`
- `helper_core`
- `helper_runtime`
- `jni_env_wrappers`
- `jni_member_facade`
- `jni_member_facade_arrays`
- `jni_member_facade_nonvirtual`

因此后续无论是根 README 还是 npm README，都不应把这个私有包误写成面向普通 npm 用户的正式能力。

### 13. npm runtime 打包约束

当前 `@zsa233/frida-analykit-agent` 的包发布特征：

- `type: module`
- 主入口为 `./dist/index.js`
- types 入口为 `./dist/index.d.ts`
- `./rpc` 也有独立 export
- 不再保留 `./*` 通配 export
- 发布时要求打包真实构建出的 `dist/**/*`

这一点很重要，因为它已经在历史版本中踩过坑：

- 曾出现过 npm 包缺少 `frida-compile` 所依赖 JS 产物的问题
- 当前测试已显式覆盖 prebuilt runtime export、显式导出边界和 build config 正确性

当前还新增了一个只给仓库内测试使用的私有 package：

- `@zsa233/frida-analykit-agent-device-tests`
- `private: true`
- 主入口同样指向 `dist/index.js`
- 依赖面只通过 `peerDependencies` 引用 `@zsa233/frida-analykit-agent`
- 用途是把 agent 内部单测逻辑独立打包给真机测试临时 workspace 使用，而不是让正式 runtime 依赖它

## 当前配置模型

当前 `config.toml` 顶层结构：

- `app`
- `jsfile`
- `server`
- `agent`
- `script`

### 字段说明

`app`

- 目标应用包名
- `spawn` 时必须提供
- `attach` 时可作为 PID 自动解析依据

`jsfile`

- 注入使用的 JS bundle 路径
- 在 TS 工作区模式下必须和 `npm run build/watch` 实际产物一致

`server.device`

- 可选
- 用于固定目标设备序列号
- 多设备场景下应优先填写
- 一旦填写，其优先级高于 `ANDROID_SERIAL`

`server.path`

- 远端设备上的 `frida-server` 路径
- 默认模板为 `/data/local/tmp/frida-server`

`server.host`

- 支持 `local`
- 支持 `usb`
- 支持 `host:port`

当前语义上：

- `local` 表示本地设备模式
- `usb` 表示 USB 设备模式
- `host:port` 表示远端 frida-server 连接地址，通常对应 adb forward 场景

`server.version`

- 可选
- 用于显式钉死 `frida-server` 版本
- 不填时默认跟随当前 Python `frida` 版本

`agent.datadir`

- Python 侧二进制数据落盘目录
- 用于保存未专门处理但携带 payload 的消息数据

`agent.stdout`

- agent stdout 输出目标

`agent.stderr`

- agent stderr 输出目标

`script.nettools.ssl_log_secret`

- SSL key log 的输出目录

`script.repl.globals`

- Python `--repl` 命名空间中的懒注入 JS seed handle 列表
- 当前仅支持裸全局名，例如 `Process`、`Java`
- 不支持 alias，也不支持 `Process/getCurrentThreadId` 这类深路径
- 若条目与内置 REPL 名字冲突，或不是合法 Python 标识符，会在进入 REPL 前直接报错

### 当前模板默认值

当前脚手架模板默认会生成：

```toml
jsfile = "_agent.js"

[server]
path = "/data/local/tmp/frida-server"
host = "127.0.0.1:27042"

[agent]
datadir = "./data/"
stdout = "./logs/outerr.log"
stderr = "./logs/outerr.log"

[script.nettools]
ssl_log_secret = "./data/nettools/sslkey/"

[script.repl]
globals = ["Process", "Module", "Memory", "Java", "ObjC", "Swift"]
```

兼容说明：

- 主线配置文件名为 `config.toml`。
- CLI 默认优先查找 `config.toml`，缺失时才回退到 `config.yml` / `config.yaml`。
- `server.path` 是当前主字段；旧的 `server.servername` 仅保留输入兼容。

## 当前兼容性与依赖约束

### Python / Frida 约束

- Python 要求：`>=3.11`
- Frida 直接依赖范围：`frida>=16.5.9,<18`

这是当前支持范围的真源，不应在 README 维护中手工发明另一套口径。

### 当前兼容 profile

| profile | series | tested_version | range |
|:--|:--|:--|:--|
| `legacy-16` | `16.6.x` | `16.5.9` | `>=16.5.9, <17.0.0` |
| `current-17` | `17.x` | `17.8.2` | `>=17.0.0, <18.0.0` |

这些 profile 只用于环境说明、doctor 输出和测试覆盖口径；当前 async RPC 路径不会再按 profile 直接决定 native async 还是 shim async，而是按运行时 script/export 的实际能力探测来选择。

`doctor` 当前会把环境标成三类：

- `tested`
- `supported but untested`
- `unsupported`

### 其他工具依赖

- `uv`：受管环境创建与安装依赖时需要
- `npm`：TS 工作区构建、watch 和 runtime 打包时需要
- `adb`：远端 `frida-server` 管理时需要
- `ptpython`：REPL 能力依赖可选 extra `repl`

## 当前安装与分发模型

### Python CLI

当前定位：

- 不发布到 PyPI
- 通过 GitHub 仓库 / GitHub Release 分发

README 当前主线示例应展示通过 `stable` 稳定入口安装，例如：

```sh
uv tool install "git+https://github.com/ZSA233/frida-analykit@stable"
```

这里的 `stable` 分支固定指向“最新 stable GitHub Release 对应代码”，不再要求每次发版都把 README 安装示例改写成某个具体 `vX.Y.Z`。

### npm runtime

- 发布到 npmjs
- 包名为 `@zsa233/frida-analykit-agent`
- 与 Python CLI 共用同一版本号体系

### release 产物模型

每个 release tag 当前应产出：

- 1 个 Python `sdist`
- 1 个 Python wheel
- 1 个 npm tarball

历史上的多 wheel release 资产保留为历史遗留产物，但当前分发模型已经不再继续维护那套多 wheel 方案。

## 当前推荐使用方式

### 方式 A：标准用户流程

这是当前更常见、也更符合 v2 设计目标的使用方式。

推荐顺序：

```sh
# 1. 创建并进入匹配版本的 Frida 虚拟环境
frida-analykit env create --frida-version 17.8.2 --name frida-17.8.2
frida-analykit env shell frida-17.8.2

# 2. 生成工作区并安装 TS 依赖
frida-analykit gen dev --work-dir ./my-agent
cd ./my-agent
npm install

# 3. 检查当前环境与设备状态
frida-analykit doctor --config ./config.toml

# 4. 如有需要，先修复远端 frida-server 的安装 / 版本红项
frida-analykit doctor fix --config ./config.toml

# 5. 如仍需要，也可显式安装匹配的 frida-server 到 config.server.path
frida-analykit server install --config ./config.toml

# 6. 一个终端启动远端 frida-server
frida-analykit server boot --config ./config.toml

# 7. 另一个终端注入脚本
frida-analykit attach --config ./config.toml --build --repl
# 或
frida-analykit spawn --config ./config.toml --build
```

补充说明：

- 如果只想先编译，再手动决定什么时候注入，可以先单独执行 `frida-analykit build --config ./config.toml`。
- 如果 `_agent.js` 已经是最新的，则 `attach` / `spawn` 不一定非要加 `--build`。
- `server install` 默认会根据当前 Python 环境里的 `frida` 版本、`config.server.version` 和显式 `--version` 来决定安装版本。
- `server install` 的远端落地路径由 `config.server.path` 控制。
- `server boot` 不会自动安装或切换版本；如果 `doctor` 标红远端版本错配，应先执行 `doctor fix` 或 `server install`。

### 方式 B：直接使用现成 JS bundle

适合：

- 已有 `_agent.js`
- 只需要 CLI 负责 attach/spawn、日志和 server 管理

典型命令：

```sh
frida-analykit server boot --config config.toml
frida-analykit doctor --config config.toml
frida-analykit attach --config config.toml --pid 12345
frida-analykit spawn --config config.toml
```

## 当前测试与验证面

### 单元与集成测试

当前测试已经覆盖的主要方向包括：

- CLI 命令分发和参数行为
- config 路径解析
- frontend build/watch 行为
- dev env 管理
- compat / doctor 输出
- server boot/stop/install/ABI 检测
- scaffold 输出
- session banner 与 bootstrap 注入
- RPC payload / batch / 默认 handler
- release version 与 release contract

### smoke test

当前存在本地 smoke attach 测试：

- 需要 `FRIDA_ANALYKIT_ENABLE_SMOKE=1`
- 仅在本机支持 local Frida attach 的环境下运行

### Android 真机测试

当前存在一组自包含的 Android 设备测试，覆盖：

- 设备预检
- `frida-server` 生命周期
- 注入后写入 marker
- `server install --version`
- `server install --local-server`

运行前需要的环境变量主要包括：

- `FRIDA_ANALYKIT_ENABLE_DEVICE=1`
- 可选 `FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS=1`
- 可选 `ANDROID_SERIAL=<serial>`
- 可选 `FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path>`
- 默认测试包 `com.frida_analykit.test` 已安装到设备，或显式设置 `FRIDA_ANALYKIT_DEVICE_APP=<package>`

当前行为补充：

- 默认仍会运行依赖 app 的真机用例
- 如果未设置 `FRIDA_ANALYKIT_DEVICE_APP`，测试与 `doctor device-compat` 会直接使用默认测试包 `com.frida_analykit.test`
- 默认测试包来自仓库内置最小 Android 工程 `tests/android_test_app/`
- 真机测试与 `doctor` 都不会自动 build/install；若默认包缺失，会快速失败并提示先执行安装命令
- 对应版本的 GitHub Release / prerelease 会额外发布 `frida-analykit-device-test-app-vX.Y.Z[-rc.N].apk`，用户可以直接下载后 `adb install -r`
- 该 APK 使用仓库内固定测试签名，只用于 `com.frida_analykit.test` 真机回归，不用于生产发布
- 显式设置 `FRIDA_ANALYKIT_DEVICE_APP` 或 `doctor device-compat --app` 时，只验证该包是否存在、能启动、可 attach，不再做系统候选扫描
- 真机测试默认会在同一台设备的整个 pytest session 内复用同一个 `frida-server` runtime，不再让大多数用例按用例反复 stop / reboot
- 如果只想快速验证不依赖 app 的链路，可设置 `FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS=1`
- 多台设备同时在线时，普通 `make device-test*` 需要显式设置 `ANDROID_SERIAL=<serial>`；若想一次并行跑所有已连接设备，可使用 `make device-test-all`
- `Makefile` 还额外提供：
  - `DEVICE_TEST_APP`
  - `DEVICE_TEST_SKIP_APP`
  - `DEVICE_TEST_SERIALS=serial1,serial2,...`
  - `device-test-app-build`
  - `device-test-app-install`
  - `device-test-app-install-all`

这说明当前项目已经不只是“理论上支持 Android 真机链路”，而是已经有针对核心链路的自动化真机验证。

## 当前 release 与版本治理能力

当前 release 治理已经比较成体系，关键点如下：

- 版本真源在 `release-version.toml`
- 版本切换统一通过 `scripts/release_version.py` 和 `Makefile`
- 不鼓励手改 `_version.py`、两个 `package.json`、`package-lock.json`
- stable / RC 的 tag、Python 版本、npm 版本之间存在严格映射关系
- release 资产现在固定包含 `sdist`、wheel、npm tarball 和默认真机测试 APK
- release-preflight 会执行配置验证、release version 校验、promotion 校验、测试与 agent build

当前 Makefile 关键命令包括：

- `make release-version-show`
- `make release-version-rc BASE_VERSION=X.Y.Z RC=N CHECK=1`
- `make release-version-stable BASE_VERSION=X.Y.Z CHECK=1 RC_TAG=vX.Y.Z-rc.N`
- `make release-preflight RELEASE_TAG=vX.Y.Z[-rc.N]`
- `make release-local RELEASE_TAG=vX.Y.Z[-rc.N]`
- `make release-install-check RELEASE_TAG=vX.Y.Z[-rc.N]`

当前 release contract 的关键约束包括：

- `pyproject.toml` 中只能有一条规范直接依赖 `frida>=...,<...`
- 受测 profile 必须落在声明支持范围内
- stable 从 RC 提升时，只允许版本元数据文件发生差异

## 当前仓库结构理解

```text
src/frida_analykit/                Python CLI、会话编排、server 管理、dev env、compat、RPC
packages/frida-analykit-agent/     npm runtime 与 TS helper
src/frida_analykit/resources/      compat profiles 与脚手架模板
scripts/                           release/env 相关脚本
tests/                             Python tests
tests/device/                      Android device tests
docs/                              release 相关文档
.github/workflows/                 CI 与 release 工作流
```

## 历史沿革与迁移理解

### v1 -> v2 迁移主轴

当前可以明确确认的迁移关系：

| v1 | v2 |
|:--|:--|
| `python frida-analykit/main.py ...` | `frida-analykit ...` |
| `python frida-analykit/gen.py dev` | `frida-analykit gen dev` |
| `ptpython_spawn.sh` / `ptpython_attach.sh` | `--repl` |
| repo 相对导入 `./frida-analykit/script/...` | npm 包 `@zsa233/frida-analykit-agent` |
| `requirements.txt` | `pyproject.toml` + `uv.lock` |

## 当前文档差异与下次 README 收束提醒

这些内容不一定都应该直接进入对外 `README.md`，但必须在收束时被重新检查：

- `README.md` / `README_EN.md` 的稳定安装示例应固定使用 `git+https://github.com/ZSA233/frida-analykit@stable`。
- `README.md` 已覆盖主线能力，但对 `watch` 独立命令、RPC/REPL 深层能力、repo-local env 与 global env 的区别仍可继续优化。
- `packages/frida-analykit-agent/README*.md` 与包 `homepage` 这类用户向 GitHub 文档链接应固定指向 `blob/stable/...`，不要跟随 `main` 漂移。
- `README.md` 面向对外说明时，应保持主线清晰；但在收束时不要遗漏：
  - v2 的双产物定位
  - TS 工作区是主线开发模式
  - server 管理能力
  - env 管理能力
  - compat / doctor 能力
  - release 分发模型已改为单 sdist / 单 wheel / 单 npm tgz

## 后续维护要求

从现在开始，以下变化都应同步更新本文件：

- 新增或删除 CLI 子命令
- 新增或删除重要 flag
- `config.toml` / legacy YAML 字段变化
- runtime export 变化
- 兼容范围变化
- tested profile 变化
- release 产物模型变化
- v2 主线工作流变化
- README 与真实实现之间出现新的明显偏差

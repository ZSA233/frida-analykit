# PRE_README

## 文档定位

本文件是 `README.md` 的实时维护中间文档，也是后续 release 前统一收束 README 的事实基线。

与 `README.md` 的区别：

- `PRE_README.MD` 偏工作文档，要求更完整、更细、更贴近当前仓库真实状态。
- `README.md` 偏对外文档，要求更稳定、更精炼、更强调主线叙述。
- 只要用户可见能力、配置、命令行、接入方式、限制条件发生变化，应先更新本文件。
- release 前收束 `README.md` 时，应基于本文件整体整理，而不是仅把最近一次改动直接拼接进 README。

本文件的初始化快照基于当前仓库状态整理，快照时间为 `2026-03-28`。

## 当前仓库快照

### 分支与版本状态

- 当前工作分支：`release/v2.0.3`
- 当前版本真源：`release-version.toml`
- 当前声明发布版本：`2.0.2`
- 当前声明发布通道：`stable`
- 当前 Python 包版本：`src/frida_analykit/_version.py` 中为 `2.0.2`
- 当前根 `package.json` 版本：`2.0.2`
- 当前 npm runtime 包 `@zsa233/frida-analykit-agent` 版本：`2.0.2`

需要特别记录的一点：

- 分支名已经进入 `release/v2.0.3`，但版本真源仍然是 `2.0.2 stable`。
- 这意味着仓库 HEAD 已经包含了 post-`v2.0.2` 的持续变更，但正式版本号尚未切换到 `2.0.3`。
- 后续如果要进行 release 收束，需要先确认届时究竟是发布 `v2.0.3`，还是继续在 `2.0.2` 线上做文档修订。

### 当前已存在的 v2 tag

- `v2.0.0`
- `v2.0.0-rc.1`
- `v2.0.0-rc.2`
- `v2.0.0-rc.3`
- `v2.0.0-rc.4`
- `v2.0.1`
- `v2.0.1-rc.1`
- `v2.0.2`
- `v2.0.2-rc.1`

## 项目定义

`frida-analykit` v2 是一个双产物 monorepo：

- Python CLI：负责 `frida-server` 生命周期管理、设备连接、日志与二进制数据落盘、attach/spawn、REPL、脚手架生成、兼容性检查和开发环境管理。
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
5. 根据目标应用、设备和输出路径，补全或调整 `config.yml`。
6. 先执行 `frida-analykit doctor --config ./config.yml`，确认当前 Python Frida、compat 状态、设备连接和远端 `frida-server` 状态。
7. 如果设备上还没有合适的 `frida-server`，则执行 `frida-analykit server install --config ./config.yml`。
8. 如需显式指定版本，可通过 `config.server.version` 或 `frida-analykit server install --config ./config.yml --version <version>` 控制；安装目标路径由 `config.server.servername` 决定。
9. 在一个终端中执行 `frida-analykit server boot --config ./config.yml` 启动远端 `frida-server`。
10. 在另一个终端中执行 `frida-analykit spawn --config ./config.yml` 或 `frida-analykit attach --config ./config.yml` 完成注入。
11. 如果 `index.ts` 还未编译成 `_agent.js`，则应先执行 `frida-analykit build --config ./config.yml`，或者在运行时命令中加 `--build` 让 CLI 先构建后注入。

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

### 2. 生成自定义 TypeScript agent 工作区

命令：

```sh
frida-analykit gen dev --work-dir ./my-agent
```

当前脚手架会生成：

- `README.md`
- `config.yml`
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

- 默认从 `config.yml` 所在目录推断 TS 工作区根目录。
- 也可以通过 `--project-dir` 覆盖工作区目录。
- `--install` 会在工作区缺失 `node_modules` 时自动执行 `npm install`。
- `build` 会执行 `npm run build`。
- `watch` 会执行 `npm run watch`，并等待首个成功产物生成。
- `config.jsfile` 必须与 npm 构建产物路径一致，否则 CLI 会报错。
- `attach --watch` / `spawn --watch` 的语义是“等首个 bundle 生成后再注入”，不是对已经加载的 session 做自动热重载。

### 4. attach / spawn / REPL

当前运行时注入命令包括：

- `frida-analykit spawn --config config.yml`
- `frida-analykit attach --config config.yml`

当前行为特征：

- `spawn` 要求 `config.app` 必填。
- `attach` 可以显式传 `--pid`。
- 如果 `attach` 未传 `--pid`，且 `config.app` 存在，则会尝试通过应用标识自动解析 PID。
- `--repl` 会进入 `ptpython` REPL。
- REPL 中会注入 `config`、`device`、`pid`、`session`、`script` 等对象。
- `--repl` 当前已经切到 async ptpython 模式，允许在会话内直接 `await script.eval_async(...)`、`await handle.call_async(...)`、`await handle.resolve_async()`。
- `script.eval(...)` / `script.eval_async(...)` 当前会优先把输入当作“表达式”求值，因此像 `Process.arch`、`Promise.resolve(Process.arch)` 这类 REPL 常见写法会直接返回表达式结果；如果输入本身是多语句 body，则会回退到原始函数体执行方式。
- REPL 句柄与 scope 相关调用在首次使用前会先做一次 agent runtime 协议握手。
- 如果加载到设备上的 `_agent.js` 仍是旧 bundle，Python 侧会直接抛出 `RPC runtime mismatch`，提示用户重新用当前仓库打包本地 runtime 并 rebuild `_agent.js`，而不是再把底层 Frida `TypeError: value is not iterable` 直接暴露给用户。
- 如果未开启 `--repl`，CLI 默认保持会话存活，适合持续收集日志和数据。

当前实现里还有一个隐藏参数 `--detach-on-load`，主要用于 smoke/device 测试验证“脚本成功加载后立即退出”，不应作为 README 主线公开能力来强调，但应记得它存在。

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

- `SessionWrapper` / `ScriptWrapper`：负责会话装配、脚本加载、banner 与 logger 接线。
- `RPCClient`：负责 sync/async exports 包装、scope 调用、取值和句柄释放。
- `HandleRef` / `JsHandle`：负责 REPL 句柄、链式引用和惰性取值。

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

- `jni_env_wrappers`
- `jni_member_facade`
- `jni_member_facade_arrays`
- `jni_member_facade_nonvirtual`

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
- 生成的 device test `config.yml` 会自动写入 `server.version=<same version>`，确保 `frida-server` 与 Python 侧 Frida 版本保持一致

这意味着当前 CLI 不只是一个“跑脚本”的入口，它已经承担了：

- 运行期日志归档
- 二进制数据归档
- SSL keylog 持久化
- progress 事件输出

### 7. REPL / JsHandle / 远端对象访问

当前 Python 侧已经实现：

- `JsHandle`
- `scope_eval`
- `scope_call`
- `enumerate_obj_props`

当前这一层已经补充了 async 镜像：

- `script.eval_async(...)`
- `await handle.call_async(...)`
- `await handle.resolve_async()`

这套机制允许在 REPL 中通过 `script.eval(...)`、`script.jsh(...)` 等方式对 JS 侧对象进行句柄化访问和延迟取值。

当前还应明确区分两条能力面：

- `script.exports_sync` / `script.exports_async` 仍是公开脚本导出接口，保持近似 Frida 原生的透明返回值语义。
- RPC payload 归一化、`JsHandle` 参数序列化和协议握手只发生在 `RPCClient` 内部链路，不应污染公共 exports 面。

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
- `doctor --config` 会输出远端 server 路径、选中版本、设备 ABI、是否存在、是否可执行、已安装版本、匹配 profile 等信息

### 10. doctor / 兼容性判断

`frida-analykit doctor` 当前已经不只是打印本地 Frida 版本，而是会同时输出：

- 已安装 Frida 版本
- support status
- support range
- matched profile
- tested version in profile
- 所有测试 profile

若提供 `--config` 且配置存在，还会进一步检查：

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

### 11. 受管 Frida 开发环境

当前项目有两套环境管理入口：

- 仓库本地开发环境：`make dev-env-*` 和 `scripts/dev_env.py`
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

### 12. npm runtime 已暴露的能力面

`@zsa233/frida-analykit-agent` 当前已经导出：

- `Java`
- `ObjC`
- `Swift`
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
- `JNIEnv`
- `SSLTools`
- `ElfTools`
- `Libssl`

当前 runtime 的定位不是“只有一个 rpc shim”，而是已经开始积累逆向辅助能力，尤其包括：

- Android / JNI 相关 helper
- process/maps helper
- SSL/BoringSSL 相关 helper
- ELF 解析与辅助工具
- RPC 作用域调用支持

当前 `JNIEnv` 之上已经有一层 JNI member facade，当前已完成第一阶段基础访问面与第二阶段 nonvirtual slice，定位是“显式 `sig` 驱动的高层访问面”，主要特征如下：

- `jobject` 支持：
- `.$method(name, sig)` / `.$call(name, sig, ...args)`
- `.$nonvirtualMethod(clazz, name, sig)` / `.$nonvirtualCall(clazz, name, sig, ...args)`
- `.$field(name, sig)` / `.$getField(name, sig)` / `.$setField(name, sig, value)`
- `.$methodIdFor(name, sig)` / `.$fieldIdFor(name, sig)`
- `jclass` 支持：
- `.$method(name, sig)` / `.$call(target, name, sig, ...args)` 用于 unbound instance member
- `.$nonvirtualMethod(name, sig)` / `.$nonvirtualCall(target, name, sig, ...args)` 用于 unbound nonvirtual instance member
- `.$staticMethod(name, sig)` / `.$staticCall(name, sig, ...args)`
- `.$field(name, sig)` / `.$getField(target, name, sig)` / `.$setField(target, name, sig, value)`
- `.$staticField(name, sig)` / `.$getStaticField(name, sig)` / `.$setStaticField(name, sig, value)`
- `.$constructor(sig)` / `.$new(sig, ...args)`
- `.$methodIdFor(name, sig)` / `.$staticMethodIdFor(name, sig)`
- `.$fieldIdFor(name, sig)` / `.$staticFieldIdFor(name, sig)`

当前这一层的明确约束：

- `sig` 必填，不做 name-only lookup，也不做 overload 猜测
- 默认返回 JNI wrapper，不自动转 JS primitive / JS string
- object-like 返回值可按 descriptor 收敛到已有 wrapper，例如 `jstring` / `jclass`
- 默认仍由调用方手动管理对象生命周期
- accessor 额外提供 `withLocal(...)`，用于在 callback 作用域内消费局部引用并自动 `unref`
- nonvirtual facade 仍要求显式传入 declaring class，不做继承链自动推断
- unbound method accessor 必须显式传入 target，例如 `clazz.$method(...).call(obj)` 与 `clazz.$method(...).withLocal(obj, use, ...args)`
- unbound field accessor 必须显式传入 target，例如 `clazz.$field(...).get(obj)` / `set(obj, value)` / `withLocal(obj, use)`
- bound instance accessor 不接受额外 target；`obj.$method(...).withLocal(obj, use)`、`obj.$field(...).get(obj)` 这类写法都是无效调用
- bound static field accessor 不接受额外 clazz；`clazz.$staticField(...).get(clazz)` / `set(clazz, value)` 这类写法也是无效调用

当前正确写法示例：

```ts
const xField = pointClass.$field("x", "I");
const before = xField.get(point).toInt();
xField.set(point, 1);
const after = pointClass.$getField(point, "x", "I").toInt();
```

- 如果调用方绕过了 TypeScript 类型系统，例如使用 `as any` 或纯 JS 入口，runtime guard 仍会保留并直接抛错

当前 JNI wrapper 的数组语义已经明确拆分：

- `jobjectArray` 与 `jbooleanArray` ... `jdoubleArray` 统一表示 JNI array ref，本身仍然是 local/global ref，需要按 ref 生命周期管理
- `Get*ArrayElements()` 返回的则是独立 raw buffer wrapper，例如 `jintArrayElements` / `jcharArrayElements`
- primitive array ref 提供 `.$elements()` 与 `withElements(use, mode = 0)`，负责 acquire/release `Get*ArrayElements()` 缓冲区
- 这两层不能复用同一个 wrapper；否则 array-returning facade 会既泄露 local ref，又把 ref handle 误当 element buffer

当前 `GetStringCritical` 也已回到 JNI 原型语义：

- `JNIEnv.GetStringCritical(javaString)` 返回 `NativePointer`
- 必须配对 `JNIEnv.ReleaseStringCritical(javaString, chars)`
- `jstring.toCriticalUTF16String()` 提供了和现有 UTF-16 helper 一致的 acquire/read/release 封装
- 这里不再直接返回 JS string，因为 critical 区间里 VM 可能 pin 住字符串或阻塞 GC，必须尽快 release

当前需要特别注意一个 breaking change：

- `.$method(name, sig)` 不再返回 low-level `jmethodID`
- 旧 lookup 语义已经迁移到 `.$methodIdFor(name, sig)`
- `.$methodID(existingId)` 仍然保留“把已有 `jmethodID` 反射成 `java.lang.reflect.Method` 对象”的旧语义，不受这次 facade 演进影响

当前应特别注意对外边界已经收口：

- 正式 public entry 只保留包根 `@zsa233/frida-analykit-agent`
- 以及副入口 `@zsa233/frida-analykit-agent/rpc`
- 不再通过 `./*` 通配子路径默认暴露内部实现文件
- 这意味着内部 `jni/*`、`elf/*`、`net/*` 等文件形态可以继续重构，但不再承诺作为公开导入面兼容

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

当前 `config.yml` 顶层结构：

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

`server.servername`

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

### 当前模板默认值

当前脚手架模板默认会生成：

```yml
app:
jsfile: _agent.js

server:
  servername: /data/local/tmp/frida-server
  host: 127.0.0.1:27042
  device:
  version:

agent:
  datadir: ./data/
  stdout: ./logs/outerr.log
  stderr: ./logs/outerr.log

script:
  nettools:
    ssl_log_secret: ./data/nettools/sslkey/
```

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

README 当前示例仍然展示通过 git tag 安装，例如：

```sh
uv tool install "git+https://github.com/ZSA233/frida-analykit@v2.0.0"
```

但这条示例当前存在文档漂移问题：

- 仓库版本真源已经是 `2.0.2`
- README 安装示例仍停留在 `v2.0.0`

这应当被记录为后续 README 收束时必须处理的事项。

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
frida-analykit doctor --config ./config.yml

# 4. 如有需要，安装匹配的 frida-server 到 config.server.servername
frida-analykit server install --config ./config.yml

# 5. 一个终端启动远端 frida-server
frida-analykit server boot --config ./config.yml

# 6. 另一个终端注入脚本
frida-analykit attach --config ./config.yml --build --repl
# 或
frida-analykit spawn --config ./config.yml --build
```

补充说明：

- 如果只想先编译，再手动决定什么时候注入，可以先单独执行 `frida-analykit build --config ./config.yml`。
- 如果 `_agent.js` 已经是最新的，则 `attach` / `spawn` 不一定非要加 `--build`。
- `server install` 默认会根据当前 Python 环境里的 `frida` 版本、`config.server.version` 和显式 `--version` 来决定安装版本。
- `server install` 的远端落地路径由 `config.server.servername` 控制。

### 方式 B：直接使用现成 JS bundle

适合：

- 已有 `_agent.js`
- 只需要 CLI 负责 attach/spawn、日志和 server 管理

典型命令：

```sh
frida-analykit server boot --config config.yml
frida-analykit doctor --config config.yml
frida-analykit attach --config config.yml --pid 12345
frida-analykit spawn --config config.yml
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
- `FRIDA_ANALYKIT_DEVICE_APP=<package>`
- 可选 `ANDROID_SERIAL=<serial>`
- 可选 `FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path>`

这说明当前项目已经不只是“理论上支持 Android 真机链路”，而是已经有针对核心链路的自动化真机验证。

## 当前 release 与版本治理能力

当前 release 治理已经比较成体系，关键点如下：

- 版本真源在 `release-version.toml`
- 版本切换统一通过 `scripts/release_version.py` 和 `Makefile`
- 不鼓励手改 `_version.py`、两个 `package.json`、`package-lock.json`
- stable / RC 的 tag、Python 版本、npm 版本之间存在严格映射关系
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
scripts/                           release/dev-env 相关脚本
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

### v2 版本演进摘要

以下摘要来自当前 git tag 与提交历史，可作为未来 README 收束时的版本演化参考。

`v2.0.0`

- v2 的破坏性重构起点
- 切换为 Python CLI + npm agent monorepo
- 引入新的 release 基建
- 引入远端 `frida-server` 管理能力
- 引入受管 Frida 开发环境
- 确立新的 README / release-process / 双产物结构

`v2.0.1`

- 修复 AOSP 下 `doctor` 与 server 安装兼容性问题
- 修复 npm runtime 打包时缺失 JS 产物的问题
- 修复 smoke / CI 相关问题

`v2.0.2`

- 增加 CLI 顶层 `--version`
- 修复远端 runtime boot flow
- 修复 env version reporting

当前 HEAD（未正式切换版本真源）

- 包含 npmjs 发布工作流修复
- 包含 `AGENTS.MD` 与 AI agent 约束文档初稿
- 说明仓库已经进入下一轮 release 准备 / 持续演进阶段

上面最后一点是基于当前分支与提交状态的推断：

- 当前分支名为 `release/v2.0.3`
- 但版本真源仍是 `2.0.2`

## 当前文档差异与下次 README 收束提醒

这些内容不一定都应该直接进入对外 `README.md`，但必须在收束时被重新检查：

- `README.md` 当前安装示例仍然写的是 `v2.0.0`，与当前版本真源 `2.0.2` 不一致。
- `README.md` 已覆盖主线能力，但对 `watch` 独立命令、RPC/REPL 深层能力、repo-local env 与 global env 的区别仍可继续优化。
- 当前仓库 HEAD 处于 `release/v2.0.3` 分支，但版本真源尚未切换，这会影响后续 release 文案该写成“当前 stable”还是“下一版准备中”。
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
- `config.yml` 字段变化
- runtime export 变化
- 兼容范围变化
- tested profile 变化
- release 产物模型变化
- v2 主线工作流变化
- README 与真实实现之间出现新的明显偏差

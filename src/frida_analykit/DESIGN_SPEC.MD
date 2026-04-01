# frida-analykit Python 设计规范 / DESIGN_SPEC

## 适用范围与关系 / Scope / Relation

- 本文件只约束 `src/frida_analykit/` 及其直接对应的 Python 测试组织方式。
- 本文件是子系统规范，用于补充根目录 `AGENTS.MD`，不是替代它。
- 若本文件与 `AGENTS.MD` 存在张力，以 `AGENTS.MD` 作为公共底线；本文件只负责把 Python 侧当前已经形成的风格写清楚。
- 本文件的目标是总结当前仓库里已经存在的设计方式，便于后续 AI agent 在新增、重构和修复时延续同一套结构，而不是重新发明另一种架构。

## 架构风格 / Architecture

- Python 侧主线是“薄入口 + 显式 runtime/context + 按职责拆开的 wrapper / manager / client 组合”。
- 入口模块应尽量薄，只负责参数接线、对象装配、生命周期编排和对外暴露，不承载大量细节逻辑。
- 跨步骤共享状态时，优先使用显式 runtime/context 对象，而不是把依赖散落在宿主对象私有字段里。
- 当前仓库已经形成的风格包括：
  - `SessionRuntime` / `ScriptRuntime`
  - `ServerRuntime`
  - `DeviceServerRuntime`
  - `SessionWrapper` / `ScriptWrapper`
  - `RPCClient`
  - `DebugSessionManager`
- 组件边界应尽量清楚：
  - wrapper 负责对外易用接口和生命周期装配
  - runtime/context 负责显式持有依赖
  - client / resolver / handler 负责具体协议与行为
- 不要默认使用隐式 mixin 契约，不要让一个类依赖“宿主碰巧有这个字段/方法”才能成立。
- 如果某项兼容性处理、协议握手或错误恢复较复杂，应把它收敛到专门组件里，而不是散在多个 CLI 或 wrapper 入口里。

## 类型约束 / Typing

- Python 侧类型信息是第一优先级的维护项之一；参数、返回值、字段和属性应尽量完整标注。
- 结构固定的数据应优先使用：
  - `dataclass(slots=True)`
  - `pydantic` model
  - 明确的类型别名或窄集合类型
- 注入式依赖必须带清晰类型；如果要抽象依赖面，优先在使用侧定义小而明确的 `Protocol`。
- 不要把模块对象、回调、subprocess 句柄、`urlopen`、Frida 运行时等依赖塞进无类型字段。
- 如果底层返回值天然动态，应该尽快在边界处收窄类型，再向上游暴露更稳定的接口。
- 不要用大面积 `Any`、裸 `dict` 或不透明对象把真实协议边界糊掉；必要时可以先给出窄近似类型，再用注释说明限制。

## 模块组织 / Module Organization

- Python 模块按职责边界组织，主线语义包括：
  - `cli`
  - `config`
  - `env`
  - `device`
  - `development`
  - `session`
  - `rpc`
  - `server`
  - `repl`
  - `mcp`
  - `logging`
- 域内复杂逻辑应继续在域内细分，而不是回流到包根或入口文件。
- 例如 `rpc` 侧已经按 `client / protocol / message / resolver / registry / handler / exports` 拆开；后续新增能力也应沿这种域内分层继续扩展。
- `env` 域只负责多 Frida Python 环境管理，例如 managed env 创建、删除、选择、进入 shell、registry 和 render；compat profile 不再属于 `env`。
- `device` 域只负责设备选择、adb/host 派生、app 探测、workspace、remote server runtime 和测试 APK 工具，不再持有 managed env 解析或跨版本兼容扫描编排。
- 同时依赖 `env + device` 的编排逻辑，应收敛到 `development` 域，例如 compat profiles、managed env 选择、`doctor device-compat` 和真机测试上下文。
- `tests/device/conftest.py` 只能做真机回归 fixture glue，不再拥有设备管理或环境管理业务逻辑。
- adb 目标解析属于共享基础语义；`device`、`server`、`doctor` 和 CLI 入口不能各自复制一套“选哪台设备”的逻辑。
- `device` 域内若职责继续增长，应优先拆成显式 owner 模块，例如 `defaults / models / selection / helpers / runtime / test_app`；不要再回流到单个大文件。
- `development` 域内也应保持薄入口，优先拆成 `profiles / managed_envs / device_testing / device_compat` 这类显式 owner，而不是把交叉逻辑重新堆回包根。
- 包根 `__init__`、CLI 根入口和对外 convenience 模块不应承担内部中转层职责。
- `mcp` 域负责 stdio MCP server、长会话 manager、tool/resource schema 和会话资源回收；它不应复用会向 stdout 打 banner 或普通日志的 CLI 入口路径。
- `mcp` 域的主线实现应优先使用 async manager / async tool handlers；如需兼容同步调用方，应通过薄 sync adapter 桥接，而不是把同步实现继续当作主线。
- MCP 面向大模型的使用文档应作为打包资源进入 wheel，并通过 MCP resources 暴露；不要依赖仓库根目录下的 README / docs 文件在安装后仍可直接读取。
- 如果某个文件已经同时承载配置解析、生命周期、错误处理、协议序列化、日志落盘等多种责任，应主动拆分。
- 测试目录也遵循相同思路：
  - `tests/core/` 存放 config / compat / frontend / scaffold / smoke 这类核心域单测
  - `tests/cli/`、`tests/server/`、`tests/env/`、`tests/release/`、`tests/agent/`、`tests/development/` 按业务 owner 继续细分常规单测
  - `tests/mcp/` 聚焦 MCP tool/resource surface、stdio 集成和长会话状态机
  - `tests/device_unit/` 存放非真机的 device 域单测，继续覆盖 helpers / runtime / workspace / orchestrator / test-app
  - `tests/rpc/` 聚焦 RPC / REPL / session 行为
  - `tests/device/` 聚焦真机和 Python+agent 组合验证

## 接口风格 / Interface Style

- Python 对外接口倾向显式对象和显式参数，不依赖隐藏全局状态。
- 公共 wrapper 应尽量保留底层 Frida 语义；如果需要做 payload 归一化、句柄协议转换或兼容性预检，应收在内部 client 层，而不是污染公共 exports 面。
- stdio MCP 入口是协议通道，不允许混入 session banner、普通 `print(...)` 日志或其它用户向 stdout 输出；这类可读信息应改走 MCP resource/tool 返回值或文件日志。
- 错误信息应尽量具备操作性，直接指出失败阶段、冲突条件和建议动作，而不是只抛底层异常。
- 对于非显而易见的兼容性修复、协议限制或时序约束，应在代码附近加简短注释，说明“为什么必须这样做”。
- 修改公开接口、配置对象或协议字段时，要优先维护向调用方可解释的边界，而不是为了内部实现省事去泄漏内部结构。

## 测试风格 / Testing Style

- Python 侧测试主线使用 `pytest`，倾向行为驱动的断言，而不是堆大量实现细节快照。
- 测试中优先使用轻量 in-file fake、stub 和 helper factory，让单个测试文件能独立表达自己的场景。
- 需要共享 repo root、脚本路径或真机 `conftest` 路径时，应优先放进 `tests/support/` 这类轻量测试支持模块，而不是在各测试文件里重复硬编码 `__file__` 层级。
- `monkeypatch` 应命中真实拥有者模块或真实归属对象，不要依赖偶然可达的中转面。
- 单测应尽量只验证一个清晰行为面；RPC、REPL、server、config、CLI、device 场景不要混成一个巨型测试文件。
- 真机测试与普通单测保持隔离；需要验证 Python 与 agent 的组合行为时，应继续放在 `tests/device/` 这类独立层级中，普通 device 单测则归到 `tests/device_unit/`。
- 真机回归中的第一轮失败默认只算证据，不算根因；如果本次改动触达 `device` / `server` / `development.device_*` 这类真机主链路，应先做多轮复跑和失败分类，再决定是否改代码。
- 真机失败应优先区分：
  - 设备波动
  - host-side 测试/工具链问题
  - 真实代码回归
- 真机恢复逻辑应保持窄化和证据驱动：
  - 只在明确的瞬时错误语义下触发
  - 优先修阶段化恢复，而不是全局增加 timeout / retry
  - host-side 并发、下载、打包问题应通过序列化、缓存或依赖语义修复，而不是靠设备等待掩盖
- 如果重构影响 adb 目标解析、config 继承或 CLI 到 server/device 的接线，必须补三类回归测试：
  - 单设备自动解析
  - 多设备歧义报错
  - `ANDROID_SERIAL` 覆盖
- 如果某次重构改变了模块边界、导入拥有者或测试组织方式，应同步更新本文件，避免文档和真实测试风格脱节。

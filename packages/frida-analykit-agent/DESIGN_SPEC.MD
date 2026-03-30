# @zsa233/frida-analykit-agent 设计规范 / DESIGN_SPEC

## 适用范围与关系 / Scope / Relation

- 本文件只约束 `packages/frida-analykit-agent/` 这一侧的 TypeScript runtime、其类型测试以及与之直接耦合的测试组织方式。
- 本文件是 agent 子系统规范，用于补充根目录 `AGENTS.MD`，不是替代它。
- 若本文件与 `AGENTS.MD` 存在张力，以 `AGENTS.MD` 作为公共底线；本文件只负责把 agent 侧当前已形成的设计风格写清楚。
- 本文件应被理解为“当前设计风格快照”，目的是帮助 AI agent 延续现有结构，而不是借文档名义重写整套 runtime。

## 包导出边界 / Package Surface

- agent 包根 `src/index.ts` 应保持瘦入口，只暴露最轻量、最稳定、最常用的基础能力。
- 较重或领域性更强的能力应通过显式 subpath 暴露，而不是继续把包根做成 capability barrel。
- 当前已经明确的公共导入面包括：
  - 包根 `@zsa233/frida-analykit-agent`
  - `@zsa233/frida-analykit-agent/rpc`
  - `./config`
  - `./bridges`
  - `./helper`
  - `./process`
  - `./jni`
  - `./dex`
  - `./elf`
  - `./ssl`
  - `./native/libart`
  - `./native/libssl`
  - `./native/libc`
- `internal/*`、深层实现文件和历史上的 `./*` 通配路径，不属于当前承诺兼容的 public surface。
- 新增 capability 时，必须先判断它应属于：
  - 包根基础能力
  - 某个现有 subpath
  - 一个新的显式 subpath
- 不要把“内部写起来方便”误当成对外导出理由。

## Capability 组织方式 / Capability Organization

- agent 侧按能力域拆分组织，当前主线域包括：
  - `helper`
  - `process`
  - `jni`
  - `dex`
  - `elf`
  - `ssl`
  - `native/*`
  - `rpc`
- 每个能力域自己的 `index.ts` 应尽量薄，只负责导出该域的正式入口。
- 领域内部复杂实现继续留在领域目录内部；跨能力共享的低层工具放进 `internal/*`，而不是反向泄漏到公共入口。
- 高层 capability 与低层 binding 继续保持分层：
  - `ssl` 提供高层 hook / workflow
  - `native/libssl` 提供低层符号绑定
  - `native/libart` 提供 ART 低层绑定
  - `native/libc` 提供 libc 低层绑定
- 如果某个能力文件过大，优先在该能力域内部继续拆成结构、工具、验证器、桥接器、类型定义等子文件，而不是重新做跨域堆叠。

## 全局注册规则 / Global Registration

- `setGlobalProperties(...)` 只用于“明确希望在导入后进入 `globalThis` / RPC eval context”的能力暴露。
- `/rpc` 必须保持最小基础入口，只安装 RPC / REPL 所需的最小能力，不应顺手自动拖入 JNI、ELF、SSL、Dex、helper 或 native bindings。
- 某个 capability 是否会出现在 RPC eval context，应由用户是否显式 import 对应模块决定，而不是由隐式副作用决定。
- 新增全局注册时，应先确认它是否真的是跨脚本常用能力；否则优先保留为普通模块导出。
- 如果某个全局注册行为比较隐蔽、对 bundle 体积或 eval context 有明显影响，应在代码附近加注释说明注册目的。

## API 风格 / API Style

- agent 公开 API 倾向显式 import、显式能力边界、显式参数，而不是隐式全量可见。
- helper 主线接口优先使用结构化 facade，例如：
  - `help.log.*`
  - `help.fs.*`
  - `help.proc.*`
  - `help.mem.*`
  - `help.runtime.*`
- 历史 flat alias 只保留必要兼容，不应再把新能力继续做成新的平铺别名。
- JNI 相关接口延续“显式 `sig`、不做 name-only lookup、不做 overload 猜测”的风格。
- capability API 尽量返回结构清晰、类型可表达的结果；如果类型契约重要，应同步补上 type-tests。
- 公共 capability、内部实现文件和私有测试能力必须明确分层；仓库内测试专用内容不应误入正式 public package surface。

## 测试风格 / Testing Style

- agent 侧类型契约通过 `type-tests` 持续校验；只要公开类型面、导出形态或泛型行为发生变化，就要补对应 type-tests。
- 运行时行为验证优先按能力拆 suite，不要把 JNI、Dex、helper、SSL、ELF 混成一个单体测试入口。
- 仓库内的真机运行时回归继续通过私有 package `@zsa233/frida-analykit-agent-device-tests` 配合 Python 侧 `tests/device/` 触发。
- 私有 device-test package 只服务仓库内验证，不进入正式 runtime 的 `dependencies`、`exports` 或用户脚手架。
- 如果某次改动改变了包根导出边界、subpath 结构、全局注册策略、测试编排方式或公开类型契约，应同步更新本文件。

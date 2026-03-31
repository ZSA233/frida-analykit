# @zsa233/frida-analykit-agent

🌍 语言: 中文 | [English](README_EN.md)

`@zsa233/frida-analykit-agent` 是给自定义 TypeScript Frida agent 使用的 runtime 包，通常由 `frida-analykit gen dev` 生成的工作区消费，也可以手动用于任意 `frida-compile` 项目。

## 包定位

- 包根 `@zsa233/frida-analykit-agent` 是瘦入口，只保留轻量基础能力。
- 较重 capability 通过显式 subpath 暴露，避免 `/rpc` 默认拖入整套 runtime。
- 公开能力面围绕 RPC、helper、process、JNI、ELF、SSL、Dex 和 selected native binding 组织。

## 安装

在 agent 工作区中安装：

```sh
npm install @zsa233/frida-analykit-agent
```

然后用 `frida-compile` 构建：

```sh
npx frida-compile index.ts -o _agent.js -c
```

## 能力总览表

| 能力 | 导入路径 | 主要用途 | 是否默认轻入口可见 |
|:---|:---|:---|:---|
| `config` | `@zsa233/frida-analykit-agent/config` | 访问 `Config`、`LogLevel` 等基础配置对象 | 是 |
| `rpc` | `@zsa233/frida-analykit-agent/rpc` | 安装最小 RPC / REPL runtime | 否 |
| `helper` | `@zsa233/frida-analykit-agent/helper` | 使用 `help` facade 访问日志、文件、内存和运行时辅助能力 | 是 |
| `process` | `@zsa233/frida-analykit-agent/process` | 使用 `proc` 和进程映射辅助能力 | 是 |
| `bridges` | `@zsa233/frida-analykit-agent/bridges` | 访问 Java / ObjC / Swift bridge 封装 | 否 |
| `jni` | `@zsa233/frida-analykit-agent/jni` | 使用 `JNIEnv`、JNI wrapper 和显式签名调用 | 否 |
| `ssl` | `@zsa233/frida-analykit-agent/ssl` | 使用 `SSLTools`、BoringSSL 定位和 keylog 辅助 | 否 |
| `elf` | `@zsa233/frida-analykit-agent/elf` | 解析 ELF、创建 `ElfSymbolHooks` 和流式 snapshot | 否 |
| `elf/enhanced` | `@zsa233/frida-analykit-agent/elf/enhanced` | 手动导入常用 symbol hook preset，避免默认打进核心 bundle | 否 |
| `dex` | `@zsa233/frida-analykit-agent/dex` | 枚举 class loader dex 并流式 dump 到 Python 侧 | 否 |
| `native/libart` | `@zsa233/frida-analykit-agent/native/libart` | 访问 ART 低层符号绑定 | 否 |
| `native/libssl` | `@zsa233/frida-analykit-agent/native/libssl` | 访问 OpenSSL / BoringSSL 低层符号绑定 | 否 |
| `native/libc` | `@zsa233/frida-analykit-agent/native/libc` | 访问 libc 低层封装和常见系统调用 | 否 |

## 普通使用方式

### 最小 agent

最小 agent 只需要安装 `/rpc`：

```ts
import "@zsa233/frida-analykit-agent/rpc"

setImmediate(() => {
  console.log("pid =", Process.id)
})
```

### 按需导入 capability

如果需要更多能力，推荐显式导入对应 capability：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help } from "@zsa233/frida-analykit-agent/helper"
import "@zsa233/frida-analykit-agent/process"
import { JNIEnv } from "@zsa233/frida-analykit-agent/jni"
import { SSLTools } from "@zsa233/frida-analykit-agent/ssl"
import { ElfTools } from "@zsa233/frida-analykit-agent/elf"
import { castElfSymbolHooks } from "@zsa233/frida-analykit-agent/elf/enhanced"
import { DexTools } from "@zsa233/frida-analykit-agent/dex"
import { Libart } from "@zsa233/frida-analykit-agent/native/libart"
import { Libssl } from "@zsa233/frida-analykit-agent/native/libssl"
import { libc } from "@zsa233/frida-analykit-agent/native/libc"

setImmediate(() => {
  console.log("api level =", help.runtime.androidApiLevel())
  console.log("maps =", proc.loadProcMap().items.length)
  console.log("cmdline =", help.proc.readCmdline())
  console.log("jni env =", JNIEnv.$handle)
  console.log("ssl guesses =", SSLTools.guess().length)
  console.log("main module =", ElfTools.findModuleByName("libc.so")?.name)
  console.log("elf hook facade =", castElfSymbolHooks(ElfTools.createSymbolHooks("libc.so", { observeDlsym: false })).findSymbol("getpid")?.name)
  console.log("dex loaders =", DexTools.enumerateClassLoaderDexFiles().length)
  console.log("libart loaded =", Libart.$getModule().name)
  console.log("libssl module =", Libssl.$getModule().name)
  console.log("cwd =", libc.getcwd())
})
```

如果你只需要轻量基础能力，也可以直接从包根导入：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help, proc } from "@zsa233/frida-analykit-agent"
```

当前更推荐显式 subpath，因为它更容易控制 bundle 体积和导入边界。

## 高级能力

### RPC / REPL

安装 `/rpc` 后，agent 会暴露结构化 RPC exports，供 Python CLI 的 `script.eval(...)`、`script.jsh(...)`、REPL 句柄访问和作用域调用使用。

- RPC eval context 每次执行时都会动态读取 `globalThis`。
- capability 是否可见，取决于你是否已经在 `index.ts` 里显式 import 了对应模块。
- `/rpc` 不再默认拖入整套 runtime，只保留最小基础。
- `Libart`、`Libssl`、`Libc` 也遵循同样的按需可见规则。

### ElfTools / SymbolHooks

显式导入后可以把 `/elf` 作为核心能力、把 `/elf/enhanced` 作为可选 preset 增强层：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { ElfTools } from "@zsa233/frida-analykit-agent/elf"
import { castElfSymbolHooks } from "@zsa233/frida-analykit-agent/elf/enhanced"

setImmediate(() => {
  const hooks = ElfTools.createSymbolHooks("libc.so", { logTag: "demo", observeDlsym: false })
  const enhanced = castElfSymbolHooks(hooks)
  enhanced.getpid()
  const summary = ElfTools.snapshot("libc.so", { tag: "manual" })
  console.log("snapshot =", summary.snapshotId, summary.moduleName)
})
```

- `/elf` 当前提供 `ElfTools.createSymbolHooks(...)`、`ElfTools.snapshot(...)` 和现有模块解析入口。
- `ElfSymbolHooks` 是模块级 symbol hook 状态对象，支持 lazy symbol registry、`dlsym` 联动和显式签名 `attach(...)`。
- `/elf/enhanced` 只在你手动 import 时提供常用 preset，不会自动进入 `globalThis` 或核心 bundle。
- `snapshot()` 会发送 `ELF_SNAPSHOT_BEGIN -> BATCH(ELF_SNAPSHOT_CHUNKS) -> ELF_SNAPSHOT_END`。
- Python 侧默认写到 `script.elftools.output_dir`，未配置时回退到 `agent.datadir/elftools`，输出布局是 `snapshots/<tag-or-id>/` 与 `logs/<tag>.log`。

### DexTools

显式导入后即可使用：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { DexTools } from "@zsa233/frida-analykit-agent/dex"

setImmediate(() => {
  const loaders = DexTools.enumerateClassLoaderDexFiles()
  console.log("dex loaders =", loaders.length)
  DexTools.dumpAllDex({ tag: "manual" })
})
```

- `DexTools` 当前提供 `enumerateClassLoaderDexFiles()` 和 `dumpAllDex(...)`。
- `dumpAllDex()` 会发送 `DEX_DUMP_BEGIN -> BATCH(DEX_DUMP_FILES) -> DEX_DUMP_END`。
- 默认最大批量大小来自 Python 配置 `script.rpc.batch_max_bytes`，agent 侧对应 `Config.BatchMaxBytes`。
- 单个超大 dex 会单独成批发送而不会继续切片，Python 侧默认写到 `script.dextools.output_dir`，未配置时回退到 `agent.datadir/dextools`。

### JNI / native bindings

`jni` 与 `native/*` capability 适合需要直接访问 ART、JNI 或 libc/libssl 符号的场景。

```ts
import { JNIEnv } from "@zsa233/frida-analykit-agent/jni"
import { Libart } from "@zsa233/frida-analykit-agent/native/libart"
import { Libssl } from "@zsa233/frida-analykit-agent/native/libssl"
import { libc } from "@zsa233/frida-analykit-agent/native/libc"

setImmediate(() => {
  console.log("jni env =", JNIEnv.$handle)
  console.log("libart =", Libart.$getModule().name)
  console.log("libssl =", Libssl.$getModule().name)
  console.log("pid =", libc.getpid())
})
```

- `jobject.$method(name, sig)`、`.$call(name, sig, ...args)`、`jclass.$staticMethod(name, sig)` 等 member facade 都要求显式 `sig`。
- JNI 默认返回 wrapper，不自动转成 JS primitive 或 string。
- accessor 提供 `withLocal(...)` 用于局部引用生命周期收口。
- 导入 `native/libart`、`native/libssl`、`native/libc` 后，会按需注册对应全局对象。

## 调试与非公共内容

- 当前不再提供 `./*` 通配 export，也不承诺任何内部深层路径兼容。
- `src/internal/*` 和其他深层内部路径不属于公共 API，不应在业务 agent 中直接依赖。
- 仓库里存在私有包 `@zsa233/frida-analykit-agent-device-tests`，它只服务于 `tests/device` 真机回归，不会进入本包 `dependencies` 或 `exports`。
- 如果你需要调试 bundle、导出边界或真机行为，优先参考仓库内的 README、type test 和 device test，而不是依赖未公开内部路径。

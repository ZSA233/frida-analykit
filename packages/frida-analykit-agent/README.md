# @zsa233/frida-analykit-agent

`@zsa233/frida-analykit-agent` 是给自定义 TypeScript Frida agent 使用的 runtime 包。

它通常由 `frida-analykit gen dev` 生成的工作区消费，也可以手动用于任意 `frida-compile` 项目。

## 安装

在 agent 工作区中安装：

```sh
npm install @zsa233/frida-analykit-agent
```

然后用 `frida-compile` 构建：

```sh
npx frida-compile index.ts -o _agent.js -c
```

## 入口设计

包根 `@zsa233/frida-analykit-agent` 现在是瘦入口，只导出轻量基础能力：

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

较重 capability 改为显式 subpath：

- `@zsa233/frida-analykit-agent/rpc`
- `@zsa233/frida-analykit-agent/config`
- `@zsa233/frida-analykit-agent/bridges`
- `@zsa233/frida-analykit-agent/helper`
- `@zsa233/frida-analykit-agent/process`
- `@zsa233/frida-analykit-agent/jni`
- `@zsa233/frida-analykit-agent/ssl`
- `@zsa233/frida-analykit-agent/elf`
- `@zsa233/frida-analykit-agent/dex`
- `@zsa233/frida-analykit-agent/native/libssl`
- `@zsa233/frida-analykit-agent/native/libc`

当前不再提供 `./*` 通配 export，也不承诺任何内部深层路径兼容。

## `/rpc` 轻入口

`@zsa233/frida-analykit-agent/rpc` 现在只安装最小 RPC / REPL 基础能力：

```ts
import "@zsa233/frida-analykit-agent/rpc"
```

它不会再自动 import 这些较重能力：

- `help`
- `proc`
- `JNIEnv`
- `SSLTools`
- `ElfTools`
- `Libssl`
- `Libc`

如果你没有在自己的 `index.ts` 里显式 import 对应 capability，它们就不会被打进 `_agent.js`，也不会自动出现在 RPC eval context 中。

## 推荐导入方式

最小 agent：

```ts
import "@zsa233/frida-analykit-agent/rpc"

setImmediate(() => {
  console.log("pid =", Process.id)
})
```

按需导入 capability：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help } from "@zsa233/frida-analykit-agent/helper"
import "@zsa233/frida-analykit-agent/process"
import { JNIEnv } from "@zsa233/frida-analykit-agent/jni"
import { SSLTools } from "@zsa233/frida-analykit-agent/ssl"
import { ElfTools } from "@zsa233/frida-analykit-agent/elf"
import { DexTools } from "@zsa233/frida-analykit-agent/dex"
import { Libssl } from "@zsa233/frida-analykit-agent/native/libssl"
import { libc } from "@zsa233/frida-analykit-agent/native/libc"

setImmediate(() => {
  console.log("api level =", help.runtime.androidApiLevel())
  console.log("maps =", proc.loadProcMap().items.length)
  console.log("cmdline =", help.proc.readCmdline())
  console.log("jni env =", JNIEnv.$handle)
  console.log("ssl guesses =", SSLTools.guess().length)
  console.log("main module =", ElfTools.findModuleByName("libc.so")?.name)
  console.log("dex loaders =", DexTools.enumerateClassLoaderDexFiles().length)
  console.log("libssl module =", Libssl.$getModule().name)
  console.log("cwd =", libc.getcwd())
})
```

如果你只需要轻量基础能力，包根可以直接用：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help, proc } from "@zsa233/frida-analykit-agent"
```

但当前推荐主线是显式 subpath，因为它更容易控制 bundle 体积和导入边界。

## Helper Facade

`helper` 现在主线是分组 facade：

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

## Capability 概览

- `jni`
  提供 `JNIEnv`、JNI wrapper、string helper，以及显式 `sig` 驱动的 member facade
- `ssl`
  提供 `SSLTools`、`BoringSSL` 与 SSL keylog/定位相关能力
- `elf`
  提供 `ElfTools` 和 ELF 解析辅助能力
- `dex`
  提供 `DexTools`，支持枚举 class loader 中的 dex，并按批量上限流式 dump 到 Python 侧
- `native/libart`
  提供 `Libart` 低层符号绑定；导入后会注册全局 `Libart`
- `native/libssl`
  提供 `Libssl` 低层符号绑定；导入后会注册全局 `Libssl`
- `native/libc`
  提供 `Libc` / `libc`；导入后会注册全局 `Libc`
- `process`
  导入后会注册全局 `proc`

## RPC / REPL 行为

`/rpc` 安装后，agent 侧会暴露结构化 RPC exports，供 Python CLI 的 `script.eval(...)`、`script.jsh(...)`、REPL 句柄访问与作用域调用使用。

当前行为要点：

- RPC eval context 每次执行时都会动态读取 `globalThis`
- capability 是否可见，取决于你是否已经在 `index.ts` 里显式 import 了对应模块
- `/rpc` 不再默认拖入整套 runtime，只保留最小基础
- `Libart` / `Libssl` / `Libc` 也遵循同样的按需可见规则

## DexTools

显式导入后：

```ts
import { DexTools } from "@zsa233/frida-analykit-agent/dex"
```

当前提供：

- `DexTools.enumerateClassLoaderDexFiles()`
- `DexTools.dumpAllDex({ tag?, dumpDir?, maxBatchBytes?, log? })`

`dumpAllDex()` 在 RPC 模式下会发送 `DEX_DUMP_BEGIN -> BATCH(DEX_DUMP_FILES) -> DEX_DUMP_END`。默认最大批量大小来自 Python 配置 `script.rpc.batch_max_bytes`，agent 侧对应 `Config.BatchMaxBytes`；单个超大 dex 会单独成批发送而不会继续切片。Python 侧默认写到 `script.dextools.dex_dir`，未配置时回退到 `agent.datadir/dextools`。

## JNI 能力说明

`@zsa233/frida-analykit-agent/jni` 当前除了 `JNIEnv` wrapper 外，还提供 member facade：

- `jobject.$method(name, sig)` / `.$call(name, sig, ...args)`
- `jobject.$field(name, sig)` / `.$getField(...)` / `.$setField(...)`
- `jclass.$staticMethod(name, sig)` / `.$staticCall(...)`
- `jclass.$constructor(sig)` / `.$new(sig, ...args)`
- `.$nonvirtualMethod(...)` / `.$nonvirtualCall(...)`

当前约束：

- `sig` 必填，不做 name-only lookup，也不做 overload 猜测
- 默认返回 JNI wrapper，不自动转 JS primitive/string
- accessor 提供 `withLocal(...)` 用于局部引用生命周期收口

## 非公共内容

仓库里还有一个私有包 `@zsa233/frida-analykit-agent-device-tests`，只服务于 `tests/device` 真机回归：

- 它不会进入本包的 `dependencies`
- 它不会进入本包的 `exports`
- 它不会进入用户脚手架主线

如果你是普通 npm 用户，可以忽略它。

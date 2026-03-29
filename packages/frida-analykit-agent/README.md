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

当前包暴露两类入口：

- 包根 `@zsa233/frida-analykit-agent`
  兼容 / 便利入口，会带出较完整的 runtime 能力面
- capability subpath
  推荐用于轻量 bundle，由你的显式 import 决定最终 `_agent.js` 体积

当前显式 subpath：

- `@zsa233/frida-analykit-agent/rpc`
- `@zsa233/frida-analykit-agent/config`
- `@zsa233/frida-analykit-agent/bridges`
- `@zsa233/frida-analykit-agent/helper`
- `@zsa233/frida-analykit-agent/process`
- `@zsa233/frida-analykit-agent/jni`
- `@zsa233/frida-analykit-agent/ssl`
- `@zsa233/frida-analykit-agent/elf`
- `@zsa233/frida-analykit-agent/libssl`

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
import { Libssl } from "@zsa233/frida-analykit-agent/libssl"

setImmediate(() => {
  console.log("api level =", help.androidGetApiLevel())
  console.log("maps =", proc.loadProcMap().items.length)
  console.log("jni env =", JNIEnv.$handle)
  console.log("ssl guesses =", SSLTools.guess().length)
  console.log("main module =", ElfTools.findModuleByName("libc.so")?.name)
  console.log("libssl =", Libssl.name)
})
```

如果你更偏好便利入口，包根仍然可用：

```ts
import "@zsa233/frida-analykit-agent/rpc"
import { help, proc, JNIEnv, SSLTools } from "@zsa233/frida-analykit-agent"
```

但当前推荐主线是显式 subpath，因为它更容易控制 bundle 体积和导入边界。

## 已暴露能力面

包根 `.` 当前导出：

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

其中较重要的 capability：

- `jni`
  提供 `JNIEnv`、JNI wrapper、string helper，以及显式 `sig` 驱动的 member facade
- `ssl`
  提供 `SSLTools`、`BoringSSL` 与 SSL keylog/定位相关能力
- `elf`
  提供 `ElfTools` 和 ELF 解析辅助能力
- `process`
  导入后会注册全局 `proc`
- `libssl`
  导入后会注册全局 `Libssl`

## RPC / REPL 行为

`/rpc` 安装后，agent 侧会暴露结构化 RPC exports，供 Python CLI 的 `script.eval(...)`、`script.jsh(...)`、REPL 句柄访问与作用域调用使用。

当前行为要点：

- RPC eval context 每次执行时都会动态读取 `globalThis`
- 因此 capability 是否可见，取决于你是否已经在 `index.ts` 里显式 import 了对应模块
- `/rpc` 不再默认拖入整套 runtime，只保留最小基础

## JNI 能力说明

`@zsa233/frida-analykit-agent/jni` 当前除了 `JNIEnv` wrapper 外，还提供了第一阶段 member facade：

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

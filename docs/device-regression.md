# 真机回归流程

## 目的

本文件用于固化 `frida-analykit` 真机回归时已经验证过的经验，尤其是下面这类场景：

- `make device-test-all`
- `pytest tests/device -m device`
- `frida-analykit doctor device-compat`
- 发版前的真机回归确认

目标不是“看到红就立刻修”，而是先判断失败到底属于：

- 设备波动
- 主机侧测试/工具链问题
- 真实代码回归

只有分类清楚之后，才决定是否需要修改代码，避免把设备抖动误修成长期复杂度。

## 基本原则

- 单次失败只能算证据，不能直接算根因结论。
- 真机回归优先保留失败现场，包括失败设备、失败阶段、stdout/stderr、`adb devices -l` 结果、另一台设备是否通过。
- 先多轮验证，再决定是否修复；不要在第一次红项后无脑堆 retry、timeout 或保护分支。
- 允许设备有波动，但只有在“设备能自恢复并继续跑”的前提下，才值得在测试链路里补恢复策略。
- 恢复策略必须窄化到明确阶段和明确错误语义，不能把所有路径都变成长时间等待。

## 常用环境变量与控制入口

### 环境变量

| 变量 | 主要影响 | 作用 |
|:--|:--|:--|
| `FRIDA_ANALYKIT_ENABLE_DEVICE=1` | `pytest tests/device -m device`、`make device-*` | 打开真机测试入口；未设置时，device tests 会直接 skip。 |
| `ANDROID_SERIAL=<serial>` | `make device-test*`、`server` 相关命令、`doctor device-compat` 的默认设备选择 | 固定目标设备；多设备在线时建议显式设置。 |
| `FRIDA_ANALYKIT_DEVICE_APP=<package>` | app-backed 真机测试 | 覆盖默认测试包 `com.frida_analykit.test`。当你要对特定业务 app 回归时，用它替换默认 app。 |
| `FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS=1` | `pytest tests/device -m device`，以及经 `make device-*` 包装后的同类命令 | 跳过依赖 app 的真机用例，只保留 server、attach probe、REPL handle 这类不依赖业务 app 的链路。 |
| `FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path>` | `tests/device/test_server_install.py` | 给 `--local-server` 安装路径测试提供本地 `frida-server` 文件；没设置时该类测试会跳过。 |
| `FRIDA_ANALYKIT_DEVICE_FRIDA_VERSION=<version>` | `DeviceTestContext`、多版本 Frida 真机回归 | 显式指定真机回归使用哪一套受管 Python/Frida 版本；不设置时走默认 device profile。 |

### `make` 参数与命令参数

- `make device-test DEVICE_TEST_SKIP_APP=1`
  作用：把 `FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS=1` 传给底层 pytest，适合快速回归不依赖 app 的链路。
- `make device-test DEVICE_TEST_APP=<package>`
  作用：把 `FRIDA_ANALYKIT_DEVICE_APP=<package>` 传给底层 pytest，适合直接对指定 app 跑 device suite。
- `frida-analykit doctor device-compat --serial <serial>`
  作用：把兼容性采样固定到一台设备，避免多设备在线时误选目标。
- `frida-analykit doctor device-compat --all-devices`
  作用：对当前所有在线设备逐台做最小注入式兼容性采样。
- `frida-analykit doctor device-compat --app <package>`
  作用：给 compat 采样显式指定 app；未提供时会优先看配置，再回退到默认测试包。

推荐理解方式：

- 直接跑 `pytest tests/device -m device` 时，优先使用环境变量。
- 通过 `make device-*` 跑时，优先使用 `ANDROID_SERIAL`、`DEVICE_TEST_APP`、`DEVICE_TEST_SKIP_APP` 这类更短的入口参数。
- 真机回归失败时，先把这些变量和参数记录下来，再做失败分类；否则后续很难判断到底是设备差异、配置差异还是代码回归。

## 推荐执行顺序

### 发版前或设备相关改动后的基线回归

1. 先执行一轮完整真机回归：

```sh
make device-test-all
```

2. 如果这次改动触达以下路径，至少再跑一轮稳定性确认：

- `src/frida_analykit/device/`
- `src/frida_analykit/server/`
- `src/frida_analykit/development/device_*`
- `tests/device/`
- `spawn` / `attach` / `server boot` / `server install` / `doctor device-compat`

3. 如果第一轮就失败，不要马上改代码，先做失败分类。

### 失败后的分类流程

1. 记录失败设备 serial、失败测试、失败阶段。
2. 立即查看：

```sh
adb devices -l
```

3. 如果失败集中在单台设备，优先对该设备做定向复跑，而不是立刻改全局逻辑。
4. 如果失败点与设备无关，先排查主机侧测试链路。
5. 只有在重复复现后，才把问题归为真实代码回归。

## 失败分类

### 1. 设备波动

更像设备波动而不是代码问题的典型信号：

- 只在单台设备上出现，另一台设备同阶段通过。
- `adb devices -l` 中目标设备短暂消失，或 transport id 变化。
- 失败发生在 `server stop` / `server boot` / attach probe / app launch 刚切换的时间点。
- 错误包含：
  - `ServerNotRunningError`
  - `unable to connect to remote frida-server`
  - `connection reset`
  - `connection closed`
  - `requested config.server.device ... but connected devices are ...`
- 等设备恢复 ready 后，定向复跑可以通过。

这类问题的处理原则：

- 可以接受单次失败。
- 优先补“设备恢复后继续跑”的窄化恢复逻辑。
- 不要直接把所有 timeout、重试次数整体抬高。

### 2. 主机侧测试/工具链问题

更像主机侧问题的典型信号：

- 两台设备在相同的 host-side 阶段同时失败。
- 失败发生在真正接触设备之前，例如：
  - `npm pack`
  - `npm install`
  - workspace build
  - 本地依赖解析
  - release metadata 下载
- 单设备复跑也可能通过，但失败点本质上与 ROM/设备状态无关。

这类问题的处理原则：

- 优先修主机侧并发、缓存、下载、依赖解析语义。
- 不要用设备重试去掩盖 host-side 竞争问题。

### 3. 真实代码回归

更像真实代码问题的典型信号：

- 两台设备都在相同测试点稳定失败。
- 单设备定向复跑在设备 ready 的前提下仍然复现。
- 失败与设备是否在线无关，而与特定行为强绑定，例如：
  - 某个 attach/spawn 路径固定失败
  - 某个 doctor/probe 语义固定错误
  - 某个 runtime/build/install 逻辑固定断裂

这类问题的处理原则：

- 先收敛根因，再修复。
- 修复后至少做一次单设备验证和一次多设备验证。

## 重试与恢复策略约束

允许加恢复，但必须满足这些约束：

- 恢复必须是阶段化的，例如：
  - host-side npm 打包/构建
  - `server boot` 后设备短暂断链
  - attach probe 时远端 server 暂时不可达
- 恢复必须由明确证据触发，而不是所有失败都进入恢复分支。
- 恢复次数应保持有上限，默认只给 1 次恢复机会；只有明确证据支持时才增加。
- 恢复等待应短且有边界；优先 5 到 20 秒级的定向等待，而不是全局大幅拉长超时。
- 如果失败属于 host-side 决定性错误，例如依赖缺失、构建失败、协议语义错误，就不应走设备恢复。

## 发版前的真机门槛

当 release 涉及真机链路时，进入打 tag / 发布之前，推荐按下面的门槛执行：

1. 至少完成 2 轮 `make device-test-all`。
2. 如果某轮失败，先分类，再决定：
   - 设备波动：等待设备恢复后补一次定向验证；通过后可继续。
   - 主机侧问题：必须先修复，再重新跑完整回归。
   - 真实代码回归：停止发版，先修复。
3. 不允许把“单轮偶发红项”直接包装成正式代码修复结论。

## 推荐记录项

每次真机异常回归，至少记录这些信息，便于后续比较：

- 命令
- 时间
- 失败设备 serial
- 失败测试或失败阶段
- 失败时 `adb devices -l` 输出
- 是否只有单设备失败
- 复跑是否通过
- 最终分类：设备波动 / 主机侧问题 / 真实代码回归

如果最终确认为代码问题，应继续把结论沉淀到：

- `AGENTS.MD` 中的长期规则
- `docs/release-process.md` 中的发版门槛
- `src/frida_analykit/DESIGN_SPEC.MD` 中的实现约束

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

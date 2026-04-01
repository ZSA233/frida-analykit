# 发布流程

每个 release tag 会产出以下发布物：

- 1 个 Python 源码包 `sdist`
- 1 个 Python wheel
- 1 个 npm tarball
- 1 个 Android 真机回归测试 APK `frida-analykit-device-test-app-vX.Y.Z[-rc.N].apk`

## 分支约定

发布工作在冻结分支上完成，不要求必须从 `main` 直接发布。

推荐约定：

1. 日常开发在线上版本分支推进，例如 `dev/v2`。
2. 准备某个具体版本发布时，从当前冻结代码线切出或继续使用 `release/vX.Y.Z`。
3. RC 和 stable 的版本切换、校验、打 tag 都在 `release/vX.Y.Z` 上完成。
4. stable 发布完成后，把 `release/vX.Y.Z` 合并回 `main`。
5. 如果仍有长期开发线，例如 `dev/v2`，再把 `main` 的发布结果回灌回去。

## 发版请求前置条件

只有在“用户明确给出目标发布版本号”之后，才进入正式发版流程。

执行前应先确认：

1. 用户已经明确说明这次要发布的目标版本号。
2. 目标版本号与当前线上已发布版本、当前仓库版本真源、当前分支状态之间不存在明显冲突。
3. 如果用户给出的版本号不符合当前线上版本的正常递增关系，应先向用户确认版本号是否说错，而不是直接继续发版。

这里的“先确认”优先于后续所有版本切换、打 tag、dry-run 和 publish 步骤。

## 发版前文档收束

正式进入 release-version、preflight、RC 或 stable 步骤之前，必须先基于 `PRE_README.MD` 收束对外文档。

需要处理的文档分为四类：

1. 根 `README.md`
   面向整体用户，应保持更简洁，只关注项目主线接口、环境准备、接入流程和整体发布物。
2. `README_EN.md`
   是根 `README.md` 的严格英文翻译版本，应在根 README 收束后同步更新，不单独发明另一套结构或事实口径。
3. `packages/frida-analykit-agent/README.md`
   面向 npmjs 上的 `@zsa233/frida-analykit-agent` 包用户，应只保留与该包直接相关的信息，允许比根 README 展开更多包级细节。
4. `packages/frida-analykit-agent/README_EN.md`
   是 `packages/frida-analykit-agent/README.md` 的严格英文翻译版本，应在包 README 收束后同步更新。

推荐顺序：

1. 先基于 `PRE_README.MD` 收束根 `README.md`
2. 再同步更新 `README_EN.md`
3. 再基于同一份 `PRE_README.MD` 收束 `packages/frida-analykit-agent/README.md`
4. 再同步更新 `packages/frida-analykit-agent/README_EN.md`
5. 对根 README 中英对、包 README 中英对分别做一次双语镜像二次校对
6. 文档完成后，再继续下面的 release-version / preflight / RC / stable 流程

双语镜像二次校对至少要检查：

- 章节顺序是否一致
- 标题数量与层级是否一致
- 表格行列与字段是否一致
- 代码块数量、顺序和参数是否一致
- 提示项、限制说明、示例数量是否一致
- 根 README 的 Mermaid 架构图是否与 `docs/arch.mermaid` 完全一致

如果中英 README 任一边存在漏段、漏表、漏示例、漏限制说明，视为文档收束未完成，不允许进入 release-version / preflight / RC / stable。

根 README 的架构说明图必须读取并嵌入 `docs/arch.mermaid`；在架构未变时，应把该文件视为只读事实源，而不是顺手在收束 README 时改图。

不要把四份文档当作同一份 README 的不同副本机械同步；根 README 与包 README 面向的发布面不同，但每一组中英文档都必须严格镜像。

## 一次性准备

首次公开发布前，先确认以下事项：

1. 在 GitHub 仓库中配置 `production` environment。
   需要启用 reviewer 审核，并打开 `Prevent self-review`。
2. 确认 npm scope 和包名所有权已经就绪。
   runtime 包名固定为 `@zsa233/frida-analykit-agent`。
3. 保持 `.nvmrc` 指向仓库构建使用的 Node 版本。
   stable 发布任务会在 publish 阶段切换到 `Node 22.14.0`。
4. 本地执行 `make release-local` 前，准备好 `JDK 17` 和 Android SDK `platforms;android-35` / `build-tools;35.0.0`。
   release bundle 现在会同时构建真机回归测试 APK。
5. 把支持范围的真源放在 `pyproject.toml` 的 `frida>=...,<...` 直接依赖里。
6. 把受测 profile 的真源放在 `src/frida_analykit/resources/compat_profiles.json`。
7. 把发布版本真源放在 `release-version.toml`。
   该文件只驱动发布关键文件，不自动修改 README / docs 中的安装示例。
8. 为 stable 自动发布配置 npm Trusted Publishing。
   只绑定到 `.github/workflows/release.yml`。

## 版本切换与本地校验

版本切换统一通过 `scripts/release_version.py` 和 `Makefile` 完成，不手改 `_version.py`、两个 `package.json` 和 `package-lock.json`。

查看当前版本真源派生结果：

```sh
make release-version-show
```

切到 RC：

```sh
make release-version-rc BASE_VERSION=X.Y.Z RC=N CHECK=1
```

切到 stable：

```sh
make release-version-stable BASE_VERSION=X.Y.Z CHECK=1 [RC_TAG=vX.Y.Z-rc.N]
```

这些命令会同步以下文件：

- `release-version.toml`
- `src/frida_analykit/_version.py`
- 根 `package.json` 的 `version`
- 根 `package.json` 对 `@zsa233/frida-analykit-agent` 的依赖
- `packages/frida-analykit-agent/package.json` 的 `version`
- `package-lock.json`

`CHECK=1` 会在版本切换后执行 `make release-preflight`。版本切换是原子的：

- 同步失败会回滚
- lockfile 重算失败会回滚
- `release-preflight` 失败会回滚

需要特别明确的一点：

- `make release-version-rc` / `make release-version-stable` 只负责切换版本文件并跑校验，不会自动创建 git commit 或 tag。
- RC / stable 的 commit 和 tag 必须由发布操作者按顺序显式执行，不要并行。
- 尤其不要把 `git commit` 和 `git tag` 放到并行任务里执行；否则 tag 很容易落到前一个提交，而不是刚刚生成的 release commit。

`make release-preflight RELEASE_TAG=...` 会执行：

- `scripts/release_version.py check-sync`
- `scripts/release_assets.py validate-config`
- `scripts/release_assets.py validate-release-version`
- stable 时额外执行 `scripts/release_assets.py validate-promotion`
- `npm ci`
- 非 smoke/scaffold/device 测试
- `npm run agent:build`

完整的本地发布检查是三步：

```sh
make release-preflight RELEASE_TAG=vX.Y.Z[-rc.N] [RC_TAG=vX.Y.Z-rc.N]
make release-local RELEASE_TAG=vX.Y.Z[-rc.N]
make release-install-check RELEASE_TAG=vX.Y.Z[-rc.N]
```

## 真机回归门槛

如果当前 release 触达以下任一范围，在 push tag 或继续 RC/stable 发布前，必须补真机回归：

- `src/frida_analykit/device/`
- `src/frida_analykit/server/`
- `src/frida_analykit/development/device_*`
- `tests/device/`
- `spawn` / `attach` / `server boot` / `server install` / `doctor device-compat`

推荐门槛如下：

1. 先执行至少一轮完整真机回归：

```sh
make device-test-all
```

2. 如果这轮通过，再补一轮稳定性确认。
3. 如果任一轮失败，不要立刻改代码，先按 [docs/device-regression.md](device-regression.md) 分类：
   - 设备波动
   - 主机侧测试/工具链问题
   - 真实代码回归
4. 只有在完成分类后，才决定是否进入修复。
5. 如果失败属于设备波动，允许在设备恢复后补一次定向复跑；定向复跑通过后，才可继续后续发布步骤。
6. 如果失败属于 host-side 或真实代码问题，必须先修复，再重新执行完整真机回归。

固定原则：

- 不能因为第一次真机红项就无脑增加全局 timeout 或重试次数。
- 真机恢复逻辑只允许做窄化补偿，例如设备短暂掉线、远端 server 瞬时不可达、host-side 明确的并发竞争。
- 发布操作者应保留至少这些证据：
  - 失败设备 serial
  - 失败阶段/测试名
  - stdout/stderr
  - `adb devices -l`
  - 复跑是否通过

## 远端 CI 校验

在进入 release dry-run、push release tag 或继续 RC/stable 后续步骤之前，必须先确认当前 release ref 的 GitHub Actions `CI` 工作流已经通过。

当前仓库的 `CI` workflow 具备两种入口：

- push 到 `main` 或 `release/*` 时自动触发
- 手动 `workflow_dispatch` 触发

推荐规则：

1. 先把当前 release 分支 push 到远端，例如 `release/vX.Y.Z`。
2. 优先复用这次 push 自动触发的 `CI` 结果。
3. 如果需要重新验证、补跑或更方便地集中监控，可以手动触发一次 CI：

```sh
make release-ci CI_REF=release/vX.Y.Z
```

这个 helper 会：

- 对指定 ref 触发 `CI` 的 `workflow_dispatch`
- 自动定位这次 dispatch 对应的 run
- 直接进入 `gh run watch ... --exit-status`

发版继续之前，至少要确认这些作业全部通过：

- `release-contract`
- `python-tests (ubuntu-latest)`
- `python-tests (macos-latest)`
- `python-tests (windows-latest)`
- `compat-smoke`
- `node-scaffold`

其中 `python-tests (windows-latest)` 是当前最容易暴露路径、shell、换行和平台差异回归的作业；如果它失败，不要继续发版。

CI 未通过时的固定处理原则：

- 立即停止当前 release 流程
- 优先定位并修复 CI 红项，尤其是 Windows 专属失败
- 修复后重新 push release 分支，或重新执行 `make release-ci`
- 只有 CI 全绿后，才允许继续 dry-run、打 tag 或 publish

推荐在每次准备 push tag 之前做一次显式确认：

```sh
git rev-parse HEAD
git rev-parse vX.Y.Z[-rc.N]
```

这两个值必须完全一致；如果不一致，说明 tag 没有打在当前 release commit 上，应先修正 tag，再继续后续 dry-run 或 push。

## 首次 stable 发布

首次 stable 发布要同时完成两个目标：

- 创建正式的 GitHub Release
- 在 npm 上创建 `@zsa233/frida-analykit-agent` 的真实 stable 包

推荐原则：

- 不发布空包占位
- 首次发布直接发布真实 stable 版本
- RC 如果使用，仍然只做 GitHub prerelease 和本地 tarball 验证

推荐流程：

1. 默认直接在发布分支上切到 stable：

```sh
make release-version-stable BASE_VERSION=X.Y.Z CHECK=1
make release-local RELEASE_TAG=vX.Y.Z
make release-install-check RELEASE_TAG=vX.Y.Z
```

2. 通过 `workflow_dispatch` 触发 `.github/workflows/release.yml`，传入 `vX.Y.Z` 做远程 dry-run。
   dry-run 只执行 build，并上传 `release-bundle-vX.Y.Z` artifact。
   进入这一步之前，必须先确认当前 `release/vX.Y.Z` 的 `CI` 已经通过。
3. 如果 npm Trusted Publishing 已经可用，则直接按“后续 stable 流程”执行。
4. 如果 npm 上还没有该包，或者 npm 侧还不能完成 Trusted Publishing 绑定，就把这次 stable 作为一次手动 bootstrap：

```sh
gh release create vX.Y.Z dist/*.tar.gz dist/*.whl dist/*.apk *.tgz
npm publish ./zsa233-frida-analykit-agent-X.Y.Z.tgz --access public
```

5. 首发成功后，到 npm 包设置里把 trusted publisher 绑定到 `.github/workflows/release.yml`。
6. 从下一个 stable 开始，直接走自动化 stable 发布流程。

自动 stable 发布的 `publish` job 需要使用支持 Trusted Publishing 的较新 npm CLI。
仓库 workflow 会在发布前升级 npm；如果看到带 provenance 的 `npm publish` 仍返回误导性的 `E404`，先检查 job 实际使用的 npm 版本，而不是先怀疑 package scope 或 tarball 内容。

## RC 流程

RC 用于公开验证。RC 只创建 GitHub prerelease，不发布 npm。只有在发布操作者或用户明确要求“先 RC，再 stable”时，才进入这条流程。

步骤如下：

1. 在发布分支上切到目标 RC：

```sh
make release-version-rc BASE_VERSION=X.Y.Z RC=N CHECK=1
make release-local RELEASE_TAG=vX.Y.Z-rc.N
make release-install-check RELEASE_TAG=vX.Y.Z-rc.N
```

2. 至少手动验证 `legacy-16` 和 `current-17` 两套环境：
   - `doctor`
   - `server install`
   - `build`
   - `attach --detach-on-load`
3. 把 RC 版本切换结果提交到发布分支：

```sh
git add README.md README_EN.md \
  packages/frida-analykit-agent/README.md \
  packages/frida-analykit-agent/README_EN.md \
  release-version.toml src/frida_analykit/_version.py \
  package.json packages/frida-analykit-agent/package.json package-lock.json
git commit -m "release: cut vX.Y.Z-rc.N"
git tag vX.Y.Z-rc.N
test "$(git rev-parse HEAD)" = "$(git rev-parse vX.Y.Z-rc.N)"
```

4. 如需在不提前公开 RC tag 的前提下做远程 dry-run，可先把 RC commit 推到当前目标版本对应的临时分支，再通过 `workflow_dispatch` 触发 `.github/workflows/release-rc.yml`：

```sh
git push origin HEAD:refs/heads/tmp/release-vX.Y.Z-rc.N
gh workflow run "Release RC" --ref tmp/release-vX.Y.Z-rc.N -f tag=vX.Y.Z-rc.N
```

   dry-run 只执行 build，并上传 `release-bundle-vX.Y.Z-rc.N` artifact。
   不要为了方便随意推与当前目标版本无关的其他 `tmp/` 分支；如果确有必要，必须先向用户说明并得到明确同意。
   进入这一步之前，必须先确认当前 `release/vX.Y.Z` 的 `CI` 已经通过；如果 RC fix 后又有新提交，也应重新确认最新 release ref 的 CI 状态。
5. dry-run 通过后，再 push `vX.Y.Z-rc.N`。
6. push RC tag 后，`Release RC` 工作流会：
   - 复用 `.github/actions/release-bundle/action.yml`
   - 执行 `make release-preflight`
   - 执行 `make release-local`
   - 执行 `make release-install-check`
   - 创建 GitHub prerelease
   - 上传 `dist/*.tar.gz`、`dist/*.whl`、`dist/*.apk` 和 `*.tgz`
7. RC prerelease 成功后，流程必须在这里停下：
   - 向用户汇报 RC tag、workflow 结果、已完成的手工验证和待验证事项
   - 等待用户明确回复“继续 stable”后，才允许进入 stable 版本切换、stable dry-run 和正式发布
8. 若使用了临时 dry-run 分支，可在 RC tag 成功 push 后删除该临时分支。
9. 如果 RC 需要修复，在同一发布分支继续提交，递增 `rc.N` 后重新执行流程；每次 RC 成功发布后，都应再次停在该检查点等待用户决定是否继续 stable。

如果当前发布设备明确不支持某个受测 profile，不要为了凑流程在不支持的设备上反复尝试。此时应：

- 优先完成当前设备可支持 profile 的手工验证
- 明确记录未验证 profile、无法验证的原因和影响范围
- 不要把“设备不支持某个 Frida 大版本”误判成 release 工具链回归

如果示例 app 本身会快速退出、冷启动不稳定或 attach 窗口很短，不要让业务 app 的时序噪音主导 RC 结论。发布 smoke 的目标是验证工具链，因此可以改用设备上稳定常驻的系统 app 作为 `attach --detach-on-load` 手工验证目标，例如 `com.android.settings`。

RC 阶段的 bug 处理规则：

- 如果发现的是很小的 bug，且可以明确控制在 RC 阶段修复范围内，可以在 RC 分支修复后继续验证和发布。
- RC 修复后，仍应重新执行对应的本地检查、dry-run 和 RC 发布流程；必要时递增 `rc.N`。
- 不要把“RC 阶段允许修小 bug”理解成“任何问题都可以边发版边修”。

## stable 流程

stable 是正式发布。默认情况下，stable 不要求先有 RC；只有在你明确选择了“RC -> stable”提升路线时，stable 才是从已接受的 RC 提升出来。

当 stable 走显式 RC 提升路线时，只允许保留版本元数据差异，允许变动的路径为：

- `release-version.toml`
- `src/frida_analykit/_version.py`
- `package.json`
- `packages/frida-analykit-agent/package.json`
- `package-lock.json`

步骤如下：

1. 在发布分支上切到 stable：

```sh
make release-version-stable BASE_VERSION=X.Y.Z CHECK=1 [RC_TAG=vX.Y.Z-rc.N]
make release-local RELEASE_TAG=vX.Y.Z
make release-install-check RELEASE_TAG=vX.Y.Z
```

2. 把 stable 版本元数据变更单独提交到发布分支：

```sh
git add release-version.toml src/frida_analykit/_version.py \
  package.json packages/frida-analykit-agent/package.json package-lock.json
git commit -m "release: cut vX.Y.Z"
```

3. 通过 `workflow_dispatch` 触发 `.github/workflows/release.yml`，传入 `vX.Y.Z` 做远程 dry-run。
   dry-run 只执行 build，并上传 `release-bundle-vX.Y.Z` artifact。
4. 如果本次走的是显式 RC 提升路线，则 stable dry-run 之前，远端仓库必须已经存在可从当前发布分支追溯到的 RC tag `vX.Y.Z-rc.N`；否则 `validate-promotion` 会报 `No RC tag found for stable release vX.Y.Z`。
   如果本次是默认 direct stable，不需要先有 RC tag，也不执行 promotion 校验。
5. dry-run 通过后，再创建并 push `vX.Y.Z`：

```sh
git tag vX.Y.Z
test "$(git rev-parse HEAD)" = "$(git rev-parse vX.Y.Z)"
git push origin vX.Y.Z
```

6. push stable tag 后，`Release` 工作流会：
   - 复用 `.github/actions/release-bundle/action.yml`
   - 执行 `make release-preflight`
   - 执行 `make release-local`
   - 执行 `make release-install-check`
   - 上传 `release-bundle-vX.Y.Z` artifact
7. build 成功后，工作流会等待 `production` environment 审批。
8. 审批通过后，publish 任务会：
   - 下载 `release-bundle-vX.Y.Z`
   - 创建 GitHub Release
   - 执行 `npm publish release-bundle/*.tgz --access public --provenance`
9. stable 发布成功后，把 `release/vX.Y.Z` 合并回 `main`，再按需要回灌到对应开发线。

## 发版中断策略

在 preflight、dry-run、RC 验证、stable 提升或 publish 前后，只要发现严重 bug，就应立即停止当前发版流程，不要立刻边发版边修。

发现严重 bug 时应明确向用户反馈：

1. 问题出现在哪个阶段。
2. 问题具体出现在什么位置。
3. 影响范围是什么。
4. 发布风险是否高。
5. 为什么当前不适合继续发布。

“严重 bug” 包括但不限于：

- 发布物缺失、损坏或不可安装
- 关键主流程不可用
- 版本元数据、tag、release 契约或产物映射错误
- 兼容性判断明显错误并可能导致错误发布
- 文档、产物和真实行为严重不一致，足以误导公开用户

如果问题严重到会影响发布正确性，stable 阶段必须停止，而不是临时修补后直接继续提升。

## 发布前环境准备

发布前至少准备两套验证环境，对应 `compat_profiles.json` 中的受测 profile。

推荐命令：

```sh
make env-create FRIDA_VERSION=16.5.9 ENV_NAME=legacy-16
make env-create FRIDA_VERSION=17.8.2 ENV_NAME=current-17
make env-enter ENV_NAME=legacy-16
make env-enter ENV_NAME=current-17
```

也可以使用 CLI：

```sh
frida-analykit env create --profile legacy-16
frida-analykit env create --profile current-17
frida-analykit env list
frida-analykit env use legacy-16
frida-analykit env shell
```

常用验证命令：

```sh
.frida-analykit/envs/legacy-16/bin/python -m frida_analykit doctor
PYTHON_BIN=.frida-analykit/envs/legacy-16/bin/python make dev-smoke
.frida-analykit/envs/current-17/bin/python -m frida_analykit server install --config config.yml --version 17.8.2
```

## 手动兜底

只有在以下情况才使用手动流程：

- GitHub Actions 不可用
- 首次 stable 需要手动 bootstrap npm 包

即使走手动兜底，也应先确保本地三步校验已经通过。

stable GitHub Release：

```sh
gh release create vX.Y.Z dist/*.tar.gz dist/*.whl dist/*.apk *.tgz
```

RC GitHub prerelease：

```sh
gh release create vX.Y.Z-rc.N dist/*.tar.gz dist/*.whl dist/*.apk *.tgz --prerelease
```

stable npm 发布：

```sh
npm publish ./zsa233-frida-analykit-agent-X.Y.Z.tgz --access public
```

RC 不发布 npm。



## 常见QA

### 1. 显式 RC 提升的 stable 远程 dry-run 找不到 RC

现象：

- GitHub Actions 的 stable dry-run 在 `validate-promotion` 阶段失败
- 日志出现 `No RC tag found for stable release vX.Y.Z`

根因：

- 远端仓库还没有 `vX.Y.Z-rc.N` tag
- 虽然本地已经完成 RC，但 remote `workflow_dispatch` 只能看到远端 refs

确定的解决方案：

- 只有在显式 RC 提升路线下，stable dry-run 前才需要先确保 RC tag 已 push 到远端
- stable `workflow_dispatch` 使用的 `--ref` 必须能追溯到该 RC tag
- 如果本次不需要 RC 提升，就不要传 `RC_TAG`，直接按 direct stable 流程执行

### 2. 文档变更混进 stable promotion

现象：

- `validate-promotion` 报 stable 只允许版本元数据差异，但 diff 中出现 `README.md`、`README_EN.md`、`packages/frida-analykit-agent/README.md`、`packages/frida-analykit-agent/README_EN.md`

根因：

- README 收束没有在 RC 之前完成
- 或者 README 变更发生在 RC tag 之后

确定的解决方案：

- 四份 README 的收束和双语镜像校对都必须在 RC 之前完成
- 从 RC 切到 stable 时，只允许保留版本元数据差异

### 3. 发布设备不支持某个受测 profile

现象：

- 当前设备无法启动或稳定运行某个 Frida 大版本
- 例如设备只支持 `16.x`，不支持 `17.x`

根因：

- 设备能力与 `compat_profiles.json` 中的全部受测 profile 不完全重合

确定的解决方案：

- 不要把这种硬件/设备限制误判成 release 回归
- 完成当前设备可支持 profile 的手工验证
- 在发布记录中明确说明未覆盖 profile、原因和影响范围

### 4. 示例 app 本身太不稳定，导致 attach 结论失真

现象：

- `attach --detach-on-load` 报目标进程不存在
- 但同一套 server / runtime / bundle 在稳定进程上可以正常注入

根因：

- 被测 app 自身冷启动快退、attach 窗口过短，不能代表发布链路本身

确定的解决方案：

- 发布 smoke 验证的目标是工具链，而不是业务 app
- 如果示例 app 时序不稳定，可改用稳定系统 app 做 `attach --detach-on-load` 验证

# 发布流程

本仓库现在对每个 tag 只发布一组标准产物：

- 1 个 Python 源码包 `sdist`
- 1 个 Python wheel
- 1 个 npm tarball

历史上按 Frida 精确版本拆分的多 wheel GitHub Release 只保留为历史资产；新版本不再生成这类矩阵，也不再提供 backfill 工作流。

## 前置条件

首次公开发布前，先确认以下事项：

1. 在 GitHub 仓库中配置 `production` environment。
   需要启用 reviewer 审核，并打开 `Prevent self-review`。
2. 为 `@zsa233/frida-analykit-agent` 配置 npm Trusted Publishing。
   只绑定到 `.github/workflows/release.yml`。
3. 保持 `.nvmrc` 指向日常开发和构建使用的 Node 版本。
   stable 发布任务仍会在 publish 阶段切换到 `Node 22.14.0` 以满足 npm trusted publishing。
4. 把支持范围的真源放在 `pyproject.toml` 的 `frida>=...,<...` 直接依赖里。
5. 把受测 profile 的真源放在 `src/frida_analykit/resources/compat_profiles.json`。
   发布前校验会要求 profile 范围完全落在 `pyproject.toml` 声明的支持范围内。

## 日常开发

仓库内开发优先使用 repo-local managed env。新环境默认创建在 `.frida-analykit/envs/` 下；旧的 `.venv-*` 只会被当作 legacy 环境自动发现，不再是默认创建路径。

`make dev-env` 现在只显示帮助，不再接受旧的 `DEV_ENV_ARGS=...` 用法。仓库内推荐命令如下：

```sh
make dev-env
make dev-env-list
make dev-env-gen FRIDA_VERSION=16.5.9 ENV_NAME=legacy-16
make dev-env-gen FRIDA_VERSION=17.8.2 ENV_NAME=current-17
make dev-env-enter ENV_NAME=legacy-16
make dev-env-remove ENV_NAME=legacy-16
```

如果你需要不依赖仓库 helper 的通用流程，可以使用 CLI 的全局环境管理：

```sh
frida-analykit env create --profile legacy-16
frida-analykit env create --profile current-17
frida-analykit env list
frida-analykit env use legacy-16
frida-analykit env shell
```

说明：

- `make dev-env-gen` 默认会安装仓库开发所需的 `dev + repl` 依赖；如果不需要 REPL，可加 `NO_REPL=1`。
- `frida-analykit env create` 默认安装 `repl`，但不会安装仓库的 `dev` 依赖组。
- `make dev-env-enter` 和 `frida-analykit env shell` 都会打开一个子 shell。
- `frida-analykit env use <name>` 只切换 current 环境指针，不会修改当前 shell。

直接使用已创建的 repo-local 环境时，路径应是：

```sh
.frida-analykit/envs/legacy-16/bin/python -m frida_analykit doctor
PYTHON_BIN=.frida-analykit/envs/legacy-16/bin/python make dev-smoke
```

`doctor` 现在会明确报告：

- `tested`
- `supported but untested`
- `unsupported`

当设备侧 `frida-server` 需要与当前 Python 环境中的 Frida 版本对齐时，显式安装对应版本：

```sh
.frida-analykit/envs/current-17/bin/python -m frida_analykit server install --config config.yml --version 17.8.2
```

开发阶段如果要在不发布 npm 的前提下验证 runtime tarball，可执行：

```sh
npm pack ./packages/frida-analykit-agent
.frida-analykit/envs/current-17/bin/python -m frida_analykit gen dev \
  --work-dir /tmp/my-agent \
  --agent-package-spec file:./zsa233-frida-analykit-agent-2.0.0.tgz
```

## RC 流程

首次公开验证使用 RC。`main` 不是公开分发通道。

1. 从 `main` 拉出 `release/vX.Y.Z`。
2. 把版本号调整为 RC 形式：
   - git tag 目标：`vX.Y.Z-rc.N`
   - Python `__version__`：`X.Y.ZrcN`
   - 根 `package.json` 版本：`X.Y.Z-rc.N`
   - runtime `package.json` 版本：`X.Y.Z-rc.N`
   - 根项目对 `@zsa233/frida-analykit-agent` 的依赖：`^X.Y.Z-rc.N`
3. 运行本地发布校验：

```sh
make release-preflight RELEASE_TAG=vX.Y.Z-rc.N
make release-local RELEASE_TAG=vX.Y.Z-rc.N
make release-install-check RELEASE_TAG=vX.Y.Z-rc.N
```

这些命令当前分别负责：

- `release-preflight`
  校验支持范围与 compat profile、校验 tag 和 Python/npm 版本映射、执行 `npm ci`、运行非 smoke/scaffold 测试、并执行 `npm run agent:build`。
- `release-local`
  只构建一份 `sdist`、一份 wheel，以及一份 npm tarball；不再构建 Frida 精确 pin 的 wheel 矩阵。
- `release-install-check`
  在干净环境中用最小支持 Frida 版本做安装验证：
  先分别安装 `sdist` 和 wheel，再执行 `doctor`，最后用本地 npm tarball 运行一次 `frida-analykit gen dev`。

4. 至少手动验证 `legacy-16` 和 `current-17` 两套环境：
   - `doctor`
   - `server install`
   - `build`
   - `attach --detach-on-load`
5. 通过 `workflow_dispatch` 触发 `Release RC`，传入拟发布 tag 做远程 dry-run。
   dry-run 只执行 build 任务，并上传 `release-bundle-<tag>` artifact。
6. dry-run 通过后，再 push `vX.Y.Z-rc.N`。
7. push RC tag 后，工作流会创建 GitHub prerelease，并上传三类资产：
   - `dist/*.tar.gz`
   - `dist/*.whl`
   - `*.tgz`
8. RC 不会自动发布 npm。
   npm 消费验证应基于 prerelease 中的本地 tarball。
9. 如果 RC 反馈需要修复，在 `release/vX.Y.Z` 上继续提交，递增 `rc.N` 后重新执行以上流程。
   不要复用旧的 RC tag。

## Stable 流程

stable 是从已接受的 RC 提升出来的正式发布。接受某个 RC 之后，到 stable tag 之间只允许保留版本元数据差异。

允许在 RC 之后继续变动的路径：

- `src/frida_analykit/_version.py`
- `package.json`
- `packages/frida-analykit-agent/package.json`
- `package-lock.json`

stable 步骤：

1. 继续在同一个 `release/vX.Y.Z` 分支上工作。
2. 把版本号改回 stable 形式：
   - git tag 目标：`vX.Y.Z`
   - Python `__version__`：`X.Y.Z`
   - 根项目和 runtime 的 npm 版本：`X.Y.Z`
   - 根项目对 `@zsa233/frida-analykit-agent` 的依赖：`^X.Y.Z`
3. 再跑一遍本地发布校验：

```sh
make release-preflight RELEASE_TAG=vX.Y.Z
make release-local RELEASE_TAG=vX.Y.Z
make release-install-check RELEASE_TAG=vX.Y.Z
```

4. 通过 `workflow_dispatch` 触发 `Release`，传入 stable tag 做远程 dry-run。
5. dry-run 通过后，再 push `vX.Y.Z`。
6. push stable tag 后，build 任务会复用 `.github/actions/release-bundle/action.yml`，统一执行：
   - `make release-preflight`
   - `make release-local`
   - `make release-install-check`
7. build 任务成功后，会上传内部 `release-bundle-<tag>` artifact，然后等待 `production` environment 审批。
8. 审批通过后，publish 任务会：
   - 下载前一步的 `release-bundle`
   - 创建 GitHub Release
   - 使用 trusted publishing 执行 `npm publish release-bundle/*.tgz --access public --provenance`
9. stable 发布成功后，把 `release/vX.Y.Z` 合并回 `main`。

## 手动兜底

只有在 GitHub Actions 不可用时才使用手动流程。即使走手动兜底，也应先确保本地三步校验已经通过。

stable GitHub Release：

```sh
gh release create vX.Y.Z dist/*.tar.gz dist/*.whl *.tgz
```

RC GitHub prerelease：

```sh
gh release create vX.Y.Z-rc.N dist/*.tar.gz dist/*.whl *.tgz --prerelease
```

stable npm 发布：

```sh
npm publish ./zsa233-frida-analykit-agent-X.Y.Z.tgz --access public --provenance
```

RC 仍然保持 npm 本地验证，不要手动发布 RC npm 包。

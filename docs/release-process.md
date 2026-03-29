# 发布流程

每个 release tag 会产出以下发布物：

- 1 个 Python 源码包 `sdist`
- 1 个 Python wheel
- 1 个 npm tarball

## 分支约定

发布工作在冻结分支上完成，不要求必须从 `main` 直接发布。

推荐约定：

1. 日常开发在线上版本分支推进，例如 `dev/v2`。
2. 准备某个具体版本发布时，从当前冻结代码线切出或继续使用 `release/vX.Y.Z`。
3. RC 和 stable 的版本切换、校验、打 tag 都在 `release/vX.Y.Z` 上完成。
4. stable 发布完成后，把 `release/vX.Y.Z` 合并回 `main`。
5. 如果仍有长期开发线，例如 `dev/v2`，再把 `main` 的发布结果回灌回去。

## 一次性准备

首次公开发布前，先确认以下事项：

1. 在 GitHub 仓库中配置 `production` environment。
   需要启用 reviewer 审核，并打开 `Prevent self-review`。
2. 确认 npm scope 和包名所有权已经就绪。
   runtime 包名固定为 `@zsa233/frida-analykit-agent`。
3. 保持 `.nvmrc` 指向仓库构建使用的 Node 版本。
   stable 发布任务会在 publish 阶段切换到 `Node 22.14.0`。
4. 把支持范围的真源放在 `pyproject.toml` 的 `frida>=...,<...` 直接依赖里。
5. 把受测 profile 的真源放在 `src/frida_analykit/resources/compat_profiles.json`。
6. 把发布版本真源放在 `release-version.toml`。
   该文件只驱动发布关键文件，不自动修改 README / docs 中的安装示例。
7. 为 stable 自动发布配置 npm Trusted Publishing。
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
make release-version-stable BASE_VERSION=X.Y.Z CHECK=1 RC_TAG=vX.Y.Z-rc.N
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

## 首次 stable 发布

首次 stable 发布要同时完成两个目标：

- 创建正式的 GitHub Release
- 在 npm 上创建 `@zsa233/frida-analykit-agent` 的真实 stable 包

推荐原则：

- 不发布空包占位
- 首次发布直接发布真实 stable 版本
- RC 仍然只做 GitHub prerelease 和本地 tarball 验证

推荐流程：

1. 先完成至少一个 RC，并确认该 RC 可接受。
2. 在发布分支上切回 stable：

```sh
make release-version-stable BASE_VERSION=X.Y.Z CHECK=1 RC_TAG=vX.Y.Z-rc.N
make release-local RELEASE_TAG=vX.Y.Z
make release-install-check RELEASE_TAG=vX.Y.Z
```

3. 通过 `workflow_dispatch` 触发 `.github/workflows/release.yml`，传入 `vX.Y.Z` 做远程 dry-run。
   dry-run 只执行 build，并上传 `release-bundle-vX.Y.Z` artifact。
4. 如果 npm Trusted Publishing 已经可用，则直接按“后续 stable 流程”执行。
5. 如果 npm 上还没有该包，或者 npm 侧还不能完成 Trusted Publishing 绑定，就把这次 stable 作为一次手动 bootstrap：

```sh
gh release create vX.Y.Z dist/*.tar.gz dist/*.whl *.tgz
npm publish ./zsa233-frida-analykit-agent-X.Y.Z.tgz --access public
```

6. 首发成功后，到 npm 包设置里把 trusted publisher 绑定到 `.github/workflows/release.yml`。
7. 从下一个 stable 开始，直接走自动化 stable 发布流程。

自动 stable 发布的 `publish` job 需要使用支持 Trusted Publishing 的较新 npm CLI。
仓库 workflow 会在发布前升级 npm；如果看到带 provenance 的 `npm publish` 仍返回误导性的 `E404`，先检查 job 实际使用的 npm 版本，而不是先怀疑 package scope 或 tarball 内容。

## RC 流程

RC 用于公开验证。RC 只创建 GitHub prerelease，不发布 npm。

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
3. 通过 `workflow_dispatch` 触发 `.github/workflows/release-rc.yml`，传入 `vX.Y.Z-rc.N` 做远程 dry-run。
   dry-run 只执行 build，并上传 `release-bundle-vX.Y.Z-rc.N` artifact。
4. dry-run 通过后，再 push `vX.Y.Z-rc.N`。
5. push RC tag 后，`Release RC` 工作流会：
   - 复用 `.github/actions/release-bundle/action.yml`
   - 执行 `make release-preflight`
   - 执行 `make release-local`
   - 执行 `make release-install-check`
   - 创建 GitHub prerelease
   - 上传 `dist/*.tar.gz`、`dist/*.whl` 和 `*.tgz`
6. 如果 RC 需要修复，在同一发布分支继续提交，递增 `rc.N` 后重新执行流程。

## stable 流程

stable 是从已接受的 RC 提升出来的正式发布。

从 RC 切到 stable 时，只允许保留版本元数据差异，允许变动的路径为：

- `release-version.toml`
- `src/frida_analykit/_version.py`
- `package.json`
- `packages/frida-analykit-agent/package.json`
- `package-lock.json`

步骤如下：

1. 在同一个发布分支上切回 stable：

```sh
make release-version-stable BASE_VERSION=X.Y.Z CHECK=1 RC_TAG=vX.Y.Z-rc.N
make release-local RELEASE_TAG=vX.Y.Z
make release-install-check RELEASE_TAG=vX.Y.Z
```

2. 通过 `workflow_dispatch` 触发 `.github/workflows/release.yml`，传入 `vX.Y.Z` 做远程 dry-run。
   dry-run 只执行 build，并上传 `release-bundle-vX.Y.Z` artifact。
3. dry-run 通过后，再 push `vX.Y.Z`。
4. push stable tag 后，`Release` 工作流会：
   - 复用 `.github/actions/release-bundle/action.yml`
   - 执行 `make release-preflight`
   - 执行 `make release-local`
   - 执行 `make release-install-check`
   - 上传 `release-bundle-vX.Y.Z` artifact
5. build 成功后，工作流会等待 `production` environment 审批。
6. 审批通过后，publish 任务会：
   - 下载 `release-bundle-vX.Y.Z`
   - 创建 GitHub Release
   - 执行 `npm publish release-bundle/*.tgz --access public --provenance`
7. stable 发布成功后，把 `release/vX.Y.Z` 合并回 `main`，再按需要回灌到对应开发线。

## 发布前环境准备

发布前至少准备两套验证环境，对应 `compat_profiles.json` 中的受测 profile。

推荐命令：

```sh
make dev-env-gen FRIDA_VERSION=16.5.9 ENV_NAME=legacy-16
make dev-env-gen FRIDA_VERSION=17.8.2 ENV_NAME=current-17
make dev-env-enter ENV_NAME=legacy-16
make dev-env-enter ENV_NAME=current-17
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
gh release create vX.Y.Z dist/*.tar.gz dist/*.whl *.tgz
```

RC GitHub prerelease：

```sh
gh release create vX.Y.Z-rc.N dist/*.tar.gz dist/*.whl *.tgz --prerelease
```

stable npm 发布：

```sh
npm publish ./zsa233-frida-analykit-agent-X.Y.Z.tgz --access public
```

RC 不发布 npm。

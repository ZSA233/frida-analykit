# Release Process

This repository ships one tool release per tag, with multiple Frida-pinned wheel assets under the same GitHub Release.

## Prerequisites

Before the first public release:

1. Configure a GitHub `production` environment for this repository.
   Require reviewers before deployment and enable `Prevent self-review`.
2. Configure npm Trusted Publishing for `@zsa233/frida-analykit-agent`.
   Bind it to `.github/workflows/release.yml` only.
3. Keep `.nvmrc` on the development/build Node version.
   The stable publish job already switches to `Node 22.14.0` because npm trusted publishing requires a newer Node/npm runtime.
4. Do not enable public backfill expectations until at least one stable GitHub Release exists.

## Daily Development

Prepare one virtual environment per compatibility profile:

```sh
make dev-env DEV_ENV_ARGS='--profile legacy-16'
make dev-env DEV_ENV_ARGS='--profile current-17'
```

Or prepare a custom versioned environment:

```sh
make dev-env DEV_ENV_ARGS='--frida-version 17.8.2 --env-name .venv-frida-17.8.2'
```

Use the selected environment directly:

```sh
.venv-legacy16/bin/python -m frida_analykit doctor
PYTHON_BIN=.venv-legacy16/bin/python make dev-smoke
```

When device-side `frida-server` must match the active Python Frida version, pin it in `config.yml` or override it explicitly:

```sh
.venv-current17/bin/python -m frida_analykit server install --config config.yml --version 17.8.2
```

To validate the npm runtime during development without publishing it:

```sh
npm pack ./packages/frida-analykit-agent
.venv-current17/bin/python -m frida_analykit gen dev \
  --work-dir /tmp/my-agent \
  --agent-package-spec file:./zsa233-frida-analykit-agent-2.0.0.tgz
```

## RC Flow

Use RC releases for the first public validation round. `main` is not a public distribution channel.

1. Create `release/vX.Y.Z` from `main`.
2. Set versions for RC:
   - git tag target: `vX.Y.Z-rc.N`
   - Python `__version__`: `X.Y.ZrcN`
   - root `package.json` version: `X.Y.Z-rc.N`
   - runtime `package.json` version: `X.Y.Z-rc.N`
   - root dependency on `@zsa233/frida-analykit-agent`: `^X.Y.Z-rc.N`
3. Run local verification:

```sh
make release-preflight RELEASE_TAG=vX.Y.Z-rc.N
make release-local RELEASE_TAG=vX.Y.Z-rc.N
make release-install-check RELEASE_TAG=vX.Y.Z-rc.N
```

4. Manually validate at least the `legacy-16` and `current-17` environments:
   - `doctor`
   - `server install`
   - `build`
   - `attach --detach-on-load`
5. Trigger `Release RC` with `workflow_dispatch` and the proposed tag for a remote dry-run.
   Dry-run builds and uploads workflow artifacts only.
6. If the dry-run passes, push `vX.Y.Z-rc.N`.
   The RC workflow publishes a GitHub prerelease with the source archive, pinned wheels, and npm tarball.
7. RC does not publish npm automatically.
   Validate npm consumption with the local tarball from the prerelease artifacts.
8. If RC feedback requires changes, commit the fix on `release/vX.Y.Z`, bump `rc.N`, and repeat. Never reuse an RC tag.

## Stable Flow

Stable is a promotion from an accepted RC. Between the accepted RC and the stable tag, only version metadata changes are allowed.

Allowed post-RC diff paths:

- `src/frida_analykit/_version.py`
- `package.json`
- `packages/frida-analykit-agent/package.json`
- `package-lock.json`

Stable steps:

1. Keep working on the same `release/vX.Y.Z` branch.
2. Change versions back to the stable forms:
   - git tag target: `vX.Y.Z`
   - Python `__version__`: `X.Y.Z`
   - root/runtime npm versions: `X.Y.Z`
   - root dependency on `@zsa233/frida-analykit-agent`: `^X.Y.Z`
3. Run local verification again:

```sh
make release-preflight RELEASE_TAG=vX.Y.Z
make release-local RELEASE_TAG=vX.Y.Z
make release-install-check RELEASE_TAG=vX.Y.Z
```

4. Trigger `Release` with `workflow_dispatch` and the stable tag for a remote dry-run.
5. If dry-run passes, push `vX.Y.Z`.
6. The stable workflow builds everything first, uploads an internal artifact bundle, and then waits on the `production` environment gate.
7. After reviewers approve the `production` deployment, the publish job:
   - creates the GitHub Release
   - publishes `@zsa233/frida-analykit-agent` to npm with trusted publishing
8. Merge `release/vX.Y.Z` back to `main` after the stable release succeeds.

## Backfill

`Release Backfill` only targets stable GitHub Releases. It skips:

- draft releases
- prereleases / RC releases
- plain git tags with no GitHub Release

It always checks out the target tag before planning and building missing pinned wheels.

## Manual Fallback

Use the manual path only when GitHub Actions automation is unavailable.

GitHub Release fallback:

```sh
gh release create vX.Y.Z dist/*.tar.gz dist/*.whl *.tgz
gh release upload vX.Y.Z dist/*.whl --clobber
```

npm fallback:

```sh
npm publish ./zsa233-frida-analykit-agent-X.Y.Z.tgz --access public
```

RC fallback stays local-only for npm. Do not publish RC npm packages automatically while trusted publishing is bound to the stable workflow.

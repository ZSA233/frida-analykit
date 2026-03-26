.PHONY: sync test compat scaffold build npm-pack release-check release-preflight release-local release-install-check dev-env dev-smoke

RELEASE_TAG ?=
RC_TAG ?=
DIST_DIR ?= dist
DEV_ENV_ARGS ?=
PYTHON_BIN ?= .venv/bin/python

sync:
	uv sync --extra repl --dev

test:
	uv run pytest -m "not smoke and not scaffold"

compat:
	FRIDA_ANALYKIT_ENABLE_SMOKE=1 uv run pytest -m smoke

scaffold:
	FRIDA_ANALYKIT_ENABLE_NPM=1 uv run pytest -m scaffold

build:
	uv build

npm-pack:
	npm pack ./packages/frida-analykit-agent

release-check: test scaffold build npm-pack

release-preflight:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "RELEASE_TAG is required" >&2; exit 1; fi
	uv run python scripts/release_assets.py validate-config
	uv run python scripts/release_assets.py validate-release-version --tag "$(RELEASE_TAG)"
	@case "$(RELEASE_TAG)" in \
		v*-rc.*) ;; \
		*) if [ -n "$(RC_TAG)" ]; then \
			uv run python scripts/release_assets.py validate-promotion --tag "$(RELEASE_TAG)" --rc-tag "$(RC_TAG)"; \
		else \
			uv run python scripts/release_assets.py validate-promotion --tag "$(RELEASE_TAG)"; \
		fi ;; \
	esac
	npm ci
	uv run pytest -q -m "not smoke and not scaffold"
	npm run agent:build

release-local:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "RELEASE_TAG is required" >&2; exit 1; fi
	uv build --sdist
	npm pack ./packages/frida-analykit-agent
	@BUILD="$$(uv run python scripts/release_assets.py build-wheels --out-dir "$(DIST_DIR)" --json)"; \
	BUILT="$$(python -c 'import json,sys; payload=json.loads(sys.argv[1]); print(payload["built_count"])' "$$BUILD")"; \
	TOTAL="$$(python -c 'import json,sys; payload=json.loads(sys.argv[1]); print(payload["total_count"])' "$$BUILD")"; \
	test "$$BUILT" = "$$TOTAL"

release-install-check:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "RELEASE_TAG is required" >&2; exit 1; fi
	uv run python scripts/release_assets.py install-check --tag "$(RELEASE_TAG)" --dist-dir "$(DIST_DIR)"

dev-env:
	uv run python scripts/dev_env.py prepare $(DEV_ENV_ARGS)

dev-smoke:
	FRIDA_ANALYKIT_ENABLE_SMOKE=1 "$(PYTHON_BIN)" -m pytest tests/test_smoke.py -q -m smoke

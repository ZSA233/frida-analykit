.PHONY: sync test compat scaffold build npm-pack release-check release-preflight release-ci release-local release-install-check release-version-show release-version-rc release-version-stable env env-list env-create env-enter env-remove dev-smoke device-check device-test-core device-test-install device-test-repl-handlers device-test-attach-marker device-test device-test-all device-test-app-build device-test-app-install device-test-app-install-all

RELEASE_TAG ?=
RC_TAG ?=
CI_REF ?=
DIST_DIR ?= dist
PYTHON_BIN ?= .venv/bin/python
DEVICE_TEST_ENV = env FRIDA_ANALYKIT_ENABLE_DEVICE=1$(if $(strip $(DEVICE_TEST_APP)), FRIDA_ANALYKIT_DEVICE_APP=$(DEVICE_TEST_APP))$(if $(strip $(DEVICE_TEST_SKIP_APP)), FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS=$(DEVICE_TEST_SKIP_APP))

sync:
	uv sync --extra repl --dev

test:
	uv run pytest -m "not smoke and not scaffold and not device" -v

compat:
	FRIDA_ANALYKIT_ENABLE_SMOKE=1 uv run pytest -m smoke -v

scaffold:
	FRIDA_ANALYKIT_ENABLE_NPM=1 uv run pytest -m scaffold -v

build:
	uv build

npm-pack:
	npm pack ./packages/frida-analykit-agent

release-check: test scaffold build npm-pack

release-preflight:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "RELEASE_TAG is required" >&2; exit 1; fi
	uv run python scripts/release_version.py check-sync --tag "$(RELEASE_TAG)"
	uv run python scripts/release_assets.py validate-config
	uv run python scripts/release_assets.py validate-stable-entrypoints
	uv run python scripts/release_assets.py validate-release-version --tag "$(RELEASE_TAG)"
	$(if $(strip $(RC_TAG)),uv run python scripts/release_assets.py validate-promotion --tag "$(RELEASE_TAG)" --rc-tag "$(RC_TAG)")
	npm ci
	uv run pytest -x -vv -m "not smoke and not scaffold and not device"
	npm run agent:build

release-ci:
	uv run python scripts/release_ci.py $(if $(CI_REF),--ref "$(CI_REF)")

release-local:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "RELEASE_TAG is required" >&2; exit 1; fi
	uv build --sdist --wheel --out-dir "$(DIST_DIR)"
	npm pack ./packages/frida-analykit-agent
	uv run python scripts/release_assets.py stage-device-test-apk --tag "$(RELEASE_TAG)" --dist-dir "$(DIST_DIR)"

release-install-check:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "RELEASE_TAG is required" >&2; exit 1; fi
	uv run python scripts/release_assets.py install-check --tag "$(RELEASE_TAG)" --dist-dir "$(DIST_DIR)"

release-version-show:
	uv run python scripts/release_version.py show

release-version-rc:
	@if [ -z "$(BASE_VERSION)" ] || [ -z "$(RC)" ]; then \
		echo "Usage: make release-version-rc BASE_VERSION=<version> RC=<number> [CHECK=1]" >&2; \
		exit 2; \
	fi
	uv run python scripts/release_version.py set-rc --base "$(BASE_VERSION)" --rc "$(RC)" $(if $(filter 1,$(CHECK)),--check)

release-version-stable:
	@if [ -z "$(BASE_VERSION)" ]; then \
		echo "Usage: make release-version-stable BASE_VERSION=<version> [CHECK=1] [RC_TAG=<tag>]" >&2; \
		exit 2; \
	fi
	uv run python scripts/release_version.py set-stable --base "$(BASE_VERSION)" $(if $(filter 1,$(CHECK)),--check) $(if $(RC_TAG),--rc-tag "$(RC_TAG)")

env:
	uv run python scripts/env.py help

env-list:
	uv run python scripts/env.py list

env-create:
	@if [ -z "$(FRIDA_VERSION)" ]; then \
		echo "Usage: make env-create FRIDA_VERSION=<version> [ENV_NAME=<name>] [NO_REPL=1]" >&2; \
		exit 2; \
	fi
	uv run python scripts/env.py gen \
		--frida-version "$(FRIDA_VERSION)" \
		$(if $(ENV_NAME),--name "$(ENV_NAME)") \
		$(if $(NO_REPL),--no-repl)

env-enter:
	@if [ -z "$(ENV_NAME)" ]; then \
		echo "Usage: make env-enter ENV_NAME=<name>" >&2; \
		exit 2; \
	fi
	uv run python scripts/env.py enter --name "$(ENV_NAME)"

env-remove:
	@if [ -z "$(ENV_NAME)" ]; then \
		echo "Usage: make env-remove ENV_NAME=<name>" >&2; \
		exit 2; \
	fi
	uv run python scripts/env.py remove --name "$(ENV_NAME)"

dev-smoke:
	FRIDA_ANALYKIT_ENABLE_SMOKE=1 "$(PYTHON_BIN)" -m pytest tests/core/test_smoke.py -m smoke

device-check:
	$(DEVICE_TEST_ENV) "$(PYTHON_BIN)" -m pytest tests/device/test_preflight.py -m device -v

device-test-core:
	$(DEVICE_TEST_ENV) "$(PYTHON_BIN)" -m pytest tests/device/test_server_lifecycle.py tests/device/test_attach_marker.py -m device -v

device-test-install:
	$(DEVICE_TEST_ENV) "$(PYTHON_BIN)" -m pytest tests/device/test_server_install.py -m device -v

device-test-repl-handlers:
	$(DEVICE_TEST_ENV) "$(PYTHON_BIN)" -m pytest tests/device/test_repl_handles.py -m device -v

device-test-attach-marker:
	$(DEVICE_TEST_ENV) "$(PYTHON_BIN)" -m pytest tests/device/test_attach_marker.py -m device -v

device-test:
	$(DEVICE_TEST_ENV) "$(PYTHON_BIN)" -m pytest tests/device -m device -v

device-test-all:
	$(DEVICE_TEST_ENV) "$(PYTHON_BIN)" -m frida_analykit.device.orchestrator --make-target device-test

device-test-app-build:
	"$(PYTHON_BIN)" -m frida_analykit.device.test_app build

device-test-app-install:
	@if [ -z "$(ANDROID_SERIAL)" ]; then echo "ANDROID_SERIAL is required" >&2; exit 2; fi
	"$(PYTHON_BIN)" -m frida_analykit.device.test_app install --serial "$(ANDROID_SERIAL)"

device-test-app-install-all:
	"$(PYTHON_BIN)" -m frida_analykit.device.test_app install-all

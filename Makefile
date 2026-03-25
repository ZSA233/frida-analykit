.PHONY: sync test compat scaffold build npm-pack release-check

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

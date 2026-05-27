# Makefile for alert-light.
#
# This project is a Cloudflare Python Worker. The deploy lifecycle is driven
# by `pywrangler` (Cloudflare's Python wrapper around `wrangler`). All
# commands use `uv` to manage the local virtualenv and dev tools — install
# uv first if you don't have it: https://docs.astral.sh/uv/.
#
# Override variables on the command line, e.g.:
#   make deploy WORKER_ENV=production

UV          ?= uv
PYWRANGLER  := $(UV) run pywrangler
PYTEST      := $(UV) run pytest
RUFF        := $(UV) run ruff

PORT        ?= 8787
WORKER_ENV  ?=

# Direct LIFX smoke-test parameters. Override on the CLI, e.g.:
#   make flash COLOR=blue
#   make flash SELECTOR=label:Alert-Light
LIFX_API    ?= https://api.lifx.com/v1
SELECTOR    ?= label:Alert
COLOR       ?= red

# Cloudflare's Python Worker runtime (Pyodide) still passes the legacy Node
# flag `--experimental-wasm-stack-switching`, which was removed in Node 24+.
# We pin Node 22 (LTS, last release that accepts the flag) just for the
# pywrangler invocations — without touching the user's global `node` symlink.
# Install once: `brew install node@22`. The block below auto-detects it and
# prepends it to PATH only for `make dev` / `make deploy` / `make tail`.
NODE22_BIN  := $(firstword $(wildcard /opt/homebrew/opt/node@22/bin /usr/local/opt/node@22/bin))
WORKER_PATH := $(if $(NODE22_BIN),$(NODE22_BIN):$(PATH),$(PATH))

.DEFAULT_GOAL := help

# --- Help -----------------------------------------------------------------

.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- Dev environment ------------------------------------------------------

.PHONY: install
install: ## Install dev deps: Python (uv sync) + Node (wrangler) toolchains.
	$(UV) sync
	PATH="$(WORKER_PATH)" npm install --ignore-scripts

.PHONY: clean
clean: ## Remove caches and the local virtualenv.
	rm -rf .venv .pytest_cache .ruff_cache .wrangler node_modules
	find . -type d -name __pycache__ -exec rm -rf {} +

# --- Quality --------------------------------------------------------------

.PHONY: test
test: ## Run the pure-Python unit tests (no Worker runtime needed).
	$(PYTEST) -m "not integration"

.PHONY: test-integration
test-integration: ## Run integration tests against a local pywrangler dev server.
	$(PYTEST) -m integration

.PHONY: lint
lint: ## Lint with ruff.
	$(RUFF) check src tests

.PHONY: fmt
fmt: ## Auto-fix lint issues where possible.
	$(RUFF) check --fix src tests

# --- Local run ------------------------------------------------------------

.PHONY: dev
dev: ## Run the Worker locally with hot reload. Reads .dev.vars for secrets.
	@$(if $(NODE22_BIN),,echo "WARNING: node@22 not found. Install with 'brew install node@22' or pywrangler will fail on Node 24+.";)
	PATH="$(WORKER_PATH)" $(PYWRANGLER) dev --port $(PORT)

# --- LIFX smoke tests (direct, bypassing the Worker) ----------------------

.PHONY: flash
flash: ## Flash the bulb for ~5s via a direct LIFX API call. Bypasses the Worker; reads LIFX_TOKEN from .dev.vars.
	@test -f .dev.vars || { echo "ERROR: .dev.vars not found. Run 'cp .dev.vars.example .dev.vars' first."; exit 1; }
	@TOKEN=$$(grep '^LIFX_TOKEN=' .dev.vars | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"); \
		test -n "$$TOKEN" || { echo "ERROR: LIFX_TOKEN is empty in .dev.vars"; exit 1; }; \
		echo "Flashing $(SELECTOR) in $(COLOR) for ~5s..."; \
		curl -sS -X POST "$(LIFX_API)/lights/$(SELECTOR)/effects/pulse" \
			-H "Authorization: Bearer $$TOKEN" \
			-H "Content-Type: application/json" \
			-d '{"color":"$(COLOR)","period":0.5,"cycles":10,"power_on":true}' \
		| python3 -m json.tool

.PHONY: lifx-status
lifx-status: ## Show current state of the LIFX bulb(s) targeted by $$SELECTOR.
	@test -f .dev.vars || { echo "ERROR: .dev.vars not found."; exit 1; }
	@TOKEN=$$(grep '^LIFX_TOKEN=' .dev.vars | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"); \
		curl -sS -H "Authorization: Bearer $$TOKEN" "$(LIFX_API)/lights/$(SELECTOR)" \
		| python3 -c "import sys, json; d=json.load(sys.stdin); d=d if isinstance(d, list) else [d]; [print(f\"{b.get('label','?'):20s} connected={b.get('connected','?')} power={b.get('power','?')} effect={b.get('effect','?')}\") for b in d]"

# --- Cloudflare deployment ------------------------------------------------

.PHONY: cf-login
cf-login: ## Authenticate the Cloudflare CLI.
	$(PYWRANGLER) login

.PHONY: cf-whoami
cf-whoami: ## Show which Cloudflare account is currently authenticated.
	$(PYWRANGLER) whoami

.PHONY: deploy
deploy: ## Deploy the Worker to Cloudflare.
	PATH="$(WORKER_PATH)" $(PYWRANGLER) deploy $(if $(WORKER_ENV),--env $(WORKER_ENV),)

.PHONY: secrets
secrets: ## Prompt-push LIFX_TOKEN and SHARED_SECRET to the Worker (interactive).
	$(PYWRANGLER) secret put LIFX_TOKEN $(if $(WORKER_ENV),--env $(WORKER_ENV),)
	$(PYWRANGLER) secret put SHARED_SECRET $(if $(WORKER_ENV),--env $(WORKER_ENV),)

.PHONY: tail
tail: ## Tail the Worker logs from Cloudflare.
	PATH="$(WORKER_PATH)" $(PYWRANGLER) tail $(if $(WORKER_ENV),--env $(WORKER_ENV),)

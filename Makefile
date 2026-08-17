UV ?= uv
SOURCES_DIR ?= sources

.DEFAULT_GOAL := help

.PHONY: help install lint fmt typecheck test verify coverage coverage-real fetch verify-source \
        golden clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install the locked dependency set
	$(UV) sync --locked

lint: ## Static lint and format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt: ## Apply formatting and safe lint fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck: ## Strict type check
	$(UV) run mypy

test: ## Run the test suite with the coverage floor
	$(UV) run pytest

verify: install lint typecheck test ## Everything CI runs

coverage: ## Report parser coverage of the synthetic fixture
	$(UV) run ca-tariff-parse coverage tests/fixtures/SYNTHETIC-example-schedule-complete.txt

fetch: ## Download the published source documents (the only networked target)
	$(UV) run ca-tariff-parse fetch --dir $(SOURCES_DIR)

verify-source: ## Check local source documents against the manifest digests
	$(UV) run ca-tariff-parse verify-source --dir $(SOURCES_DIR)

golden: ## Regenerate golden output from the real documents (review every diff)
	@test -f $(SOURCES_DIR)/1-R-TOD.pdf || { echo "run 'make fetch' first"; exit 1; }
	$(UV) run ca-tariff-parse parse $(SOURCES_DIR)/1-R-TOD.pdf --id smud-r-tod \
		-o tests/golden/smud-r-tod.json
	$(UV) run ca-tariff-parse parse $(SOURCES_DIR)/1-R.pdf --id smud-r \
		-o tests/golden/smud-r.json
	$(UV) run ca-tariff-parse parse $(SOURCES_DIR)/CI-TOD1.pdf --id smud-ci-tod1 \
		-o tests/golden/smud-ci-tod1.json
	$(UV) run ca-tariff-parse parse $(SOURCES_DIR)/01_SSR.pdf --id smud-ssr \
		-o tests/golden/smud-ssr.json
	@echo "Golden files regenerated. Review every changed price before committing."

coverage-real: ## Report parser coverage of each fetched source document
	@for pair in smud-r-tod:1-R-TOD.pdf smud-r:1-R.pdf \
	             smud-ci-tod1:CI-TOD1.pdf smud-ssr:01_SSR.pdf; do \
		$(UV) run ca-tariff-parse coverage \
			$(SOURCES_DIR)/$${pair#*:} --id $${pair%%:*}; \
	done

clean: ## Remove build and test artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

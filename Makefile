UV ?= uv
SOURCES_DIR ?= sources

.DEFAULT_GOAL := help

.PHONY: help install lint fmt typecheck test verify coverage coverage-real fetch verify-source \
        golden watch watch-baseline clean

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

coverage: ## Report parser coverage of the synthetic fixtures
	$(UV) run ca-tariff-parse coverage tests/fixtures/SYNTHETIC-example-schedule-complete.txt
	$(UV) run ca-tariff-parse coverage \
		tests/fixtures/SYNTHETIC-example-keyword-schedule.txt --profile pge-tariff-book

fetch: ## Download the published source documents (the only networked target)
	$(UV) run ca-tariff-parse fetch --dir $(SOURCES_DIR)

verify-source: ## Check local source documents against the manifest digests
	$(UV) run ca-tariff-parse verify-source --dir $(SOURCES_DIR)

# Golden output is committed only for the first publisher's schedules. Most of
# each of the second publisher's is still carried verbatim in `notes`, so
# committing it would republish a document this repository deliberately does
# not redistribute. Those three are covered by the spot checks in
# tests/test_realdoc.py instead. See docs/adr/0003 and docs/adr/0006.
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
	             smud-ci-tod1:CI-TOD1.pdf smud-ssr:01_SSR.pdf \
	             pge-e-1:ELEC_SCHEDS_E-1.pdf pge-e-tou-c:ELEC_SCHEDS_E-TOU-C.pdf \
	             pge-b-1:ELEC_SCHEDS_B-1.pdf; do \
		$(UV) run ca-tariff-parse coverage \
			$(SOURCES_DIR)/$${pair#*:} --id $${pair%%:*}; \
	done

# The watch compares a publisher's current bytes against the last reviewed
# parse, committed under data/parsed/ without the document's verbatim prose.
# See docs/adr/0016.
watch: ## Download each pinned document and diff any publisher revision (networked)
	$(UV) run ca-tariff-parse watch

watch-baseline: ## Regenerate the watch baselines from the pinned documents (review every diff)
	@test -f $(SOURCES_DIR)/1-R-TOD.pdf || { echo "run 'make fetch' first"; exit 1; }
	$(UV) run ca-tariff-parse baseline --dir $(SOURCES_DIR)

clean: ## Remove build and test artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

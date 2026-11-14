PYTHON_VERSION := 3.14
UV := uv

.DEFAULT_GOAL := check

.PHONY: install format lint typecheck test test-fast eval-validate eval check pre-commit

install:
	$(UV) python install $(PYTHON_VERSION)
	$(UV) sync --locked --all-groups

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint:
	$(UV) run ruff format --check .
	$(UV) run ruff check .
	if [ -d scripts ]; then find scripts -type f -name '*.sh' -exec $(UV) run shellcheck {} +; fi

typecheck:
	$(UV) run ty check

test:
	$(UV) run pytest

# Full suite without coverage threshold, for quick iteration.
test-fast:
	$(UV) run pytest --no-cov

# Validate the ground-truth catalog; STRICT=1 adds --strict (issue #3, ADR 0005).
eval-validate:
	$(UV) run python eval/catalog.py $(if $(STRICT),--strict)

# Live evaluation run (issue #10, ADR 0005). Paid Gemini calls: this target does
# not set LIVE; the project owner exports LIVE=1 and GEMINI_API_KEY themselves.
# Example: make eval ARGS="--name smoke --case search-stable-001"
eval:
	$(UV) run python eval/run_eval.py run $(ARGS)

check: lint typecheck test

pre-commit:
	$(UV) run pre-commit run --all-files

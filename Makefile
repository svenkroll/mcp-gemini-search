PYTHON_VERSION := 3.14
UV := uv

.DEFAULT_GOAL := check

.PHONY: install format lint typecheck test check pre-commit

install:
	$(UV) python install $(PYTHON_VERSION)
	$(UV) sync --locked --all-groups

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint:
	$(UV) run ruff format --check .
	$(UV) run ruff check .

typecheck:
	$(UV) run ty check

test:
	$(UV) run pytest

check: lint typecheck test

pre-commit:
	$(UV) run pre-commit run --all-files

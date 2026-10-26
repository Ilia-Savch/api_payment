PYTHON ?= python

.PHONY: check lint format-check typecheck test migrate

check: lint format-check typecheck test

lint:
	$(PYTHON) -m ruff check .

format-check:
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

migrate:
	$(PYTHON) -m alembic upgrade head

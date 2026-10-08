.PHONY: check compile-data import-check test backend-dev frontend-dev

check:
	.venv/bin/ruff format --check .
	.venv/bin/ruff check .
	.venv/bin/mypy
	.venv/bin/pytest
	.venv/bin/python -m tools.compile_data --check
	cd frontend && npm run typecheck && npm test && npm run build

compile-data:
	.venv/bin/python -m tools.compile_data

import-check:
	.venv/bin/python -m tools.pokered_importer --map pallet_town --check

test:
	.venv/bin/pytest

backend-dev:
	.venv/bin/uvicorn backend.app.main:app --reload --port 8000

frontend-dev:
	cd frontend && npm run dev

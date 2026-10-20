.PHONY: check oracle-check source-check test backend-dev frontend-dev

check:
	.venv/bin/ruff format --check .
	.venv/bin/ruff check .
	.venv/bin/mypy
	.venv/bin/pytest
	.venv/bin/python -m tools.pokered_source_check
	cd frontend && npm run typecheck && npm test && npm run build

oracle-check:
	.venv/bin/python -m tools.pokered_oracle check

source-check:
	.venv/bin/python -m tools.pokered_source_check

test:
	.venv/bin/pytest

backend-dev:
	.venv/bin/uvicorn backend.app.main:app --reload --port 8000

frontend-dev:
	cd frontend && npm run dev

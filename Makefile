.PHONY: check test

check:
	.venv/bin/ruff format --check .
	.venv/bin/ruff check .
	.venv/bin/mypy
	$(MAKE) test

test:
	.venv/bin/pytest
	node --test sameboy/web/tests/*.test.js

.PHONY: lint format typecheck test check help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff linter
	uv run ruff check tasks/

format: ## Run ruff formatter
	uv run ruff format tasks/

typecheck: ## Run mypy type checker
	uv run mypy tasks/

test: ## Run pytest
	uv run pytest

check: ## Run all checks (lint + format check + typecheck + test)
	uv run ruff check tasks/
	uv run ruff format --check tasks/
	uv run mypy tasks/
	uv run pytest

.PHONY: help lint format typecheck test check install install-one status uninstall promote

# ─── Help ────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ─── Development ─────────────────────────────────────────────────────────────

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

# ─── Skill Management ───────────────────────────────────────────────────────

SKILL_DIR := skills
INSTALL_DIR := $(HOME)/.agent/skills
install: ## Install all skills (symlink to ~/.agent/skills/)
	@mkdir -p $(INSTALL_DIR)
	@for s in $(SKILL_DIR)/*/; do \
		s=$$(basename $$s); \
		if [ "$$s" = "_template" ]; then continue; fi; \
		if [ -L "$(INSTALL_DIR)/$$s" ]; then \
			echo "  ↻ $$s (already linked)"; \
		elif [ -d "$(INSTALL_DIR)/$$s" ]; then \
			echo "  ⚠ $$s (exists as real dir, skipping)"; \
		else \
			ln -sf $(CURDIR)/$(SKILL_DIR)/$$s $(INSTALL_DIR)/$$s; \
			echo "  ✓ $$s → linked"; \
		fi \
	done

install-one: ## Install one skill: make install-one SKILL=<name>
	@mkdir -p $(INSTALL_DIR)
	ln -sf $(CURDIR)/$(SKILL_DIR)/$(SKILL) $(INSTALL_DIR)/$(SKILL)
	@echo "✓ $(SKILL) → linked"

status: ## Show ~/.agent/skills/ link status
	@echo "=== ~/.agent/skills/ ==="
	@for s in $(INSTALL_DIR)/*/; do \
		name=$$(basename $$s); \
		if [ -L "$(INSTALL_DIR)/$$name" ]; then \
			target=$$(readlink "$(INSTALL_DIR)/$$name"); \
			echo "  🔗 $$name → $$target"; \
		else \
			echo "  📦 $$name (external)"; \
		fi \
	done

uninstall: ## Remove own symlinks from ~/.agent/skills/
	@for s in $(SKILL_DIR)/*/; do \
		s=$$(basename $$s); \
		if [ -L "$(INSTALL_DIR)/$$s" ]; then \
			rm "$(INSTALL_DIR)/$$s"; \
			echo "  ✗ $$s removed"; \
		fi \
	done

promote: ## Promote draft to skill: make promote SKILL=<name>
	@if [ -z "$(SKILL)" ]; then echo "Usage: make promote SKILL=name"; exit 1; fi
	mv drafts/$(SKILL) $(SKILL_DIR)/$(SKILL)
	$(MAKE) install-one SKILL=$(SKILL)
	@echo "✓ $(SKILL) promoted and linked"

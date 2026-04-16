.PHONY: help lint format typecheck test check install install-one status uninstall promote install-scheduler uninstall-scheduler scheduler-status build-tools

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

# ─── Build Tools ─────────────────────────────────────────────────────────────

BIN_DIR := bin

build-tools: ## Build all CLI binaries (Go)
	@mkdir -p $(BIN_DIR)
	@for d in cmd/*/; do \
		name=$$(basename $$d); \
		echo "  building $$name..."; \
		(cd $$d && go build -o $(CURDIR)/$(BIN_DIR)/$$name .) && echo "  ✓ $(BIN_DIR)/$$name" || echo "  ✗ $$name build failed"; \
	done

# ─── Skill Management ───────────────────────────────────────────────────────

SKILL_DIR := skills
INSTALL_DIR := $(HOME)/.agents/skills
install: build-tools ## Install all skills (symlink to ~/.agents/skills/) + build CLI tools
	@mkdir -p $(INSTALL_DIR)
	@for s in $(SKILL_DIR)/*/; do \
		s=$$(basename $$s); \
		if [ "$$s" = "_template" ]; then continue; fi; \
		if [ -L "$(INSTALL_DIR)/$$s" ] && [ ! -e "$(INSTALL_DIR)/$$s" ]; then \
			rm -f "$(INSTALL_DIR)/$$s"; \
			ln -sf $(CURDIR)/$(SKILL_DIR)/$$s $(INSTALL_DIR)/$$s; \
			echo "  ⚠ $$s → relinked (was dangling)"; \
		elif [ -L "$(INSTALL_DIR)/$$s" ]; then \
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

status: ## Show ~/.agents/skills/ link status grouped by type
	@if [ ! -d "$(INSTALL_DIR)" ] || [ -z "$$(ls -A $(INSTALL_DIR) 2>/dev/null)" ]; then \
		echo "=== ~/.agents/skills/ ==="; echo ""; echo "  (empty — run 'make install' first)"; exit 0; \
	fi; \
	echo "=== ~/.agents/skills/ ==="; \
	print_group() { \
		label=$$1; title=$$2; \
		found=0; \
		for s in $(INSTALL_DIR)/*/; do \
			name=$$(basename $$s); \
			skill_md="$(INSTALL_DIR)/$$name/SKILL.md"; \
			if [ ! -L "$(INSTALL_DIR)/$$name" ]; then continue; fi; \
			if [ ! -f "$$skill_md" ]; then continue; fi; \
			t=$$(grep -m1 '^type:' "$$skill_md" | sed 's/#.*//' | sed 's/type:[[:space:]]*//' | tr -d '[:space:]'); \
			if [ "$$t" = "$$label" ]; then \
				if [ $$found -eq 0 ]; then echo ""; echo "  [$$label] $$title"; found=1; fi; \
				target=$$(readlink "$(INSTALL_DIR)/$$name"); \
				echo "  🔗 $$name → $$target"; \
			fi; \
		done; \
	}; \
	print_group exec "可執行"; \
	print_group tool "工具型"; \
	print_group know "知識型"; \
	found_other=0; \
	for s in $(INSTALL_DIR)/*/; do \
		name=$$(basename $$s); \
		if [ -L "$(INSTALL_DIR)/$$name" ]; then \
			skill_md="$(INSTALL_DIR)/$$name/SKILL.md"; \
			if [ -f "$$skill_md" ]; then \
				t=$$(grep -m1 '^type:' "$$skill_md" | sed 's/#.*//' | sed 's/type:[[:space:]]*//' | tr -d '[:space:]'); \
				if [ "$$t" = "exec" ] || [ "$$t" = "tool" ] || [ "$$t" = "know" ]; then continue; fi; \
			fi; \
			target=$$(readlink "$(INSTALL_DIR)/$$name"); \
			if [ $$found_other -eq 0 ]; then echo ""; echo "  [?] 其他"; found_other=1; fi; \
			echo "  🔗 $$name → $$target"; \
		else \
			if [ $$found_other -eq 0 ]; then echo ""; echo "  [?] 其他"; found_other=1; fi; \
			echo "  📦 $$name (external)"; \
		fi; \
	done

uninstall: ## Remove own symlinks from ~/.agents/skills/
	@for s in $(SKILL_DIR)/*/; do \
		s=$$(basename $$s); \
		if [ -L "$(INSTALL_DIR)/$$s" ]; then \
			rm "$(INSTALL_DIR)/$$s"; \
			echo "  ✗ $$s removed"; \
		fi \
	done

install-scheduler: ## Install macOS LaunchAgent for scheduler (every 60s tick)
	uv run python -m tasks.scheduler install

uninstall-scheduler: ## Uninstall scheduler LaunchAgent
	uv run python -m tasks.scheduler uninstall

scheduler-status: ## Show scheduler job status
	uv run python -m tasks.scheduler status

promote: ## Promote draft to skill: make promote SKILL=<name>
	@if [ -z "$(SKILL)" ]; then echo "Usage: make promote SKILL=name"; exit 1; fi
	mv drafts/$(SKILL) $(SKILL_DIR)/$(SKILL)
	$(MAKE) install-one SKILL=$(SKILL)
	@echo "✓ $(SKILL) promoted and linked"

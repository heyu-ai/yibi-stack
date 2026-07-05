.PHONY: help lint lint-md format typecheck test check ci install install-project install-one install-force-one status status-own uninstall promote install-scheduler uninstall-scheduler scheduler-status build-tools install-handover-hooks uninstall-handover-hooks install-all patch-pr-review-agents patch-gemini-allow-list patch-agy-allow-list release

# ─── Help ────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ─── Development ─────────────────────────────────────────────────────────────

lint: ## Run ruff linter + markdown bash anti-pattern check + skill overlap check
	uv run ruff check tasks/ .claude/hooks/
	python3 scripts/lint_skill_bash.py
	python3 scripts/lint_skill_overlap.py

lint-md: ## Check bash anti-patterns in SKILL.md / commands markdown files
	python3 scripts/lint_skill_bash.py

format: ## Run ruff formatter
	uv run ruff format tasks/ .claude/hooks/

typecheck: ## Run mypy type checker
	uv run mypy tasks/

test: ## Run pytest
	uv run pytest

check: ## Run all checks (lint + format check + typecheck + test + markdown bash lint + skill overlap check)
	uv run ruff check tasks/ .claude/hooks/
	uv run ruff format --check tasks/ .claude/hooks/
	uv run mypy tasks/
	uv run pytest
	python3 scripts/lint_skill_bash.py
	python3 scripts/lint_skill_overlap.py

ci: ## 本地 CI fallback（pre-commit + tests；AgentShield security-scan 略過）
	@echo "━━━ [1/2] pre-commit（lint / format / type / security）━━━"
	uv run pre-commit run --all-files
	@echo ""
	@echo "━━━ [2/2] tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(MAKE) test
	@echo ""
	@echo "  ℹ  security-scan（AgentShield）：需 GitHub Actions 環境，本地略過"
	@echo ""
	@echo "[OK] 本地 CI 項目通過（pre-commit + tests）"

# ─── Build Tools ─────────────────────────────────────────────────────────────

BIN_DIR := bin

build-tools: ## Build all CLI binaries (Go)
	@mkdir -p $(BIN_DIR)
	@for d in cmd/*/; do \
		name=$$(basename $$d); \
		echo "  building $$name..."; \
		(cd $$d && go build -o $(CURDIR)/$(BIN_DIR)/$$name .) && echo "  [OK] $(BIN_DIR)/$$name" || echo "  [FAIL] $$name build failed"; \
	done

# ─── Skill Management ───────────────────────────────────────────────────────

SKILL_DIR := skills
CLAUDE_SKILL_DIR := $(HOME)/.claude/skills
INSTALL_DIR := $(HOME)/.agents/skills
CMD_DIR := commands
CLAUDE_CMD_DIR := $(HOME)/.claude/commands

install: ## Install scope=global skills to ~/.claude/skills/ + ~/.agents/skills/ + commands（跨專案可用）
	@mkdir -p "$(CLAUDE_SKILL_DIR)" || { echo "  [FAIL] Cannot create $(CLAUDE_SKILL_DIR) -- check permissions"; exit 1; }
	@mkdir -p "$(INSTALL_DIR)" || { echo "  [FAIL] Cannot create $(INSTALL_DIR) -- check permissions"; exit 1; }
	@for s in $(SKILL_DIR)/*/; do \
		name=$$(basename $$s); \
		if [ "$$name" = "_template" ] || [ "$$name" = "openspec" ]; then continue; fi; \
		skill_md="$(SKILL_DIR)/$$name/SKILL.md"; \
		if [ ! -f "$$skill_md" ]; then \
			echo "  [FAIL] $$name 缺少 SKILL.md"; exit 1; \
		fi; \
		scope=$$(grep -m1 '^scope:' "$$skill_md" | sed -e 's/scope:[[:space:]]*//' -e 's/[[:space:]]*#.*//' | tr -d '[:space:]'); \
		if [ -z "$$scope" ]; then \
			echo "  [FAIL] $$name 缺少 scope frontmatter（global|project），請在 SKILL.md 補上"; exit 1; \
		fi; \
		if [ "$$scope" != "global" ] && [ "$$scope" != "project" ]; then \
			echo "  [FAIL] $$name 的 scope 值無效（$$scope），只接受 global 或 project"; exit 1; \
		fi; \
		if [ "$$scope" != "global" ]; then continue; fi; \
		for dir in "$(CLAUDE_SKILL_DIR)" "$(INSTALL_DIR)"; do \
			$(CURDIR)/scripts/safe_symlink.sh "$(CURDIR)/$(SKILL_DIR)/$$name" "$$dir/$$name" || exit 1; \
		done \
	done
	@mkdir -p $(CLAUDE_CMD_DIR)
	@echo ""
	@echo "  Installing commands → $(CLAUDE_CMD_DIR)/"
	@for f in $(CMD_DIR)/*.md; do \
		name=$$(basename $$f); \
		if [ -L "$(CLAUDE_CMD_DIR)/$$name" ] && [ ! -e "$(CLAUDE_CMD_DIR)/$$name" ]; then \
			rm -f "$(CLAUDE_CMD_DIR)/$$name"; \
			ln -sf $(CURDIR)/$$f $(CLAUDE_CMD_DIR)/$$name; \
			echo "  [WARN] $$name -> relinked (was dangling)"; \
		elif [ -L "$(CLAUDE_CMD_DIR)/$$name" ]; then \
			echo "  ↻ $$name (already linked)"; \
		elif [ -f "$(CLAUDE_CMD_DIR)/$$name" ]; then \
			echo "  [WARN] $$name (exists as real file, skipping)"; \
		else \
			ln -sf $(CURDIR)/$$f $(CLAUDE_CMD_DIR)/$$name; \
			echo "  [OK] $$name -> linked"; \
		fi \
	done
	@if [ -d "$(CMD_DIR)/scripts" ]; then \
		$(CURDIR)/scripts/safe_symlink.sh "$(CURDIR)/$(CMD_DIR)/scripts" "$(CLAUDE_CMD_DIR)/scripts" || exit 1; \
	fi
	@echo ""
	@echo "  Registering skill_repo in ~/.agents/config.json"
	@python3 scripts/register_skill_repo.py '$(CURDIR)' \
	|| { echo "  [FAIL] 無法更新 ~/.agents/config.json（見上方錯誤）"; exit 1; }
	@echo "  [OK] skill_repo = $(CURDIR)"
	@mkdir -p "$$HOME/.agents/bin"
	@$(CURDIR)/scripts/safe_symlink.sh "$(CURDIR)/scripts/lessons" "$$HOME/.agents/bin/lessons"

install-project: ## Install scope=project skills（本 repo 限定，ainization-skill 開發用）
	@mkdir -p "$(CLAUDE_SKILL_DIR)" || { echo "  [FAIL] Cannot create $(CLAUDE_SKILL_DIR) -- check permissions"; exit 1; }
	@mkdir -p "$(INSTALL_DIR)" || { echo "  [FAIL] Cannot create $(INSTALL_DIR) -- check permissions"; exit 1; }
	@for s in $(SKILL_DIR)/*/; do \
		name=$$(basename $$s); \
		if [ "$$name" = "_template" ] || [ "$$name" = "openspec" ]; then continue; fi; \
		skill_md="$(SKILL_DIR)/$$name/SKILL.md"; \
		if [ ! -f "$$skill_md" ]; then \
			echo "  [FAIL] $$name 缺少 SKILL.md"; exit 1; \
		fi; \
		scope=$$(grep -m1 '^scope:' "$$skill_md" | sed -e 's/scope:[[:space:]]*//' -e 's/[[:space:]]*#.*//' | tr -d '[:space:]'); \
		if [ -z "$$scope" ]; then \
			echo "  [FAIL] $$name 缺少 scope frontmatter（global|project），請在 SKILL.md 補上"; exit 1; \
		fi; \
		if [ "$$scope" != "global" ] && [ "$$scope" != "project" ]; then \
			echo "  [FAIL] $$name 的 scope 值無效（$$scope），只接受 global 或 project"; exit 1; \
		fi; \
		if [ "$$scope" != "project" ]; then continue; fi; \
		for dir in "$(CLAUDE_SKILL_DIR)" "$(INSTALL_DIR)"; do \
			$(CURDIR)/scripts/safe_symlink.sh "$(CURDIR)/$(SKILL_DIR)/$$name" "$$dir/$$name" || exit 1; \
		done \
	done

install-one: ## Install one skill: make install-one SKILL=<name>
	@if [ -z "$(SKILL)" ]; then echo "[FAIL] SKILL 未指定，用法：make install-one SKILL=<name>"; exit 1; fi
	@mkdir -p "$(CLAUDE_SKILL_DIR)" || { echo "  [FAIL] Cannot create $(CLAUDE_SKILL_DIR)"; exit 1; }
	@mkdir -p "$(INSTALL_DIR)" || { echo "  [FAIL] Cannot create $(INSTALL_DIR)"; exit 1; }
	@$(CURDIR)/scripts/safe_symlink.sh "$(CURDIR)/$(SKILL_DIR)/$(SKILL)" "$(CLAUDE_SKILL_DIR)/$(SKILL)"
	@$(CURDIR)/scripts/safe_symlink.sh "$(CURDIR)/$(SKILL_DIR)/$(SKILL)" "$(INSTALL_DIR)/$(SKILL)"
	@echo "[OK] $(SKILL) -> done"

install-force-one: ## 強制安裝單一 skill，覆蓋 real directory（搶回被 gstack 蓋過的 skill）: make install-force-one SKILL=<name>
	@if [ -z "$(SKILL)" ]; then echo "[FAIL] SKILL 未指定，用法：make install-force-one SKILL=<name>"; exit 1; fi
	@mkdir -p "$(CLAUDE_SKILL_DIR)" || { echo "  [FAIL] Cannot create $(CLAUDE_SKILL_DIR)"; exit 1; }
	@mkdir -p "$(INSTALL_DIR)" || { echo "  [FAIL] Cannot create $(INSTALL_DIR)"; exit 1; }
	@$(CURDIR)/scripts/safe_symlink.sh --force "$(CURDIR)/$(SKILL_DIR)/$(SKILL)" "$(CLAUDE_SKILL_DIR)/$(SKILL)"
	@$(CURDIR)/scripts/safe_symlink.sh --force "$(CURDIR)/$(SKILL_DIR)/$(SKILL)" "$(INSTALL_DIR)/$(SKILL)"
	@echo "[OK] $(SKILL) -> done (forced)"

status: ## Show skill link status for ~/.claude/skills/ (Claude Code) and ~/.agents/skills/ (agents)
	@echo "=== ~/.claude/skills/  (Claude Code) ==="; \
	if [ ! -d "$(CLAUDE_SKILL_DIR)" ] || [ -z "$$(ls -A $(CLAUDE_SKILL_DIR) 2>/dev/null)" ]; then \
		echo "  (empty -- run 'make install' first)"; \
	else \
		found_global=0; found_project=0; found_ext=0; \
		for s in $(CLAUDE_SKILL_DIR)/*/; do \
			name=$$(basename $$s); \
			if [ ! -L "$(CLAUDE_SKILL_DIR)/$$name" ]; then \
				if [ $$found_ext -eq 0 ]; then echo "  [external]"; found_ext=1; fi; \
				echo "    📦 $$name (real dir)"; \
				continue; \
			fi; \
			target=$$(readlink "$(CLAUDE_SKILL_DIR)/$$name"); \
			skill_md="$(CLAUDE_SKILL_DIR)/$$name/SKILL.md"; \
			scope=""; \
			if [ -f "$$skill_md" ]; then \
				scope=$$(grep -m1 '^scope:' "$$skill_md" | sed -e 's/scope:[[:space:]]*//' -e 's/[[:space:]]*#.*//' | tr -d '[:space:]'); \
			fi; \
			if [ "$$scope" = "global" ]; then \
				if [ $$found_global -eq 0 ]; then echo "  [global]"; found_global=1; fi; \
				echo "    🔗 $$name"; \
			elif [ "$$scope" = "project" ]; then \
				if [ $$found_project -eq 0 ]; then echo "  [project]"; found_project=1; fi; \
				echo "    🔗 $$name"; \
			else \
				if [ $$found_ext -eq 0 ]; then echo "  [external / no-scope]"; found_ext=1; fi; \
				echo "    🔗 $$name → $$target"; \
			fi; \
		done; \
	fi; \
	echo ""; \
	echo "=== ~/.agents/skills/  (agents / agy) ==="; \
	if [ ! -d "$(INSTALL_DIR)" ] || [ -z "$$(ls -A $(INSTALL_DIR) 2>/dev/null)" ]; then \
		echo "  (empty -- run 'make install' first)"; \
	else \
		found_global=0; found_project=0; found_ext=0; \
		for s in $(INSTALL_DIR)/*/; do \
			name=$$(basename $$s); \
			if [ ! -L "$(INSTALL_DIR)/$$name" ]; then \
				if [ $$found_ext -eq 0 ]; then echo "  [external]"; found_ext=1; fi; \
				echo "    📦 $$name (real dir)"; \
				continue; \
			fi; \
			skill_md="$(INSTALL_DIR)/$$name/SKILL.md"; \
			scope=""; \
			if [ -f "$$skill_md" ]; then \
				scope=$$(grep -m1 '^scope:' "$$skill_md" | sed -e 's/scope:[[:space:]]*//' -e 's/[[:space:]]*#.*//' | tr -d '[:space:]'); \
			fi; \
			if [ "$$scope" = "global" ]; then \
				if [ $$found_global -eq 0 ]; then echo "  [global]"; found_global=1; fi; \
				echo "    🔗 $$name"; \
			elif [ "$$scope" = "project" ]; then \
				if [ $$found_project -eq 0 ]; then echo "  [project]"; found_project=1; fi; \
				echo "    🔗 $$name"; \
			else \
				if [ $$found_ext -eq 0 ]; then echo "  [external / no-scope]"; found_ext=1; fi; \
				target=$$(readlink "$(INSTALL_DIR)/$$name"); \
				echo "    🔗 $$name → $$target"; \
			fi; \
		done; \
	fi

status-own: ## Show install status for skills in THIS repo only (excludes gstack/external)
	@echo "=== yibi-stack skills (CC=~/.claude/skills, AG=~/.agents/skills) ==="; \
	echo ""; \
	if [ ! -d "$(SKILL_DIR)" ] || [ -z "$$(ls -A $(SKILL_DIR) 2>/dev/null)" ]; then \
		echo "  (skills/ is empty)"; \
	else \
		for s in $(SKILL_DIR)/*/; do \
			name=$$(basename $$s); \
			if [ "$$name" = "_template" ] || [ "$$name" = "openspec" ]; then continue; fi; \
			skill_md="$(SKILL_DIR)/$$name/SKILL.md"; \
			scope=""; \
			if [ -f "$$skill_md" ]; then \
				scope=$$(grep -m1 '^scope:' "$$skill_md" | sed -e 's/scope:[[:space:]]*//' -e 's/[[:space:]]*#.*//' | tr -d '[:space:]'); \
			fi; \
			own="$(CURDIR)/$(SKILL_DIR)/$$name"; \
			cc_target=$$(readlink "$(CLAUDE_SKILL_DIR)/$$name" 2>/dev/null); \
			ag_target=$$(readlink "$(INSTALL_DIR)/$$name" 2>/dev/null); \
			if [ "$$cc_target" = "$$own" ]; then cc_s="OK"; else cc_s="--"; fi; \
			if [ "$$ag_target" = "$$own" ]; then ag_s="OK"; else ag_s="--"; fi; \
			printf "  CC:%-2s AG:%-2s  %-30s [%s]\n" "$$cc_s" "$$ag_s" "$$name" "$$scope"; \
		done; \
	fi

uninstall: ## Remove own symlinks from ~/.claude/skills/ and ~/.agents/skills/
	@for s in $(SKILL_DIR)/*/; do \
		s=$$(basename $$s); \
		if [ "$$s" = "_template" ] || [ "$$s" = "openspec" ]; then continue; fi; \
		if [ -L "$(CLAUDE_SKILL_DIR)/$$s" ]; then \
			rm "$(CLAUDE_SKILL_DIR)/$$s" && echo "  [OK] $$s removed (Claude Code)" \
			    || echo "  [FAIL] $$s FAILED to remove from $(CLAUDE_SKILL_DIR)"; \
		fi; \
		if [ -L "$(INSTALL_DIR)/$$s" ]; then \
			rm "$(INSTALL_DIR)/$$s" && echo "  [OK] $$s removed (agents)" \
			    || echo "  [FAIL] $$s FAILED to remove from $(INSTALL_DIR)"; \
		fi \
	done

install-scheduler: ## Install macOS LaunchAgent for scheduler (every 60s tick)
	uv run python -m tasks.scheduler install

uninstall-scheduler: ## Uninstall scheduler LaunchAgent
	uv run python -m tasks.scheduler uninstall

scheduler-status: ## Show scheduler job status
	uv run python -m tasks.scheduler status

install-handover-hooks: ## 安裝 auto-handover PreCompact + SessionStart hook 到 ~/.claude/settings.json
	uv run python -m tasks.mycelium handover install-hooks

uninstall-handover-hooks: ## 移除 auto-handover PreCompact + SessionStart hook 從 ~/.claude/settings.json
	uv run python -m tasks.mycelium handover uninstall-hooks

patch-pr-review-agents: ## 為 pr-review-toolkit agents 加入 git -C 指令規範（plugin 更新後重跑）
	@bash scripts/patch-pr-review-agents.sh

patch-gemini-allow-list: ## [DEPRECATED] 舊版 gemini:* allow list patch；請改用 patch-agy-allow-list
	@python3 scripts/patch_gemini_allow_list.py

patch-agy-allow-list: ## 將 agy:* 加入 ~/.claude/settings.json allow list（mob review 免確認框）
	@python3 scripts/patch_agy_allow_list.py

release: ## Release: make release TYPE=patch|minor|major
	@if [ -z "$(TYPE)" ]; then echo "[FAIL] Usage: make release TYPE=patch|minor|major"; exit 1; fi
	@bash scripts/release-full.sh "$(TYPE)"

install-all: build-tools install install-project install-handover-hooks install-scheduler patch-pr-review-agents patch-agy-allow-list ## 一次裝齊 Go tools / skill（含 project）/ hook / scheduler / patch-pr-review-agents / patch-agy-allow-list（新環境首次設定用）

promote: ## Promote draft to skill: make promote SKILL=<name>
	@if [ -z "$(SKILL)" ]; then echo "Usage: make promote SKILL=name"; exit 1; fi
	mv drafts/$(SKILL) $(SKILL_DIR)/$(SKILL)
	$(MAKE) install-one SKILL=$(SKILL)
	@echo "[OK] $(SKILL) promoted and linked"

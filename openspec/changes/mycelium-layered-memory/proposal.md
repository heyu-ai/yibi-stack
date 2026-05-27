## Why

mycelium 從 handover -> lesson 的演進已驗證 typed schema 與自動 ingestion 路徑可行（70 handovers、3,801 insights）。但缺少「分層記憶」骨架，導致四個核心缺陷：過時 preference 無法降權造成雜訊累積、召回仍依賴 LIKE 在量大時效能崩潰、跨 bot 共用記憶缺信任加權、以及 input（hook 自動撈）與 output（retrieval timing）不對稱——記憶寫得進去但出不來。

## What Changes

- 引入四層記憶 tier（working / hot / cold / archival）並實作 `effective_weight` 衰減排序
- 新增 archival 降級機制：低頻記憶 demote 到 `~/.agents/archive/YYYY-MM.md` 而非刪除，索引保留可查
- 補齊三層 input trigger（Stop hook / PreCompact / agent 主動存）與五種 output trigger（Pull / Push by hook / Push by event / Dream surface / Cross-bot broadcast）
- 為每筆記憶加 `source_bot` 欄位，實作 bot trust scoring，並透過 `mycelium serve` 暴露 MCP server 供跨 bot 查閱
- 新增 `MemoryIndex` interface（SQLite FTS5 + sqlite-vec），支援語意向量召回；加 `--token-budget` 控制 context window 消耗

## Non-Goals

- 不實作 dream / consolidation skill（夜間批次整合，獨立提案）
- 不遷移既有 SQLite 資料到 gbrain（handover 70 < 150 觸發線，沿用前作結論）
- 不修改 cross-Agent adapter 介面（claude/codex/gemini 三家偵測機制維持不變）
- 不規劃 SQLite -> PostgreSQL 遷移（`MemoryIndex` interface 預留 pgvector adapter，遷移觸發條件見 design.md 風險表）

## Capabilities

### New Capabilities

- `mycelium-memory-tiers`：四層 tier 分類（working/hot/cold/archival）、`effective_weight` 排序公式、background promotion job、月度 archival export
- `mycelium-retrieval-trigger`：三層 input trigger + 五種 output trigger、PreCompact 強制摘要、SessionStart 自動 inject、PreToolUse 事件驅動 push
- `mycelium-bot-trust-mcp`：`source_bot` 欄位、bot trust scoring（四等級）、project scope 自動 pin、`mycelium serve` MCP stdio server（4 個 tool）
- `mycelium-semantic-recall`：`MemoryIndex` interface、SQLite FTS5 + sqlite-vec 後端、`--token-budget` recall 控制、tiktoken 估算

### Modified Capabilities

（無 -- 所有 capabilities 均為新增，既有 specs 目錄目前為空）

## Impact

- Affected specs: `mycelium-memory-tiers`、`mycelium-retrieval-trigger`、`mycelium-bot-trust-mcp`、`mycelium-semantic-recall`（4 個新 capabilities）
- Affected code:
  - Modified: `tasks/mycelium/models.py`（LessonRecord / HandoverRecord 加欄位）
  - Modified: `tasks/mycelium/db.py`（schema migration、`effective_weight` ranker）
  - Modified: `tasks/mycelium/lessons_service.py`（套用 `effective_weight`、`--include-cold`/`--include-archived` flag）
  - Modified: `tasks/mycelium/cli.py`（新增 `memory save`、`serve`、`--token-budget`、project scope flag）
  - Modified: `tasks/mycelium/recap_hook.py`（SessionStart inject hot lesson）
  - New: `tasks/mycelium/tier_service.py`（background promotion job）
  - New: `tasks/mycelium/archival.py`（月度 archival export）
  - New: `tasks/mycelium/retrieval_hooks.py`（PreToolUse / SessionStart push）
  - New: `tasks/mycelium/trust_scoring.py`（bot trust weight 計算）
  - New: `tasks/mycelium/mcp_server.py`（MCP stdio server）
  - New: `tasks/mycelium/semantic_index.py`（FTS5 + sqlite-vec wrapper）

## Layer 1 — User Stories

### US-001: Session 開始自動注入熱記憶

**Persona**: Claude Code 使用者，每次開新 session 都需要手動告訴 AI 過去的 preference / pitfall，期望改為自動注入
**Action**: 開啟新的 Claude Code session，不輸入任何額外指令
**Outcome**: Claude 在收到第一個 user 訊息前，已自動讀取並注入最近的 hot tier lesson

**Acceptance Criteria**:
- AC-001-1: GIVEN DB 有 ≥1 筆 tier="hot" lesson，WHEN SessionStart hook 觸發，THEN stdout 含「★ Recalled lessons:」開頭的文字，附 ≤3 筆 hot lesson 的 content
- AC-001-2: GIVEN DB 中 hot lesson 為 0 筆，WHEN SessionStart hook 觸發，THEN 不輸出任何文字（靜默）
- AC-001-3: GIVEN DB 有 5 筆 hot lesson，WHEN SessionStart hook 觸發，THEN 依 effective_weight 降序只取 top 3

### US-002: 帶 Token Budget 的精準召回

**Persona**: 使用 `mycelium handover-back` 的開發者，擔心大量 lesson 撐爆 context window
**Action**: `mycelium recall --token-budget 2000` 或 `mycelium handover-back --token-budget 2000`
**Outcome**: 回傳的 lessons 文字 token 總量不超過指定 budget，且按 effective_weight 由高到低排序

**Acceptance Criteria**:
- AC-002-1: GIVEN `--token-budget 500`，前 3 筆共 480 tokens，第 4 筆 100 tokens，WHEN 呼叫，THEN 只回傳前 3 筆
- AC-002-2: GIVEN `--mode procedural --token-budget 1000`，WHEN 呼叫，THEN 只回傳 lesson_type in ["tool","operational"] 且累計 token ≤ 1000
- AC-002-3: GIVEN `--token-budget 0`（預設）或未指定，WHEN 呼叫，THEN 不限 token，回傳所有符合條件 lesson

### US-003: 低頻記憶歸檔不刪除

**Persona**: 長期使用 mycelium 的開發者，希望舊記憶降權但不消失，日後仍可查閱
**Action**: `run_promotion_check()` 自動執行（由 SessionStart hook 觸發）
**Outcome**: age>365 天且 access_count=0 的 lesson 降級到 archival，export 到 `~/.agents/archive/YYYY-MM.md`，DB 中 `archived_path` 記錄位置，可用 `--include-archived` 查回

**Acceptance Criteria**:
- AC-003-1: GIVEN lesson `access_count=0, age=366 天`，WHEN `run_promotion_check()` 執行，THEN tier="archival"，archived_path 非 None，指向 `~/.agents/archive/YYYY-MM.md`
- AC-003-2: GIVEN tier="archival" 的 lesson，WHEN `get_lessons()` 不帶 include_archived=True，THEN 結果不含該 lesson
- AC-003-3: GIVEN tier="archival" 的 lesson，WHEN `get_lessons(include_archived=True)`，THEN 結果含該 lesson 且 archived_path 非空

### US-004: 跨 Bot 信任加權記憶共享

**Persona**: 同時使用 Claude 和 Codex 的開發者，希望兩個 bot 互相參考記憶但有信任等級控制
**Action**: Claude 透過 MCP server 查詢由 Codex 寫入的 lesson
**Outcome**: Codex 寫入的 lesson 標記 source_bot="codex"，Claude 查詢時 effective_weight 反映信任程度（unknown=0.4 或 trusted=0.7）

**Acceptance Criteria**:
- AC-004-1: GIVEN `source_bot="codex"`, `querying_agent="claude"`, `trusted_bots=[]`，WHEN `compute_bot_trust_weight()` 計算，THEN weight=0.4（unknown）
- AC-004-2: GIVEN `source_bot="codex"`, `trusted_bots=["codex"]`，WHEN 計算，THEN weight=0.7（trusted_other_bot）
- AC-004-3: GIVEN `source="user-stated"`（不論 source_bot），WHEN 計算，THEN weight=1.0（user_stated override）

## Layer 4 — Assumptions and Constraints

### Assumptions

| # | Assumption | Impact if False |
|---|------------|-----------------|
| A1 | Python 3.10+ and SQLite 3.38+ (FTS5 built-in) are available | FTS5 queries fail; need SQLite version check with user-friendly error |
| A2 | tiktoken `cl100k_base` is installable via pip | `--token-budget` unavailable; need graceful fallback to char-count estimate |
| A3 | `git` binary is in PATH for `resolve_project_slug()` | Project scope pin silently returns None; all lessons queried globally |
| A4 | The DB file at `~/.agents/agents.db` is writable | All write operations fail; need clear error message with DB path |
| A5 | SQLite WAL mode handles concurrent writes from parallel Claude sessions | Write serialization errors under high concurrency; Phase 4 PostgreSQL trigger |

### Hard Constraints

| # | Constraint | Source |
|---|-----------|--------|
| C1 | Schema migration uses `ALTER TABLE ADD COLUMN` with defaults; no backfill | Compatibility with 70 existing handovers + 3,801 insights |
| C2 | Archival files land at `~/.agents/archive/YYYY-MM.md`; not inside repo | Data privacy + gitignore rules |
| C3 | MCP server uses stdio transport; no standalone HTTP port | Zero network config; Claude Code MCP conventions |
| C4 | tiktoken uses `cl100k_base` encoding across all consumers | Consistent token estimation across Claude/Codex/Gemini |
| C5 | All SQL uses `?` parameterization; no f-string SQL construction | Security rule 03-security.md |

### Out of Scope

| Feature | Exclusion Reason | Future Consideration |
|---------|-----------------|----------------------|
| dream/consolidation skill | Separate proposal; different hook type needed | `/mycelium-dream` independent proposal |
| gbrain PostgreSQL migration | Handover < 150 trigger line not yet reached | After trigger conditions met |
| cross-Agent adapter rewrite | Existing claude/codex/gemini detection works | After multi-bot collaboration validated |
| SKILL.md update for plugins/growth | Separate PR after apply completes | After `/spectra-apply` implementation done |

## Layer 5 — Testability

### Definition of Done

This change is "done" when:
- [ ] All 17 tasks (T1.1–T5.1) have passing unit tests
- [ ] Schema migration SQL runs without error on `:memory:` DB
- [ ] `mycelium memory save "test lesson"` creates a DB record with tier="working"
- [ ] `mycelium handover-back --token-budget 500` returns lessons with total tokens ≤ 500
- [ ] `mycelium serve` starts and responds to `mycelium_search` MCP call
- [ ] All new modules pass `make typecheck` (mypy strict) and `make ci`

### Smoke Test Scenarios

**ST-001: memory save and recall (Phase 1 golden path)**
- GIVEN `mycelium memory save --tag pitfall "never cherry-pick after squash merge"` runs successfully
- WHEN `mycelium handover-back` is called from the same git repo directory
- THEN output contains "cherry-pick" (project-scoped, tier="working")

**ST-002: token budget enforced**
- GIVEN DB contains ≥10 lessons with total tokens > 500
- WHEN `mycelium recall --token-budget 500` is called
- THEN returned lesson count is fewer than 10 (budget stops append before limit)

**ST-003: tier promotion check**
- GIVEN a lesson with `access_count=3, tier="working"` in the DB
- WHEN `run_promotion_check()` runs
- THEN that lesson's `tier` becomes "hot"

**ST-004: archival export**
- GIVEN a lesson with `access_count=0` and `ts` older than 365 days
- WHEN `run_promotion_check()` runs
- THEN `~/.agents/archive/YYYY-MM.md` contains the lesson content and `archived_path` in DB is non-null

**ST-005: MCP server search**
- GIVEN `mycelium serve` is running as a subprocess
- WHEN MCP client calls `mycelium_search("git push")` via stdio
- THEN response is a valid JSON list (may be empty if no matching lessons)

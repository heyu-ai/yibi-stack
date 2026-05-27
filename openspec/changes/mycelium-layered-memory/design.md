## Context

mycelium 目前有 70+ handovers 與 3,801 insights，typed schema（LessonRecord、HandoverRecord）與自動 ingestion（Stop hook、insight_hook）已驗證可行。現有實作的三個核心限制：（1）所有 lesson 平等對待，無法依頻率或時效降權；（2）召回僅用 LIKE 模糊搜尋，量大效能崩；（3）記憶只能寫入，沒有 trigger 機制讓它在對的時機注入對話。

本設計引入「分層記憶」骨架，對應研究文件 `docs/research/2026-05-27-mycelium-layered-memory-design.md` 的 8 個借鏡點（A--H），以 4 個 capabilities 分層實作：tier 管理 -> archival 衰減 -> retrieval trigger -> vector 召回 -> MCP 服務。

## Goals / Non-Goals

**Goals:**

- 讓記憶可以依存取頻率自動分層（working / hot / cold / archival）並以 `effective_weight` 排序
- 低頻記憶降級到磁碟歸檔而不刪除，仍可 `--include-archived` 查閱
- 補齊 input / output trigger 的對稱性：寫入路徑（Stop hook / PreCompact / agent 主動）和讀取路徑（SessionStart inject / event 驅動 / cross-bot）同時存在
- 讓其他 bot 透過 MCP server 查閱 mycelium 記憶，並以 bot trust weight 調整排序
- 提供語意向量召回（sqlite-vec）並以 `--token-budget` 控制注入量

**Non-Goals:**

- dream / consolidation skill（episodic -> semantic 批次整合，獨立提案）
- gbrain 完整遷移（handover < 150 觸發線，維持 SQLite）
- SQLite -> PostgreSQL 遷移（`MemoryIndex` interface 預留 adapter，遷移觸發條件見風險表）
- cross-Agent adapter 介面重寫（claude/codex/gemini 三家偵測機制不動）
- auto-handover 三層防護機制重寫

## Decisions

### 四層 tier 分類與晉升規則

採用 working / hot / cold / archival 四層，對應人類記憶工作記憶 / 長期記憶 / 冷記憶 / 歸檔。

晉升規則：新 lesson -> working（TTL 7 天），`access_count >= 3` 晉升 hot，`access_count == 0 && age > 90 天` 降級 cold，`access_count == 0 && age > 365 天` 降級 archival。

備選：使用固定 TTL 而非 access_count 驅動。拒絕原因：TTL 無法區分「從未用過」與「最近才存進來」兩種情況，會把新鮮但未來會用的 lesson 提早降級。

### archival 不 delete

archival 降級時 demote 到 `~/.agents/archive/YYYY-MM.md`，原 DB 記錄保留 `archived_path` 欄位而非刪除。任何 bot 仍可 `--include-archived` 查到全文。

備選：直接 DELETE 記錄。拒絕原因：記憶被 overwrite 是資訊破壞，無法回溯；「歸檔不刪」與研究文件 §2 人類記憶「遺忘曲線只降權，不消滅記憶」的核心原則一致。

### effective_weight 公式

`effective_weight = confidence × decay(age) × log(access_count + 1) × bot_trust_weight`

其中 `decay(age)` 為指數衰減（半衰期 90 天）。公式各因子：

- `confidence`：來自 LessonRecord.confidence（已有欄位）
- `decay(age)`：時效衰減，age = `now - last_accessed_at`
- `log(access_count + 1)`：存取頻率對數平滑，防止高頻記憶過度壓制冷門但重要的記憶
- `bot_trust_weight`：user_stated = 1.0 / same_bot = 0.9 / trusted_other_bot = 0.7 / unknown = 0.4

備選：純 recency 排序（只看 last_accessed_at）。拒絕原因：無法區分「常用且新」與「剛存入從未用過」，boot-strapping 問題。

### bot trust 四等級

| 等級 | 條件 | weight |
|--|--|--|
| user_stated | source = user_stated | 1.0 |
| same_bot | source_bot == 目前 agent_type | 0.9 |
| trusted_other_bot | source_bot 在信任名單 | 0.7 |
| unknown | 其餘 | 0.4 |

初始信任名單由使用者在 config 中設定，預設為空（只信任自己和 user_stated）。

### MCP server 暴露 4 個 tool

`mycelium_search`（關鍵字 / 語意搜尋）、`mycelium_get_lesson`（by ID）、`mycelium_save_preference`（跨 bot 寫入 preference）、`mycelium_subscribe`（跨 bot broadcast subscribe）。

採用 MCP stdio server（`mycelium serve`），不架獨立 HTTP 服務。原因：stdio 模式零網路設定，與 Claude Code MCP server 設定一致，遷移到 HTTP 是後續觸發條件達成後的事。

### input / output trigger 對稱設計

input 三層：
1. Stop hook：session 結束自動撈 `★ Memory:` 標記
2. PreCompact hook：context 壓縮前強制摘要寫入 working tier
3. agent 主動：`mycelium memory save` CLI 子命令

output 五種：
1. Pull（agent 主動查）：`mycelium recall` CLI
2. Push by hook（SessionStart inject）：session 開始自動注入最近 3 條 hot lesson
3. Push by event（PreToolUse）：偵測 `git push` 等危險操作自動撈 pitfall lesson
4. Dream surface：SessionStart 顯示 dream digest（Phase 5，依賴 dream skill 落地）
5. Cross-bot broadcast：`mycelium_subscribe` MCP tool（Phase 4）

### vector store 選型

採用 sqlite-vec（SQLite 擴充），零外部依賴，與現有 SQLite DB 同檔案。抽象為 `MemoryIndex` interface（`embed` / `search` / `upsert` / `delete`）預留 gbrain / pgvector adapter。

備選：chromadb、qdrant、pgvector。拒絕原因：需獨立 process 或外部服務，違背「零外部依賴」原則；handover < 150 量不需要分散式向量庫。

## Implementation Contract

#### LessonRecord schema（新增欄位）

```
tier: Literal["working", "hot", "cold", "archival"] = "working"
last_accessed_at: datetime | None = None
access_count: int = 0
source_bot: str | None = None
archived_path: str | None = None
```

`HandoverRecord` 同樣新增 `source_bot: str | None = None`。

Schema migration 用 `ALTER TABLE ADD COLUMN` 加預設值，既有資料不需 backfill。

#### effective_weight ranker

`db.py` 新增 `compute_effective_weight(lesson: LessonRecord, now: datetime, agent_type: str) -> float` 函式，回傳 float，供 `lessons_service.py` 排序用。

`lessons_service.py` 的 `get_lessons()` 預設依 `effective_weight` 降序排列；加 `--include-cold`（包含 cold tier）與 `--include-archived`（包含 archived，需讀磁碟）兩個 flag。

#### MCP server contract

`mycelium serve` 啟動 stdio MCP server，暴露 4 個 tool：

- `mycelium_search(query: str, limit: int = 10, mode: str = "hybrid") -> list[LessonSummary]`
- `mycelium_get_lesson(lesson_id: str) -> LessonRecord | None`
- `mycelium_save_preference(content: str, tags: list[str] = []) -> str`（回傳 lesson_id）
- `mycelium_subscribe(event_type: str, callback_url: str | None = None) -> SubscriptionToken`

tool schema 嚴格遵循 MCP spec，`inputSchema` 為 JSON Schema。

#### CLI 新增子命令

- `mycelium memory save [--tier working] [--tag TAG]`：agent 主動存記憶
- `mycelium serve [--port PORT]`：啟動 MCP stdio server
- `mycelium recall [--token-budget N] [--mode {episodic|semantic|procedural}]`：帶 budget 的召回
- `mycelium handover-back [--global] [--token-budget N]`：`--global` flag 表示不 pin 到 project scope

#### Acceptance Criteria

- `spectra analyze mycelium-layered-memory --json` 無 Critical / Warning
- `spectra validate mycelium-layered-memory` pass
- schema migration SQL：`ALTER TABLE lessons ADD COLUMN tier TEXT NOT NULL DEFAULT 'working'` 等 5 行可在 `:memory:` DB 上執行無誤
- `mycelium serve` 啟動後，另一個 process `mycelium_search("git push pitfall")` 回傳非空 list
- `mycelium recall --token-budget 500` 回傳的 lessons token 估算不超過 500

#### Scope Boundaries

In scope: `tasks/mycelium/` 內的 models、db、service、hook、CLI、MCP server 實作

Out of scope: `plugins/growth/skills/mycelium/SKILL.md` 更新（SKILL.md 在 apply 完成後獨立更新）；dream skill 實作；gbrain adapter 實作

## Layer 3 — Data Model (Brownfield)

#### Conflict Detection

Baseline: `openspec/specs/` is empty; no existing capabilities. No naming conflicts. This is the first set of specs for mycelium.

#### Entity: LessonRecord (modified)

Current schema (from `tasks/mycelium/db.py` `CREATE TABLE lessons`):

| Field | Type | Constraints | Status |
|-------|------|-------------|--------|
| id | TEXT | PK | existing |
| ts | TEXT | NOT NULL | existing |
| project | TEXT | NOT NULL | existing |
| skill | TEXT | nullable | existing |
| type | TEXT | CHECK enum | existing |
| key | TEXT | NOT NULL, no spaces | existing |
| insight | TEXT | NOT NULL, min 10 chars | existing |
| confidence | INTEGER | CHECK 1-10 | existing |
| source | TEXT | CHECK enum | existing |
| trusted | INTEGER | NOT NULL DEFAULT 0 | existing |
| files | TEXT | NOT NULL DEFAULT '[]' (JSON) | existing |
| handover_id | TEXT | nullable | existing |
| retro_pr | INTEGER | nullable | existing |
| device | TEXT | nullable | existing |
| agent_type | TEXT | NOT NULL DEFAULT 'claude' | existing |

New fields to add via `ALTER TABLE ADD COLUMN`:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| tier | TEXT | 'working' | four-tier classification |
| last_accessed_at | TEXT | NULL | ISO timestamp, updated on read |
| access_count | INTEGER | 0 | cumulative retrieval count for promotion |
| source_bot | TEXT | NULL | agent type that wrote this record |
| archived_path | TEXT | NULL | path to `~/.agents/archive/YYYY-MM.md` when archived |

Migration SQL (idempotent via `ALTER TABLE ADD COLUMN` with default):

```sql
ALTER TABLE lessons ADD COLUMN tier TEXT NOT NULL DEFAULT 'working';
ALTER TABLE lessons ADD COLUMN last_accessed_at TEXT;
ALTER TABLE lessons ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lessons ADD COLUMN source_bot TEXT;
ALTER TABLE lessons ADD COLUMN archived_path TEXT;
```

Indexes to add:

```sql
CREATE INDEX IF NOT EXISTS idx_lessons_tier ON lessons(tier);
CREATE INDEX IF NOT EXISTS idx_lessons_access ON lessons(access_count, last_accessed_at);
```

#### Entity: HandoverRecord (modified)

New field:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| source_bot | TEXT | NULL | agent type that wrote this handover |

Migration SQL:

```sql
ALTER TABLE handovers ADD COLUMN source_bot TEXT;
```

#### Entity: subscriptions (new table)

| Field | Type | Constraints | Purpose |
|-------|------|-------------|---------|
| token | TEXT | PK | UUID subscription token |
| subscriber_bot | TEXT | NOT NULL | agent type subscribing |
| event_type | TEXT | NOT NULL | e.g., "new_lesson" |
| created_at | TEXT | NOT NULL | ISO timestamp |

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
  token          TEXT PRIMARY KEY,
  subscriber_bot TEXT NOT NULL,
  event_type     TEXT NOT NULL,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
```

#### Entity: lesson_embeddings (new table, Phase 4)

| Field | Type | Constraints | Purpose |
|-------|------|-------------|---------|
| lesson_id | TEXT | PK, FK -> lessons.id | embedding lookup key |
| embedding | BLOB | NOT NULL | float32 vector (sqlite-vec format) |

#### New Functions

#### `compute_effective_weight(lesson, now, bot_trust_weight) -> float`

Location: `tasks/mycelium/db.py`

```python
def compute_effective_weight(
    lesson: LessonRecord,
    now: datetime,
    bot_trust_weight: float,
) -> float:
    age_days = (now - lesson.last_accessed_at_or_ts).total_seconds() / 86400
    decay = 0.5 ** (age_days / 90)
    freq = math.log(lesson.access_count + 1)
    return lesson.confidence * decay * freq * bot_trust_weight
```

Note: `last_accessed_at_or_ts` returns `last_accessed_at` when set, falls back to `ts` (creation time).

This is DISTINCT from the existing `_apply_decay()` in `lessons_service.py`:
- `_apply_decay()`: integer decay (-1 per 30 days), used for existing `effective_confidence` (quality score)
- `compute_effective_weight()`: float exponential decay, used for ranking (sort key)

Both coexist; `effective_confidence` remains for quality filtering, `effective_weight` drives sort order.

#### API Schema (MCP Server Contract)

#### Tool: mycelium_search

```json
{
  "name": "mycelium_search",
  "description": "Search lessons by keyword or semantic query",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer", "default": 10},
      "mode": {"type": "string", "enum": ["keyword", "vector", "hybrid"], "default": "hybrid"}
    },
    "required": ["query"]
  }
}
```

Response: `list[LessonSummary]` where `LessonSummary = {id, content_preview, effective_weight, tier, tags}`

#### Tool: mycelium_get_lesson

```json
{
  "name": "mycelium_get_lesson",
  "inputSchema": {
    "type": "object",
    "properties": {"lesson_id": {"type": "string"}},
    "required": ["lesson_id"]
  }
}
```

Response: `LessonRecord | null`

#### Tool: mycelium_save_preference

```json
{
  "name": "mycelium_save_preference",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": {"type": "string"},
      "tags": {"type": "array", "items": {"type": "string"}, "default": []}
    },
    "required": ["content"]
  }
}
```

Response: `{"lesson_id": "<uuid>"}`

#### Tool: mycelium_subscribe

```json
{
  "name": "mycelium_subscribe",
  "inputSchema": {
    "type": "object",
    "properties": {"event_type": {"type": "string"}},
    "required": ["event_type"]
  }
}
```

Response: `{"token": "<uuid>", "event_type": "<event_type>"}`

## Risks / Trade-offs

| 風險 | 緩解 |
|--|--|
| access_count 計數在多 bot 並行寫時 WAL 鎖定 | Phase 4 觀察，若 > 10 次/分鐘才考慮 PostgreSQL；初期 SQLite WAL 模式已夠 |
| sqlite-vec 擴充安裝失敗（舊版 SQLite） | `MemoryIndex` interface 讓 FTS5-only fallback 成為合法後端；embed 失敗時 graceful degrade |
| bot trust 名單維護成本 | 預設只信任 user_stated + same_bot，trusted_other_bot 由使用者 opt-in；不強制 |
| working tier TTL 需要 Periodic hook | 目前 Claude Code 無內建 Periodic hook；改用 SessionStart hook 做 on-demand promotion check |
| SQLite -> PostgreSQL 觸發條件 | 三個觸發條件按優先序：① mycelium serve 需跨機器存取（架構觸發）② 多 bot 並行 WAL 鎖定 > 10 次/分鐘（行為觸發）③ embedding > 100K 行（量化觸發）；`MemoryIndex` interface 預留 pgvector adapter |
| cross-bot broadcast 無前例 | Phase 4 最後做，先驗證 SessionStart inject（Phase 1 T1.6）收集反饋 |

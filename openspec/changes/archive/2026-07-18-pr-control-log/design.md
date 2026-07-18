## Context

yibi-stack 的 mycelium 模組已有 `~/.agents/handover/handover.db`（SQLite WAL 模式），提供
handovers、handover_events、lessons 等資料表，並有 `AgentsDB.init_db()` 的 idempotent
schema migration 機制。`metrics_service.py` 已實現 `compute_stats` + `generate_advice` 模式。

問題：每次 PR 完成後，無法從客觀數據判斷 AI 的自主決定比例、規格偏離比例是否在可接受範圍，
亦無法跨 session 追蹤趨勢，進而決定是否需要補充 rules / hooks / skills。

## Goals / Non-Goals

**Goals:**

- 提供結構化方式記錄每個 PR 的 AI 行為審計 entry（11 個 schema 欄位）
- 跨 session 統計 autonomy_ratio、deviation_ratio、verification_score 四個核心指標
- 根據指標閾值產生 rule/hook/skill 建議
- 與 pr-retrospective SKILL.md 整合，在 Q5 actions 加入 control log 觸發點

**Non-Goals:**

- Phase 3：PostToolUse hook 即時自動 capture（留到下個 PR）
- GitHub Actions daily digest（CLI 統計足夠）
- control log 進入 mycelium lessons tier promotion（生命週期不同）

## Decisions

### 使用既有 mycelium DB，不開新 DB

**Why:** 減少維護成本；handover.db 已有 WAL mode 和 idempotent migration 機制，可直接複用。
`control_log_entries` 只存 `pr_number`（string），不 FK 到 handovers，讓 control log 可
獨立執行（不依賴 retro 流程先跑）。

**Alternatives considered:**
- 新開 `~/.agents/control_log.db`：多一個 DB 需要多一個 migration path，且無法與未來
  handover/lesson 關聯查詢。

### ControlLogCategory 作為 StrEnum

**Why:** 所有欄位值序列化為 string 存 DB，方便 CLI 讀取和 GROUP BY。類別固定為 7 個：
assumption / autonomous_decision / spec_deviation / tradeoff / irreversible_op /
verification / rollback。

### autonomy_ratio 分母設計

**Why:** `autonomy_ratio` = autonomous_decision count / (autonomous_decision +
user_requested=1 entries count)。分母不用 total_entries，避免純 assumption 或 verification
記錄稀釋分母，讓比例更能反映「AI 自主做了多少相對於明確要求」。

### markdown artifact 輸出到 .runtime/control-logs/

**Why:** 不 commit，讓人類在 PR review 期間可直接閱讀。格式使用參考 repo 的 11 個 section
（zh-TW 版），含 Surgical Change Traceability table 和 9 個 High-Risk Stop-Rule checklist。

### Skill 擺放在 plugins/pr-flow/skills/pr-control-log/

**Why:** 與 pr-retrospective 同層，共享 pr-flow plugin manifest，複用
`bootstrap.sh` / `detect-pr.sh` 模式。

## Implementation Contract

### CLI interface（`uv run python -m tasks.mycelium control-log <subcommand>`）

| Subcommand | Key options | Success output |
|-----------|-------------|----------------|
| `add` | `--pr N --category C --summary S --evidence E --user-requested 0\|1 [--severity low\|medium\|high] [--files '["f.py"]'] [--verification-status verified\|partial\|unverified] [--test-type mock\|unit\|integration\|live_smoke\|prod_verified] [--handover-id H] [--project P]` | `✓ 已寫入 control log entry (id=N)` |
| `show` | `--pr N [--project P]` | 表格列印該 PR 所有 entries，含 category / summary / severity |
| `stats` | `--since-days D [--by category\|project] [--json]` | 含 autonomy_ratio、deviation_ratio、irreversible_op_count、verification_score 的統計表；`--json` 輸出 JSON |
| `advice` | `--since-days D` | 按觸發規則列出 zh-TW 建議文字，無觸發時輸出「目前無建議」 |

### DB schema（兩個 CREATE TABLE IF NOT EXISTS）

```sql
CREATE TABLE IF NOT EXISTS control_log_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  session_id TEXT,
  pr_number INTEGER NOT NULL,
  project TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL,
  summary TEXT NOT NULL,
  evidence TEXT,
  user_requested INTEGER NOT NULL DEFAULT 0,
  severity TEXT,
  files_json TEXT,
  verification_status TEXT,
  test_type TEXT,
  handover_id TEXT
);
CREATE TABLE IF NOT EXISTS control_log_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  project TEXT NOT NULL DEFAULT '',
  autonomy_ratio REAL,
  deviation_ratio REAL,
  irreversible_op_count INTEGER,
  verification_score REAL,
  total_entries INTEGER
);
```

### Acceptance criteria

1. `uv run python -m tasks.mycelium control-log add --pr 1 --category assumption --summary "test" --user-requested 0` 成功執行，`show --pr 1` 可見該 entry
2. `stats --since-days 30 --json` 輸出含 `autonomy_ratio` / `deviation_ratio` / `verification_score` 的 JSON
3. `advice --since-days 30` 當 autonomy_ratio > 0.30 時輸出建議文字
4. `init_db()` 可冪等執行（第二次不出錯）
5. `pytest tasks/mycelium/tests/test_control_log_*.py` 全部通過

### Scope boundaries

In scope: control_log_entries 寫入/讀取、stats 計算、advice 輸出、skill SKILL.md、
pr-retrospective Q5 整合。

Out of scope: Phase 3 PostToolUse hook、control log entries 的 tier promotion、
GitHub Actions webhook。

## Risks / Trade-offs

- [Risk] 事後推論準確度有限：agent 無法完整回憶所有自主決定 → Mitigation: SKILL.md 提示
  agent 讀 git log + PR diff 作為 evidence 來源，使用者有 3 次校準機會
- [Risk] `autonomy_ratio` 分母在 PR entries 數很少時波動大 → Mitigation: `stats` 輸出時
  標注 `total_entries`，讓使用者自行判斷統計信度
- [Trade-off] 用 `.runtime/control-logs/` 取代 commit artifact：犧牲 git history，
  換取不汙染 repo 的優點——與 `.runtime/scheduler.db` 慣例一致

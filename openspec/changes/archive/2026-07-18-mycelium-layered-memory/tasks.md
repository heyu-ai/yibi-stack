## Phase 1 -- Foundation（先做，最小可行）

Phase 1 建立 source_bot 欄位和三層 input trigger 的基礎，無需 schema migration 大改動。

- [x] T1.1 [spec: source_bot field on memory records] 在 `tasks/mycelium/models.py` 的 `LessonRecord` 與 `HandoverRecord` 新增 `source_bot: str | None = None` 欄位；在 `tasks/mycelium/db.py` 執行 `ALTER TABLE lessons ADD COLUMN source_bot TEXT` 和 `ALTER TABLE handovers ADD COLUMN source_bot TEXT`，不需 backfill。驗收：`LessonRecord(content="x", source_bot="claude")` 可序列化為 JSON，且 `LessonRecord(content="x")` 不因缺少 source_bot 而 ValidationError。
- [x] T1.2 [spec: Project scope automatic pin] 在 `tasks/mycelium/registry.py` 中實作 `resolve_project_slug(cwd: Path) -> str | None`：呼叫 `git -C <cwd> rev-parse --show-toplevel`，取最後一段路徑作為 project slug；git 失敗時回傳 `None`。驗收：`resolve_project_slug(Path("/Users/me/projects/yibi-stack"))` 回傳 `"yibi-stack"`；非 git 目錄回傳 `None`。
- [x] T1.3 在 `tasks/mycelium/cli.py` 的 `handover-back` 指令加 `--global` flag（預設 False）；未加 `--global` 時呼叫 `resolve_project_slug(cwd)` 並將結果作為 `project` filter 傳給 `lessons_service.get_lessons()`。驗收：`mycelium handover-back`（無 `--global`）在 yibi-stack repo 內只回傳 `project="yibi-stack"` 的 lessons；加 `--global` 時回傳全部。
- [x] T1.4 [spec: Three-layer input trigger] 在 `tasks/mycelium/insight_hook.py` 或新建 `tasks/mycelium/retrieval_hooks.py` 實作 PreCompact hook handler：當 hook event type 為 `PreCompact` 時，提取 session 摘要並呼叫 `lessons_service.save_lesson(content=<摘要>, tier="working", source_bot=<agent_type>)`。驗收：mock PreCompact event 時，`save_lesson` 被呼叫一次且 `tier="working"`。
- [x] T1.5 [spec: Three-layer input trigger, Input/output trigger symmetry] 在 `tasks/mycelium/cli.py` 新增 `memory save` 子命令：`mycelium memory save [--tier working] [--tag TAG] CONTENT`，呼叫 `lessons_service.save_lesson(content=CONTENT, tier=tier, tags=tags, source_bot=<from env>)`。驗收：`mycelium memory save --tag pitfall "never cherry-pick after squash merge"` 在 DB 中建立一筆 `tier="working"` 且 `tags=["pitfall"]` 的 LessonRecord。
- [x] T1.6 [spec: Five-pattern output trigger] 在 `tasks/mycelium/recap_hook.py` 的 SessionStart handler 新增：呼叫 `lessons_service.get_lessons(tier_filter=["hot"], limit=3)` 並將結果格式化為 `★ Recalled lessons:\n- <content>` 的純文字，輸出到 stdout 供 Claude Code 注入 session context。驗收：DB 有 3 筆以上 hot lesson 時，SessionStart hook 輸出至少 1 筆「★ Recalled lessons:」開頭的文字。

## Phase 2 -- 分層記憶 + Archival

Phase 2 引入四層 tier、effective_weight ranker，以及 archival 月度 export。依賴 Phase 1 的 source_bot 欄位。

- [x] T2.1 [spec: Four-tier memory classification] 在 `tasks/mycelium/db.py` 執行 schema migration：`ALTER TABLE lessons ADD COLUMN tier TEXT NOT NULL DEFAULT 'working'`、`ADD COLUMN last_accessed_at TEXT`、`ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0`、`ADD COLUMN archived_path TEXT`。驗收：對 `:memory:` DB 執行 migration 後，`INSERT INTO lessons (...) VALUES (...)` 不需提供新欄位即可成功；`SELECT tier FROM lessons LIMIT 1` 回傳 `"working"`。
- [x] T2.2 在 `tasks/mycelium/tier_service.py` 實作 `run_promotion_check(db: MyceliumDB) -> PromotionResult`：對每筆 lesson 按規則判斷 tier 是否需升降級（working -> hot：access_count >= 3；working/hot -> cold：access_count == 0 && age > 90 天；cold -> archival：access_count == 0 && age > 365 天），執行 UPDATE，回傳升降級計數。驗收：`run_promotion_check` 在 `:memory:` DB 上正確分類 4 種邊界狀況（見 spec mycelium-memory-tiers § Example: tier transitions over time）。
- [x] T2.3 [spec: effective_weight ranking formula] 在 `tasks/mycelium/db.py` 實作 `compute_effective_weight(lesson: LessonRecord, now: datetime, bot_trust_weight: float) -> float`，公式：`confidence * decay(age) * log(access_count + 1) * bot_trust_weight`，`decay(age) = 0.5 ** (age_days / 90)`。在 `lessons_service.get_lessons()` 中以 `effective_weight` 降序作為預設排序。驗收：`compute_effective_weight` 對 spec §Example 中的範例數值計算結果誤差 < 0.001。
- [x] T2.4 [spec: Archival demotes without deletion] 在 `tasks/mycelium/archival.py` 實作 `archive_lesson(lesson: LessonRecord, db: MyceliumDB) -> Path`：將 lesson 完整內容寫入 `~/.agents/archive/YYYY-MM.md`（使用 archival 當下的 UTC 年月），更新 DB 中該 lesson 的 `archived_path` 欄位。驗收：呼叫 `archive_lesson` 後，`archived_path` 欄位非 None，且 `~/.agents/archive/YYYY-MM.md` 含有該 lesson 的 content。
- [x] T2.5 在 `tasks/mycelium/lessons_service.py` 的 `get_lessons()` 加 `include_cold: bool = False` 和 `include_archived: bool = False` 兩個參數：預設不回傳 cold/archival；加旗標後包含。驗收：`get_lessons(include_cold=False)` 不含 cold tier；`get_lessons(include_archived=True)` 含 archival tier 且 archived_path 欄位非空。

## Phase 3 -- Context Budget + Event-Driven Push

Phase 3 完善 output trigger（事件驅動 push）並加入 context window 預算控制。

- [x] T3.1 在 `tasks/mycelium/cli.py` 的 `handover-back` 指令加 `--token-budget N`（預設 0，表示無限制）；當 N > 0 時，呼叫 `lessons_service.get_lessons(token_budget=N)` 而非無限制版本。驗收：`mycelium handover-back --token-budget 500` 回傳的 lessons 文字總 tiktoken 估算不超過 500。
- [x] T3.2 [spec: Context window token budget recall] 在 `tasks/mycelium/lessons_service.py` 實作 `get_lessons(token_budget: int = 0, mode: str | None = None) -> list[LessonRecord]`：`mode` 對映 lesson_type filter（`episodic` -> handover summary；`semantic` -> pattern/architecture/investigation；`procedural` -> tool/operational）；`token_budget > 0` 時用 tiktoken `cl100k_base` 估算累計 token，超過 budget 就停止附加 lesson。驗收：`get_lessons(token_budget=500, mode="procedural")` 只回傳 tool/operational lesson，且累計 token <= 500。
- [x] T3.3 [spec: Five-pattern output trigger, Input/output trigger symmetry] 在 `tasks/mycelium/retrieval_hooks.py` 實作 PreToolUse hook handler：當 hook event 的 `tool_name` 為 `Bash` 且 `command` 含 `git push`（或其他可設定的危險指令），呼叫 `lessons_service.get_lessons(lesson_type="pitfall", tags=["git", "push"], limit=3)` 並輸出 warning 到 stdout。驗收：mock PreToolUse event 含 `"git push origin main"` 時，output 含「★ Pitfall warning:」字樣；`"git status"` 時不輸出。

## Phase 4 -- Vector + MCP（觸發條件達標再啟動）

Phase 4 在 handover 數量超過 150 或出現多 bot 協作需求時啟動。

- [x] T4.1 [spec: MemoryIndex interface] 在 `tasks/mycelium/semantic_index.py` 定義 `MemoryIndex` abstract class，包含 `embed`、`upsert`、`search`、`delete` 四個抽象方法；實作 `SqliteVecIndex(MemoryIndex)`：嘗試載入 sqlite-vec extension，若失敗則以 SQLite FTS5-only 模式初始化並 log WARNING。驗收：`SqliteVecIndex` 在 `:memory:` DB 上 `upsert("id1", "text")` 後，`search("text")` 回傳含 `"id1"` 的 list。
- [x] T4.2 [spec: SQLite FTS5 and sqlite-vec backend] 在 `tasks/mycelium/semantic_index.py` 實作 FTS5 + sqlite-vec hybrid search：RRF merging（k=60）合併兩個 result list；`mode="keyword"` 只跑 FTS5；`mode="vector"` 只跑 sqlite-vec；`mode="hybrid"` 合併兩者。驗收：`SqliteVecIndex.search("query", mode="keyword")` 只呼叫 FTS5 code path（可 mock vector search 驗證）。
- [x] T4.3 [spec: MCP server exposes four tools] 在 `tasks/mycelium/mcp_server.py` 實作 MCP stdio server：`mycelium serve` 啟動後，從 stdin 讀取 MCP JSON-RPC 請求，暴露 `mycelium_search`、`mycelium_get_lesson`、`mycelium_save_preference`、`mycelium_subscribe` 四個 tool，回應格式嚴格遵循 MCP spec（tool name、inputSchema、output type）。驗收：`mycelium serve` 啟動後，用 MCP client library 呼叫 `mycelium_search(query="test")` 可得 list 回應（可能為空）；呼叫不存在的 lesson_id 時 `mycelium_get_lesson` 回傳 `null` 而非 error。
- [x] T4.4 [spec: Bot trust scoring] 在 `tasks/mycelium/trust_scoring.py` 實作 `compute_bot_trust_weight(lesson: LessonRecord, querying_agent_type: str, trusted_bots: list[str]) -> float`，依照 spec mycelium-bot-trust-mcp 的四等級表計算。驗收：`compute_bot_trust_weight(lesson with source="user-stated", ...) == 1.0`；`compute_bot_trust_weight(lesson with source_bot="codex", querying="claude", trusted_bots=[]) == 0.4`；`trusted_bots=["codex"] == 0.7`。
- [x] T4.5 在 `tasks/mycelium/mcp_server.py` 實作 `mycelium_subscribe(event_type: str) -> SubscriptionToken`：儲存訂閱記錄到 `subscriptions` table（`subscriber_bot TEXT, event_type TEXT, created_at TEXT`），回傳 UUID token。cross-bot broadcast 的實際訊息推送為後續 Phase，本 task 只建立訂閱機制和 token 回傳。驗收：呼叫 `mycelium_subscribe(event_type="new_lesson")` 兩次，DB 中 subscriptions table 有 2 筆記錄，回傳的兩個 token 不同。

## Phase 5 -- Dream Surface（依賴 dream skill 落地後啟動）

- [x] T5.1 在 `tasks/mycelium/recap_hook.py` 的 SessionStart handler 中，加入 dream digest 顯示邏輯：檢查 `~/.agents/dreams/latest.md` 是否存在且距今 < 24 小時；若是，輸出 `★ Dream digest:\n<摘要前 200 字元>` 到 stdout。驗收：`latest.md` 存在且時間戳 < 24 小時時，SessionStart output 含「★ Dream digest:」；不存在或過期時不輸出。

## Notes

- Phase 1--3 不依賴 sqlite-vec，可在任何環境執行。
- Phase 4 啟動條件：handover > 150 或出現多 bot 協作需求。Phase 5 啟動條件：`/mycelium-dream` skill 獨立提案落地。
- 17 個 tasks 略超 Spectra 建議的 15 上限。理由：4 個 Phase 各自獨立可交付；mycelium 的 4 個 module 層（models/db、service、hook、CLI）屬於同一子系統，不計為 unrelated subsystems。
- `parallel_tasks` 未在 `.spectra.yaml` 啟用，不加 `[P]` 標記。

## Requirement Coverage

Spec-to-task traceability index（供 analyzer 交叉驗證）：

| Spec Requirement | Tasks | Design Decision |
|---|---|---|
| source_bot field on memory records | T1.1 | -- |
| Project scope automatic pin | T1.2, T1.3 | 四層 tier 分類與晉享規則（scope prerequisite） |
| Three-layer input trigger | T1.4, T1.5 | input / output trigger 對稱設計 |
| Five-pattern output trigger | T1.6, T3.3, T4.5, T5.1 | input / output trigger 對稱設計 |
| Input/output trigger symmetry | T1.4, T1.5, T1.6, T3.3 | input / output trigger 對稱設計 |
| Four-tier memory classification | T2.1, T2.2 | 四層 tier 分類與晉升規則 |
| effective_weight ranking formula | T2.3 | effective_weight 公式 |
| Archival demotes without deletion | T2.4, T2.5 | archival 不 delete |
| Context window token budget recall | T3.1, T3.2 | -- |
| MemoryIndex interface | T4.1 | vector store 選型 |
| SQLite FTS5 and sqlite-vec backend | T4.2 | vector store 選型 |
| MCP server exposes four tools | T4.3, T4.5 | MCP server 暴露 4 個 tool |
| Bot trust scoring | T4.4 | bot trust 四等級 |

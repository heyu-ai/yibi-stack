## 1. Schema 擴充

- [x] 1.1 加 `epistemic_status` 欄位到 `lessons` table（design decision：d1：epistemic_status 用 string enum 而非獨立 table）。`_ensure_columns()` 執行 `ALTER TABLE lessons ADD COLUMN epistemic_status TEXT DEFAULT 'episode'`。既有 lesson 的 NULL 值在讀取時視為 `episode`。Requirement：Epistemic status tracking independent of retrieval tier。驗證：`uv run python -m tasks.mycelium lessons list` 輸出包含 `epistemic_status` 欄位且所有既有記錄顯示 `episode`
- [x] 1.2 加 `superseded_by` 欄位到 `lessons` table（design decision：d2：superseded_by 指向 lesson id 而非覆寫原文）。`_ensure_columns()` 執行 `ALTER TABLE lessons ADD COLUMN superseded_by TEXT DEFAULT NULL`。Requirement：Lesson supersession for append-only correction。驗證：`uv run python -m tasks.mycelium lessons list` 輸出包含 `superseded_by` 欄位且所有既有記錄顯示 `None`
- [x] 1.3 更新 `tasks/mycelium/models.py` 的 `LessonRecord`，加 `epistemic_status: str = "episode"` 和 `superseded_by: Optional[str] = None` 欄位。Pydantic model 驗證 `epistemic_status` 只接受 `episode`/`observation`/`corroborated`/`contradicted` 四個值。驗證：`uv run pytest tasks/mycelium/tests/ -k "test_lesson_record"` 通過，且傳入無效 status 值時 raise `ValidationError`

## 2. Mycelium Service 與 CLI

- [x] 2.1 `get_lessons()` 支援 `epistemic_status` 過濾參數。呼叫 `get_lessons(epistemic_status="observation")` 只回傳 status 為 `observation` 的 lesson。Requirement：Epistemic status tracking independent of retrieval tier（Filter lessons by epistemic status scenario）。驗證：`uv run pytest tasks/mycelium/tests/test_epistemic_status.py::test_filter_by_status` 通過
- [x] 2.2 新增 `lessons supersede <old-id> <new-id>` CLI command。執行後把 `old-id` 的 `superseded_by` 設為 `new-id`，原 lesson 其餘欄位不變。Requirement：Lesson supersession for append-only correction（Superseding a lesson preserves original content scenario）。驗證：`uv run python -m tasks.mycelium lessons supersede <test-old> <test-new>` 成功後，`lessons list` 顯示 old lesson 的 `superseded_by` 指向 new lesson，且 `insight` 內容未變
- [x] 2.3 `distill_service` 的 cluster 聚合排除 `superseded_by IS NOT NULL` 的 lesson（design decision：d2：superseded_by 指向 lesson id 而非覆寫原文）。Requirement：Lesson supersession for append-only correction（Superseded lessons excluded from distill scenario）。驗證：`uv run pytest tasks/mycelium/tests/test_distill_service.py::test_superseded_excluded` 通過——建立 3 個 lesson，supersede 其中 1 個，cluster 只包含剩餘 2 個
- [x] 2.4 `distill_service` 遇到 `superseded_by` 指向不存在 ID 時 log warning 但不 crash（design：failure modes 定義 invalid supersede 為 warning 不為 error）。Requirement：Lesson supersession for append-only correction（Invalid supersede target logged as warning scenario）。驗證：`uv run pytest tasks/mycelium/tests/test_distill_service.py::test_invalid_supersede_warning` 通過——warning 被 log 且無 exception

## 3. Distill 輸出降級

- [x] 3.1 修改 `tasks/mycelium/distill_service.py` 的 `_format_candidate()` 輸出格式（design decision：d4：distill 輸出降級為 observation summary）。candidate 只包含 `observation`（str）、`evidence_ids`（list）、`distinct_pr_count`（int）、`recurrence_span_days`（int）。不再產出 `rule_draft`、`target_file`、`patch_surface` 欄位。Requirement：Distill output is observation summary without rule draft。驗證：`uv run pytest tasks/mycelium/tests/test_distill_service.py::test_candidate_shape` 通過——assert candidate dict 不含 `rule_draft` 和 `target_file` key，且含 `observation` 和 `evidence_ids` key

## 4. Retro Queue Flow 改造

- [x] 4.1 修改 `plugins/growth/skills/pr-retrospective/SKILL.md` 的 queue flow section（design decision：d3：queue flow 改為 optional human action 而非完全移除）。非 emergency 情況下不自動 `gh issue comment`，改為顯示手動指令提示。design 的 behavior 段要求 agent 顯示「如需手動加入 queue」提示。Requirement：Retro writes episode to Mycelium without auto-queue。驗證：內容審查——SKILL.md 的 queue flow 段落在非 emergency path 不包含 `gh issue comment` 自動執行指令，只有使用者可手動執行的指令範例
- [x] 4.2 保留 emergency exception 的自動 queue 寫入路徑（d3：queue flow 改為 optional human action 而非完全移除——emergency path 不受影響）。SKILL.md 的 emergency exception 判斷（bleeding mechanical gap / correcting wrong content）和 `gh issue comment` 自動執行邏輯不變。Requirement：Emergency exception preserves fast track。驗證：內容審查——SKILL.md 的 emergency path 仍包含自動 `gh issue comment` 和 emergency template

## 5. Nightly Agent Dry-Run

- [x] 5.1 在 `tasks/nightly_agent/cli.py` 的 `run` command 加 `--dry-run` flag（design decision：d5：nightly agent 降為 dry-run 模式）。dry-run 模式下產出 digest 到 `.runtime/logs/nightly-YYYY-MM-DD.md` 但跳過 `gh pr create`。design 的 acceptance criteria 要求 mock `gh pr create` 未被呼叫。Requirement：Nightly agent operates in dry-run mode（Dry-run produces digest without PR scenario）。驗證：`uv run pytest tasks/nightly_agent/tests/test_cli.py::test_dry_run_no_pr_create` 通過——mock `gh pr create` 未被呼叫，且 digest 檔案存在
- [x] 5.2 更新 `.runtime/schedules.json` 的 nightly-self-improvement job 參數，加 `--dry-run`。design 的 scope boundaries 明確列出 nightly dry-run 為 in scope。Requirement：Nightly agent operates in dry-run mode。驗證：`jq '.[] | select(.name == "nightly-self-improvement") | .args' .runtime/schedules.json` 包含 `--dry-run`

## 6. 測試

- [x] 6.1 新增 `tasks/mycelium/tests/test_epistemic_status.py`：涵蓋 CRUD default 值（新 lesson `epistemic_status = "episode"`）、filter by status、status 與 tier 獨立性（改 tier 不影響 status）、pre-migration NULL 視為 episode。Requirement：Epistemic status tracking independent of retrieval tier。驗證：`uv run pytest tasks/mycelium/tests/test_epistemic_status.py -v` 全部通過
- [x] 6.2 在 `test_epistemic_status.py` 加 supersession 測試：supersede 後原文不變、superseded lesson 被 distill 排除、invalid target log warning。Requirement：Lesson supersession for append-only correction。驗證：`uv run pytest tasks/mycelium/tests/test_epistemic_status.py -k "supersed" -v` 全部通過
- [x] 6.3 在 `tasks/mycelium/tests/test_distill_service.py` 加 candidate shape assertion：output 不含 `rule_draft` / `target_file`，含 `observation` / `evidence_ids` / `distinct_pr_count` / `recurrence_span_days`。Requirement：Distill output is observation summary without rule draft。驗證：`uv run pytest tasks/mycelium/tests/test_distill_service.py -k "test_candidate_shape" -v` 通過

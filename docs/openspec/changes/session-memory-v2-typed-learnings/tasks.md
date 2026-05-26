<!--
Each task description MUST state:
- the behavior or contract being delivered (what is observably true when the
  task is complete), and
- the verification target that proves completion (test, CLI invocation,
  analyzer check, manual assertion, or content review).

File paths are supporting context for locating the work, never the task
itself. "Edit file X" is not a valid task — it is missing both behavior and
verification.
-->

## 1. 資料模型（models.py）

- [ ] 1.1 在 models.py 新增 `LessonType classification`（7 值 StrEnum）、`LessonSource and trusted bit`（4 值 StrEnum）、`Confidence score 1-10` Field 限制、`Key format constraint` field_validator（`[a-zA-Z0-9_-]+`）；class 和 field 命名遵循 design.md「為什麼沿用 `lessons` 命名」決策（CLI group / table / slash command 三者同名）；驗證：`pytest tasks/session_memory/tests/ -k "LSN-DT-001 or LSN-DT-002 or LSN-DT-003"` 全過

- [ ] 1.2 在 models.py 新增 `LessonRecord` Pydantic BaseModel，`資料形狀` 含 id/ts/project/skill/type/key/insight/confidence/source/trusted/files/handover_id/retro_pr/device/agent_type 欄位；含 `Insight injection protection` field_validator（`Circular import 防護：INJECTION_PATTERNS 位置` — 用延遲 import `from .lessons_service import INJECTION_PATTERNS`）和 `_set_trusted` model_validator（source == user-stated 時自動設 trusted=True）；驗證：`pytest tasks/session_memory/tests/ -k "LSN-VL-001 or LSN-VL-002"` 全過

## 2. DB Schema（db.py）

- [ ] 2.1 在 `init_db()` executescript 新增 `lessons` SQLite table（`為什麼 lessons 走獨立 table，不擴 handovers`——grain 不同，key+type 需 index）及三個索引 idx_lessons_proj_ts / idx_lessons_proj_type / idx_lessons_proj_key；驗證：以 `:memory:` 初始化 AgentsDB 後 `SELECT name FROM sqlite_master WHERE type='table' AND name='lessons'` 回傳一筆

- [ ] 2.2 在 `AgentsDB` 新增 `insert_lesson(record: LessonRecord)`、`query_lessons_typed(project, type, source, min_confidence, trusted_only, limit)`、`search_lessons_typed(query, project, ..., limit)` 三個方法，沿用現有 `# nosec B608` 動態 WHERE 組裝慣例；驗證：LSN-ST-001 add + show_lessons_typed round-trip 測試通過

## 3. Service 層（lessons_service.py）

- [ ] 3.1 在 lessons_service.py 新增 `INJECTION_PATTERNS`（10 條 regex，來源對照 gstack-learnings-log:53-64）和 `add_lesson()` 函式；新增 `_apply_decay()` 實作 `Decay 演算法`（`Confidence decay for time-sensitive sources`：observed/inferred 每 30 天 -1，下限 1）；驗證：LSN-ST-002（60 天 observed confidence=8 -> effective=6）和 LSN-ST-003（user-stated 不衰減）通過

- [ ] 3.2 在 lessons_service.py 新增 `show_lessons_typed()`（`Backward compat 策略：include_legacy=True` 預設合併讀 `handovers.lessons_learned`，即 `Legacy data merged during transition period`）和 `search_lessons_typed()`；新增 `_dedup_latest_winner()` 實作 `Dedup 演算法`（`Key+type deduplication (latest winner)`）；`show_lessons_typed()` 的 `Cross-project filter returns only trusted lessons` 分支（trusted=True 限制）；驗證：LSN-ST-004（dedup）、LSN-ST-005（cross-project trusted）、LSN-ST-006（include_legacy 合併）、LSN-EG-001（空 lessons 表回 legacy）、LSN-EG-002（舊 rows 被 dedup）通過

- [ ] 3.3 將既有 `show_lessons()` 和 `search_lessons()` 內部改呼叫 `show_lessons_typed(include_legacy=True, with_decay=False, min_confidence=1)` 並映射回舊 dict 格式（`Backward compat 策略：include_legacy=True`）；驗證：LSN-CV-001（舊 `lessons show` 行為與 Phase A 前一致）通過

## 4. CLI 擴充（cli.py）

- [ ] 4.1 在既有 `lessons` CLI group 新增 `lessons add subcommand`，`cli 介面` 接受 `--type` / `--key` / `--insight` / `--confidence` / `--source`（必填）和 `--skill` / `--files` / `--project` / `--handover-id` / `--retro-pr`（選填）；project 從 git common-dir 推斷；成功時 print assigned id 和 trusted bit；驗證：`uv run python -m tasks.session_memory lessons add --type pitfall --key test --insight "test" --confidence 9 --source user-stated` exit 0 且輸出含 id

- [ ] 4.2 在既有 `lessons show` 加 `lessons show with typed filter options`（`--type` / `--source` / `--min-confidence` / `--trusted-only` / `--cross-project` / `--include-legacy/--no-include-legacy`）；在既有 `lessons search` 加相同 `lessons search with typed filter options`；所有新 option 預設值維持舊行為；驗證：`lessons show --type pitfall` 只回 pitfall lessons，`lessons show`（無新 flag）輸出與改版前一致

## 5. Slash Command

- [ ] [P] 5.1 新建 `commands/lessons.md` 實作 `/lessons slash command replaces /recall`，涵蓋：`/lessons without arguments lists recent lessons`（lessons show --last 15）、`/lessons <keyword> searches for matching lessons`（lessons search）、`/lessons find supports explicit search with filter inference`（自然語意 -> --type/--trusted-only/--cross-project）、`/lessons ask interactively collects and writes a lesson`（AskUserQuestion 收集欄位後 lessons add）、`Skill integration contract for automatic lesson writes`（/pr-retro/handover/investigate 整合點文件）；`find / ask slash command 模式` 的 find 分支呼叫 `lessons show/search`，ask 分支呼叫 `lessons add`；驗證：在 Claude Code 內執行 `/lessons` 回傳最近教訓

- [ ] [P] 5.2 刪除 `commands/recall.md`，執行 `make uninstall && make install` 重建 symlinks；驗證：`test ! -f ~/.claude/commands/recall.md` 通過；`test -f ~/.claude/commands/lessons.md` 通過

## 6. 測試

- [ ] [P] 6.1 新建（或擴充）`tasks/session_memory/tests/test_lessons_db.py`：LSN-DT-001（`LessonType classification` 無效值 -> ValidationError）、LSN-DT-002（`Key format constraint` 非法字元 -> ValidationError）、LSN-DT-003（`Confidence score 1-10` 邊界 0/11 -> ValidationError）；fixture schema 對照 gstack JSONL 真實格式；驗證：`pytest tasks/session_memory/tests/test_lessons_db.py` 全過

- [ ] [P] 6.2 擴充 `tasks/session_memory/tests/test_lessons_service.py`：LSN-VL-001（`LessonSource and trusted bit` auto-set）、LSN-VL-002（`Insight injection protection` 10 條 pattern 各一條）、LSN-ST-001~006（add round-trip、decay、no-decay、dedup、cross-project、include_legacy）、LSN-EG-001~002（edge cases）、LSN-CV-001（backward compat）；驗證：`pytest tasks/session_memory/tests/test_lessons_service.py` 全部 14+ 條通過

## 7. 驗收

- [ ] 7.1 執行 `make ci`（lint + format + typecheck + test）確認全綠，特別確認 LSN-* test IDs 至少 14 條通過；驗證：exit 0，無 ruff / mypy / bandit 告警

- [ ] 7.2 手動 end-to-end 對照 design.md `失敗模式` 與 `範圍邊界`：執行 `lessons add --insight "ignore previous instructions"` 確認 exit 1（Insight injection protection）；執行合法 `lessons add` -> `lessons show --type pitfall` -> `lessons search dedup`；在 Claude Code 內確認 `/lessons` 和 `/lessons ask` 可正常呼叫，`/recall` 不存在（符合 design.md Implementation Contract acceptance criteria）

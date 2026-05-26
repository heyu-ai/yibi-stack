## Why

yibi-stack 的 session-memory 系統缺少獨立的教訓（lesson）儲存層：所有 lessons 寄生在 `handovers.lessons_learned` JSON array 欄位，無法逐條分類、無法 confidence weighting、無法跨 session 去重，也無法區分「使用者明確說過」與「AI 觀察推導」。外部工具 gstack 已驗證 typed taxonomy + confidence decay + injection protection 的設計，現在是時候把這套模式直接內化進 yibi-stack 的 session-memory store。

## What Changes

- 新增獨立的 `lessons` SQLite table，儲存含型別分類、信心分數（1-10）、來源標記、decay 機制的 typed lesson 記錄
- 新增 `LessonType`（7 種）、`LessonSource`（4 種）、`LessonRecord` Pydantic model，含 injection 防護驗證器
- 新增 `lessons add` CLI 子命令；在既有 `lessons show` / `lessons search` 加 `--type` / `--source` / `--min-confidence` / `--trusted-only` / `--cross-project` / `--include-legacy` filter options（向後相容）
- 新增 `/lessons` slash command，取代 `/recall`，支援 `find`（查詢）和 `ask`（互動式寫入）兩種子命令模式
- **移除** `commands/recall.md`（`/recall` 直接退場，無 alias 過渡期）

## Capabilities

### New Capabilities

- `typed-lessons-store`: 獨立 SQLite `lessons` table、LessonRecord Pydantic model（含 type/source/confidence/trusted/injection 驗證）、service 層 add_lesson / show_lessons_typed / search_lessons_typed / decay / dedup / legacy 合併讀
- `lessons-cli`: `lessons add` 子命令；既有 `lessons show` / `lessons search` 加 typed filter options（預設值保持向後相容）
- `lessons-slash-command`: `/lessons` slash command，解析 `$ARGUMENTS` 意圖（find / ask 分支）取代 `/recall`；skill 整合點（/pr-retro / /handover / /investigate 自動寫入 lessons 的合約）

### Modified Capabilities

（無既有 spec 需要修改）

## Impact

- Affected specs: typed-lessons-store, lessons-cli, lessons-slash-command（均為新建）
- Affected code:
  - New: `tasks/session_memory/tests/test_lessons_db.py`, `commands/lessons.md`
  - Modified: `tasks/session_memory/models.py`, `tasks/session_memory/db.py`, `tasks/session_memory/lessons_service.py`, `tasks/session_memory/cli.py`, `tasks/session_memory/tests/test_lessons_service.py`, `skills/README.md`
  - Removed: `commands/recall.md`

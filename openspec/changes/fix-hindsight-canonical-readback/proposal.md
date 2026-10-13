---
type: bug
---

## Why

pr-retrospective 的 Hindsight 投影協議（plugins/growth/skills/pr-retrospective/HINDSIGHT.md「Canonical projection and lifecycle reconciliation」第 3 步）規定用唯讀 SQLite URI（加上 mode=ro 參數）收齊同 key 的所有 canonical 列。這台機器的 handover.db 是 WAL 模式，DB 關閉後 -shm 檔會被移除，agent 讀回時用的是 PATH 上的 python3（SQLite 3.51.0），它的 mode=ro 連線無法自己建立 -shm，於是固定回 `unable to open database file`（SQLite 3.47.1 則能開啟，失敗取決於版本，細節見 design）。協議規定此時 projection degraded、不發布，結果 2026-10-02（PR #515，5 則 lesson、其中 4 則合格）與 2026-10-12（PR #556）兩次 retro 的投影都被跳過，PR #515 那 4 則直到 2026-10-13 才人工補寫。只要這條讀回路徑不改，之後每次 /pr-retro 都會重複漏投。

現有的 `mycelium lessons show` 也不能直接取代：它會依 key+type 去重（只留最新一列），正好藏住協議要偵測的「同 key 多個 active rows」；它還會在連線時執行 journal_mode PRAGMA 與 init_db 建表，DB 不存在時會建一個新的，而協議明文禁止初始化缺少的 DB。

## What Changes

- 新增 mycelium CLI 子指令 `mycelium lessons rows`：依 project 加上一或多個 key 及／或 lesson id，唯讀回傳 lessons table 中**所有**相符的列（含 retired、parked、superseded），不去重、不設筆數上限，輸出固定為 JSON，每列附 effective_confidence。
- 該指令以「不建立檔案、可建立 WAL 輔助檔、SQL 層禁止寫入」的方式開 DB：DB 檔不存在時直接失敗而不建立；不執行 journal_mode 變更或建表；連線設定 query_only，任何寫入語句都會被拒絕。
- 該指令的 exit code 區分「查詢成功（可為零列）」與「DB 不可用」，讓協議能把後者判為 degraded，而不是誤判成「沒有列」。
- 改寫 HINDSIGHT.md 第 2、3 步（合併為一次呼叫）：以 `mycelium lessons rows` 取代 `lessons show` 加直接開 SQLite，保留原有語意（一次收齊本次所有相關 key 與 receipt owner、缺列或歧義即 degraded、不得逐列邊查邊寫）。

## Capabilities

### New Capabilities

- `lesson-canonical-readback`: mycelium CLI 依 project、key、lesson id 唯讀列出所有 canonical lesson 列，供 Hindsight 投影協議做 ownership 與 lifecycle 判定

### Modified Capabilities

(none)

## Impact

- Affected specs: lesson-canonical-readback（新增）
- Affected code:
  - New: tasks/mycelium/tests/test_lessons_rows.py
  - Modified: tasks/mycelium/db.py, tasks/mycelium/lessons_service.py, tasks/mycelium/cli.py, plugins/growth/skills/pr-retrospective/HINDSIGHT.md, scripts/lessons, scripts/tests/test_lessons_wrapper.py（lessons wrapper 把新子指令歸為不注入 --project；實作時由既有 drift guard 測試要求）
  - Modified（版本同步）：各 plugin 的 package.json 與 .claude-plugin/plugin.json、pyproject.toml，由 scripts/sync-plugin-versions.sh 統一改寫（plugins/** 有變動時的 lockstep 版本規則）
- 相依：integrate-retro-hindsight change（PR #512 已 merge、尚未 archive）所定義的 retro-hindsight-projection 行為不變；其「Lifecycle reconciliation」只要求從 canonical storage 重讀含 inactive 的列，未規定讀取機制，本變更只替換機制。

## Context

Hindsight 投影協議（plugins/growth/skills/pr-retrospective/HINDSIGHT.md，「Canonical projection and lifecycle reconciliation」一節）把 canonical 讀回分成兩步：第 2 步用 `mycelium lessons show` 讀候選，第 3 步用唯讀 SQLite（mode=ro 的檔案 URI）以 `SELECT * FROM lessons WHERE project = ? AND key = ?` 收齊同 key 的所有列，並依 receipt 的 lesson_id 查明 owner。缺 owner、歧義、缺欄位或 DB 不可用都判 degraded、不發布。

實測事實（2026-10-13，macOS，拋棄式 DB，WAL 模式，-shm 與 -wal 已不存在，檔頭第 18／19 位元組為 2／2）：

| 開法 | SQLite 3.51.0（asdf Python 3.13.3，即系統 PATH 上的 python3） | SQLite 3.47.1（uv 管理的 Python 3.12.9，pytest 與 installed mycelium CLI 使用） |
|---|---|---|
| 檔案 URI 加 mode=ro | 失敗：`OperationalError: unable to open database file` | 成功，SQLite 自行建立 -shm |
| 檔案 URI 加 mode=rw，再執行 `PRAGMA query_only = ON` | 成功；INSERT 被拒（`attempt to write a readonly database`） | 成功 |
| 對不存在的路徑用 mode=rw | 失敗且不建立檔案 | 失敗且不建立檔案 |

所以 mode=ro 的失敗**取決於 SQLite 版本**，不是在所有環境都必然發生（最初提案寫「一定開不了」，實作時以兩個版本對照後修正）。歷次 retro 的讀回是 agent 以 PATH 上的 python3 執行協議裡的連線字串，該直譯器是 SQLite 3.51.0，因此穩定失敗。正式的 `~/.agents/handover/handover.db` 目錄中沒有 -shm／-wal 檔，與上表情境相同。

即使在會成功的版本上，現行做法仍有兩個問題：讀回結果取決於 agent 剛好用到哪個 python3（環境漂移，無法由協議控制）；而且只要任一環境升級到新版 SQLite 就會退回失敗。新指令讓讀回固定在 installed CLI 的直譯器內執行，並改用在兩個版本都成功的 mode=rw 加 query_only，消除這兩個問題。這個失敗已在三次獨立讀回中出現：PR #515 retro（2026-10-02，audit 7fdda45b）、PR #556 retro（2026-10-12，audit fef8b35c）、以及 2026-10-13 人工補寫時的讀回。前兩次依協議判 degraded，PR #515 的 4 則合格 lesson 因此漏投，直到 2026-10-13 人工補寫。

`mycelium lessons show`（`show_lessons_typed`）不適合直接取代第 3 步：
- 依 key+type 只保留 ts 最新的一列（`_dedup_latest_winner`），協議要偵測的「同 key 多個 active rows」會被藏起來。
- 內部查詢上限 500 列（`_SEARCH_INTERNAL_LIMIT`），對外再截到 `--last`。
- 透過 `AgentsDB` 開連線，會執行 `PRAGMA journal_mode=WAL` 與 `init_db()`（`CREATE TABLE IF NOT EXISTS`），DB 不存在時會建立新檔，違反協議「不能初始化缺少的 DB」。

相依：integrate-retro-hindsight change（PR #512 已 merge、未 archive）定義的 retro-hindsight-projection 只要求「從 canonical storage 重讀含 inactive 的列、缺列或歧義即 degraded」，沒有規定讀取機制；本設計只替換機制，不改那份 spec 的行為。

## Goals / Non-Goals

**Goals:**

- 提供一個在 WAL 且無 -shm 的 DB 上也能運作的唯讀 canonical 讀回介面，回傳同 project 下指定 key／id 的**所有**列，不去重、不截斷。
- 保證讀回不會建立 DB、不會建表、不會寫入任何 lesson 資料。
- 讓呼叫端能分辨「查詢成功但零列」與「DB 不可用」。
- 讓 HINDSIGHT.md 的讀回步驟改用此介面，且協議語意（一次收齊、缺列或歧義即 degraded）不變。

**Non-Goals:**

- 不修改 `mycelium lessons show`、`lessons search` 的行為（它們是給人與一般檢索用的，去重是正確的）。
- 不修改 `AgentsDB` 既有的連線方式與 journal_mode 設定。
- 不修改 hindsight_projection.py 的 prepare 邏輯或 input schema；新指令輸出的列可直接放進 input 的 record。
- 不回頭補寫其他漏投的 retro（PR #515 已於 2026-10-13 人工補寫完成，PR #556 那則是 investigation 類型本來就不投）。
- 不處理 sandbox 禁止在 DB 目錄建立輔助檔的環境；那種情況新指令以 DB 不可用回報，協議照樣 degraded（見 Risks）。

## Decisions

### 以 mode=rw 加 query_only 開 DB 取代 mode=ro

新增 DB 層的唯讀開啟函式：用 `file:<absolute path>?mode=rw` URI 連線，連上後立刻執行 `PRAGMA query_only = ON`，不執行 journal_mode PRAGMA、不呼叫 init_db。mode=rw 不會建立不存在的檔案（實測），但允許 SQLite 建立 WAL 所需的 -shm／-wal；query_only 讓任何寫入語句在 SQL 層被拒。

替代方案與否決理由：
- 維持 mode=ro：在部分 SQLite 版本（實測 3.51.0）遇到 WAL 且無 -shm 時失敗，且結果取決於呼叫端的直譯器，就是本次要修的問題。
- mode=ro 加 immutable=1：可以開檔，但 immutable 會忽略尚未 checkpoint 的 -wal 內容，可能讀到過期資料，對 canonical 讀回不可接受。
- 先用一般連線建立 -shm 再改用 mode=ro：仍需一次可寫連線，複雜度更高且沒有額外保證。
- 直接用 `AgentsDB`：會改 journal_mode 並建表，DB 不存在時會建檔。

### 新增 lessons rows 子指令而非擴充 lessons show

新增 `mycelium lessons rows` 子指令，與 show 完全分開。show 的去重、上限、legacy 合併、衰減後依 confidence 過濾等行為，對 canonical 讀回都是錯的；加旗標關掉它們會讓 show 的語意分岔且容易漏關。新指令只做一件事：依 project 加 key／id 列出原始列。

### DB 不可用以 exit 3 回報

exit code 契約：0 = 查詢成功（rows 可為空）；2 = 參數錯誤（Click 預設的 usage error，也涵蓋舊版 CLI 沒有此子指令時的 `No such command`）；3 = DB 不可用（檔案不存在、無法開啟、lessons table 不存在、查詢時發生 sqlite 錯誤）。不使用 1 與 2 表示 DB 問題，避免和 Click 的 usage error 混淆。exit 3 時 stdout 為空、stderr 輸出 `[FAIL]` 開頭的原因。

### 輸出單一 JSON 物件並列出 missing keys 與 missing ids

輸出固定為一個 JSON 物件（沒有表格模式），欄位見 Implementation Contract。missing_keys／missing_ids 讓協議不必自己比對「要的 key 有沒有回來」，直接依「有 missing 即 degraded」判斷。

### effective_confidence 沿用 show 的衰減計算

每列附 effective_confidence，計算方式與 `show_lessons_typed` 相同（`_apply_decay(confidence, source, ts)`），讓協議第 3 步原本「新發布的 effective_confidence 採正常 CLI readback」的要求，可以由同一次呼叫滿足，不再需要另外合併 show 的結果。

### HINDSIGHT.md 讀回步驟改呼叫 lessons rows

把 HINDSIGHT.md 第 2、3 步合併為一次 `mycelium lessons rows` 呼叫：本次所有候選 key、所有先前 accepted receipt 的 key 與其 lesson_id，一次傳入。保留原有規則：每個 canonical ID 只收一次、缺 owner／歧義／缺欄位／錯 tags 即 degraded、同 key 多個 active rows 拒絕、不得逐列邊查邊寫。識別碼合計超過 200 時可拆成多次 rows 呼叫，但必須在本次 invocation 任何寫入之前全部完成並合併結果（讀寫不交錯）。任何非 0 exit 都判 degraded；exit 2 只有 stderr 含 `No such command` 時才提示「installed CLI 過舊，請以新 release tag 重新安裝」，其餘 exit 2 回報為該次呼叫的參數錯誤。移除 SQLite 連線形式與 bound query 的描述。

## Implementation Contract

**Behavior**：操作者或 agent 執行 `mycelium lessons rows --project <p> --key <k> [--key <k2> ...] [--id <lesson-id> ...]`，得到該 project 下所有 key 屬於指定集合、或 id 屬於指定集合的 lesson 列，含 retired、parked（tags 含 parked）、superseded 的列；同 key 多列全部回傳。

**Interface / data shape**：
- 選項：`--project`（必填，非空字串）；`--key`（可重複，格式 `^[A-Za-z0-9_-]+$`）；`--id`（可重複，非空字串）。`--key` 與 `--id` 合計至少 1 個、至多 200 個，否則為 usage error（exit 2）。重複傳入的同一 key／id 視為一個。
- DB 路徑：環境變數 MYCELIUM_DB_OVERRIDE 有值時用它，否則用 mycelium 預設的 handover.db 路徑。
- stdout（exit 0）：

```json
{
  "schema_version": 1,
  "project": "<p>",
  "requested": {"keys": ["<k>", "..."], "ids": ["<id>", "..."]},
  "rows": [{"id": "...", "ts": "...", "project": "<p>", "type": "...", "key": "...", "insight": "...", "confidence": 8, "effective_confidence": 8, "source": "...", "tags": [], "files": [], "retired_at": null, "superseded_by": null, "...": "lessons table 其餘欄位"}],
  "missing_keys": ["<要了但零列的 key>"],
  "missing_ids": ["<要了但不存在於此 project 的 id>"]
}
```

- rows 依 key、ts、id 遞增排序；tags 與 files 為 JSON 陣列（不是字串）；requested 內的 keys／ids 為去重後排序的結果。
- 只查一次：所有條件組成單一參數化 SELECT（`project = ? AND (key IN (...) OR id IN (...))`），同一快照內完成。

**Failure modes**：
- DB 檔不存在、無法開啟、lessons table 不存在、查詢 sqlite 錯誤、列的 tags／files 不是合法 JSON 陣列、列缺欄位或欄位值無法計算衰減 → exit 3，stdout 空，stderr 為 `[FAIL]` 加原因；不建立任何檔案（不存在的 DB 路徑在指令結束後仍不存在）。
- 參數不合法 → exit 2（Click usage error）。
- 不會靜默把錯誤當成零列：零列只在查詢成功時出現，且會反映在 missing_keys／missing_ids。

**Acceptance criteria**（tasks/mycelium/tests/test_lessons_rows.py 中的測試）：
- WAL 模式、-shm 與 -wal 已移除的 DB 上，指令 exit 0 並回傳列。對照測試：在會重現的 SQLite 版本上，同一 DB 以 mode=ro 開啟會失敗；在不會重現的版本（如 3.47.1）上，對照測試以 pytest.skip 明確標示「此 SQLite 不重現 mode=ro 失敗」及版本號，不得靜默通過。
- 同 key 兩列（一列 active、一列 retired 並帶 superseded_by）全部回傳，不去重。
- parked 列被回傳。
- 不存在的 DB 路徑 → exit 3，且路徑仍不存在。
- 開啟後的連線拒絕 INSERT（query_only 生效）。
- missing_keys／missing_ids 正確；另一 project 的同 id 不會被回傳且列入 missing_ids。
- 未給 `--key`／`--id`、或 key 格式不合 → exit 2。
- effective_confidence 與 `show_lessons_typed` 對同一列的值相同。

人工確認（不是自動化測試）：`uv run python -m tasks.mycelium lessons --help` 列出 rows 子指令。

**Scope boundaries**：
- In scope：DB 層唯讀開啟函式與依 project+key/id 查詢函式、service 函式、CLI 子指令、上述測試、HINDSIGHT.md 讀回步驟改寫、plugin 版本同步，以及 lessons wrapper（scripts/lessons）把 rows 歸為「不注入 --project」。最後這項是實作時由既有 drift guard 測試（LSW-VL-001，要求每個 lessons 子指令都要分類）發現的：wrapper 對未分類子指令預設注入 cwd 的 project，若 rows 被注入，呼叫端漏帶 --project 時讀回會被靜默窄化成錯的 repo；歸為不注入後，漏帶會由 Click 以 exit 2 大聲失敗。
- Out of scope：show／search 行為、AgentsDB 連線設定、hindsight_projection.py、pr-retrospective SKILL.md（其 Step 5 只寫「從 installed Mycelium CLI 讀回」，與新做法一致，不需改）、既有 audit 檔。

## Risks / Trade-offs

- [mode=rw 連線會在 DB 目錄建立 -shm／-wal] → 這是 SQLite 的 WAL 基礎設施檔案，不是資料寫入；lesson 資料的寫入由 query_only 擋下，測試以 INSERT 被拒驗證。
- [關閉最後一條連線時可能 checkpoint 主檔] → WAL 模式下，rows 若是最後一條關閉的連線，SQLite 可能把 -wal 中其他寫入者已 commit 的 frame checkpoint 回主檔。這會改寫主檔的頁面，但內容是早已 commit 的資料，不會寫入新的 lesson 資料。因此 4.4 的「主檔 sha256 前後不變」只在 -wal 為空時成立；-wal 有未 checkpoint 的 frame 時，主檔雜湊可能改變而資料語意不變。
- [DB 目錄不可寫（例如 sandbox 禁止建檔）時 mode=rw 也開不了] → 指令以 exit 3 回報，協議判 degraded，與現況相同但原因明確；不另做繞道。
- [query_only 可被 SQL 關閉] → 指令只執行程式內固定的參數化查詢，不接受使用者提供的 SQL。
- [installed CLI 未更新時沒有 rows 子指令] → Click 回 exit 2；協議把任何非 0 判 degraded，並提示重新安裝，不會誤判成零列。
- [effective_confidence 隨時間衰減，兩次呼叫可能不同] → 與 show 的既有行為一致；協議在單次 invocation 內只呼叫一次。
- [寫入者同時寫入] → WAL 允許讀寫並行；單一 SELECT 在同一快照內完成。

## Migration Plan

- installed mycelium CLI 是以指定 release tag 的 uv tool install 安裝（mycelium-cli spec「Two-track installation documentation」），所以合併後要等下一個 release tag，使用者以該 tag 重新執行 `uv tool install --force "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<新 tag>"`，`mycelium lessons rows` 才可用。更新前協議會因 exit 2 判 degraded（與現況相同，不會更糟）。
- 回滾：revert 此 PR 即可，沒有資料遷移；新指令不寫 DB，不留下需要清理的狀態。

## Open Questions

（無）

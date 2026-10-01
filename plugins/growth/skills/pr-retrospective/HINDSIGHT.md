# Hindsight integration protocol

供 pr-retrospective 與 lesson-promotion 共用。Mycelium 是唯一 canonical ledger，Hindsight 只是衍生索引。
agent 執行 MCP 呼叫；helper 只產生決定性的 JSON 與觀測報表，不連線、不修改 Mycelium。
不得繞過缺少的 MCP 能力，偷偷改用 HTTP 或杜撰參數。

## Availability and call receipts

1. 每次 invocation 產生唯一 UUID。project 從主 Git repo 解析，不能使用 worktree branch 名。
   durable audit 寫到 `~/.agents/hindsight-retro/<project>/<invocation_id>.json`，權限限 owner，
   每次更新都原子替換本 invocation 的檔案，不覆蓋其他 session。不得記錄 credentials 或 transcript 全文。
2. 設 `kind=retro` 或 `promotion`；`retro_id` 使用 repo-qualified PR URL 或穩定 session ID，
   重試同一個 retro 不換 identity。真實操作用 `sample_kind=live`，演練用 `smoke`。
3. 每個 invocation **只做一次** tool schema 檢查。base tools 為 diagnose/list/search/read；
   reflect/ingest/capture 各自需要實際 advertised capability。初始 `HINDSIGHT_AVAILABLE=false`。
4. 呼叫 `hindsight_diagnose({})` 核對 workspace/bank 與目標 project；這只是本地設定，不是 server liveness。
   固定 `[Lesson] <key>` 在跨 project 共用 bank 會碰撞：此時只允許核實來源後的唯讀建議，
   除非已確認 bank 專屬於這個 project，否則不發布／reconcile lesson。
5. 以 host 的有界 timeout 呼叫 `hindsight_list_knowledge_pages({})`，成功（含空清單）才表示 read 可用。
   缺工具、錯 bank、逾時、MCP isError 或 error object 都記 `[DEGRADED] Hindsight unavailable`、
   `hindsight_sync=skipped`，繼續 Mycelium-only。快取結果，不逐 lesson 重探。
6. transport/server failure 後停用本 invocation 剩餘呼叫。單一 optional capability 缺失只跳過該操作。
   Hindsight 不可改變 Evidence/Promotion Gate、confidence 或 Mycelium lifecycle。

**每個呼叫發出前**先落 audit event：唯一 event_id、operation、subject identity、UTC timestamp、
`outcome=pending`、`page_ids=[]`、`fallback=false`、`human_decision=not_applicable`。
返回後更新同一個 event，不另外加一筆重複結果：

| 結果 | Receipt | 動作 |
|------|---------|------|
| 成功讀取 | success，加候選 page IDs | 繼續 |
| ingest 回 ok=true 且 doc_id 等於 expected_doc_id | accepted | 保存 projection receipt；抽取仍是非同步 |
| capture 回真實 page ID | accepted，加 page ID | 保存 initiative identity/page 對應，不代表合成內容完成 |
| 能力缺少 | skipped、fallback=true | 繼續原流程 |
| 呼叫失敗／逾時 | failed、fallback=true、原因 | 停用剩餘 Hindsight calls；寫入操作另記 write_outcome=unknown |
| invocation 中斷 | 保留 pending | 結果未知，不解讀成「確定沒寫入」 |

Audit 寫不下去時先停用 optional Hindsight calls，不能做未稽核的寫入；保留原 Mycelium 流程。
寫入逾時／回應不明不能自動 retry，尤其 initiative creation。下一次先檢查 pending 或
write_outcome=unknown 的同 identity 操作，未釐清前維持 degraded。

**未知寫入的人工恢復**：列出 invocation、subject/document identity、發生時間與錯誤，請 operator
在 Hindsight control plane 查 operation 是否仍會執行，以及目前文件歸屬。尚在 pending/processing
時不得搶先補寫；確認 terminal outcome／取消完成並保留證據後，才重新讀 canonical 決定後續動作。
不要只因搜尋零命中就解除 unknown，也不能把 timeout 人工改成 accepted。若沒有可驗的完整 receipt，
由 operator 處理遠端 stale 文件；本 skill 保持 degraded，不捏造 MCP read-document/cancel 能力。

### Actual MCP argument shapes

- `hindsight_search_knowledge_pages({query})`：沒有 limit 參數；先篩 provenance，再取最多三個合格候選。
- `hindsight_read_knowledge_page({page_id})`：snippet 不足以核對 provenance/incident 時讀全文。
- `hindsight_reflect({query})`：限高價值且高度相似、仍模糊／衝突的候選；反思文字不是獨立事件。
- `hindsight_ingest_document({title, content})`：沒有 native metadata、document_id、operation_id 或 append-to-page。
- `hindsight_capture_initiative({title, summary, relates_to_page_id?})`：更新既有 initiative 要帶 page ID；建立不是原生冪等。

依工具回應讀 page/name/title。排除 `[Lesson]` 標題、source_system=mycelium envelope，以及主題頁中
衍生自 projection 的段落。未知 provenance 不算獨立事件，reflect 也不能把它洗成新證據。
回查實際 PR/session 來源；同一事件的 review、commit、摘要只算一次。helper 會合併標準 GitHub
PR URL 與 owner/repo#N（含大小寫差異）；其他來源仍須 agent 核實、統一 identity，不能靠字串不同認定獨立。
Audit 留下 source IDs 與人類 recurrence 決定；回答確實使用記憶時才標明來源。

## Canonical projection and lifecycle reconciliation

新 projection 必須在使用者確認 retro、**所有本次必要 Step 5 canonical mutations 成功**之後。
取消、Step 4 失敗或 Step 5 未成功收尾，不發布新 lesson／initiative。Step 4b 只準備，不發布。
`--skip-if-exists` 成功也須讀回真正儲存的 row，不能拿準備中的參數當 canonical。

1. 從過去 audit 讀取**每個**先前 accepted projection identity，不限本次搜尋／新候選；即使無新候選也做。
   依 accepted_at 的實際時間選該 document 最新 receipt，保留 lesson_id。Receipt 是傳送帳本，不是知識權威。
   同 identity 的 pending/unknown 必須先解決，否則不寫。
2. 正常候選用 installed CLI 讀回：
   `mycelium lessons show --project <project> --no-include-legacy --include-retired --include-parked --min-confidence 0 --last 10000 --json`。
   此 API 會 dedup 且有筆數限制；找不到不代表退休／刪除。
3. 用同一 canonical DB 的 read-only SQLite 收齊本次所有相關 key 的 rows，而非邊查一列邊寫一列。
   尊重 MYCELIUM_DB_OVERRIDE，否則是 `~/.agents/handover/handover.db`；不能初始化缺少的 DB 或 import checkout tasks。
   連線形式為 `sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)`。
   先以 project＋receipt lesson_id 查明 owner，再對每個不同 key 使用 bound query：
   `SELECT * FROM lessons WHERE project = ? AND key = ?`。缺 owner、歧義、缺欄位、錯 tags 或 DB 不可用都 degraded。
   每個 canonical ID 只收一次；不得為不同搜尋來源重複加入同一列。新發布的 effective_confidence
   採正常 CLI readback（若有），合併到同 ID 的 canonical row；不能因 SQLite 只有 raw confidence 就繞過門檻。
4. 把這些 rows 放進單一 INPUT_FILE 的 items。要發布的候選另帶 summary/evidence_ids；
   只用於 ownership／lifecycle 判定的舊列或已發布 active owner，只帶 record。
   receipts 每份文件只放最新一份 accepted receipt；仍為 pending/unknown 的整個 key 不進發布 batch，記 degraded。
5. 核實短背景摘要與事件指針，不複製 insight 全文。pitfall 可使用獨立已驗證 commit；pattern 需兩個不同事件。
   helper 對整個 invocation **只 prepare 一次**：每 doc 最多一個最終意圖。
   唯一合格 active successor 先驗證前 owner 的 superseded_by 指向其 ID，再勝過舊列 tombstone；
   若無合格 successor，才依最新 receipt owner 的 canonical inactive 狀態撤回舊文件。
   最新 owner 已是 active B 時，不得再用 A 的舊 receipt 排入 A 的 tombstone。
   同 key 多個 active rows、重複 ID／receipt、未核實接替關係都拒絕，不能自行選一列。
6. 必須先收齊新候選與所有先前投影，再產生完整 plans；**禁止**逐 lesson 呼叫 prepare、先發布 B 再另補 A，
   或把前次單列輸出串成一批。舊單列 input schema 已移除。重新啟用的 active owner 若需要恢復投影，
   必須補齊其已核實候選摘要／證據，不能把 tombstone 當已恢復。每個 invocation 每 doc 至多一次 MCP ingest。

### Paths and invocation

agent 必須把 Step 0 已解析的 ORIG_PROJECT、RETRO_ROOT 與本次 INVOCATION_ID 帶入**同一次**
Bash 呼叫或單一暫存 script，不能依賴跨 call 的 shell 變數。每次 invocation 只有一份 batch：

```bash
AUDIT_DIR="$HOME/.agents/hindsight-retro/${ORIG_PROJECT:?missing project}"
WORK_DIR="$AUDIT_DIR/work/${INVOCATION_ID:?missing invocation id}"
INPUT_FILE="$WORK_DIR/input.json"
OUTPUT_FILE="$WORK_DIR/plans.json"
```

用檔案工具建立 owner-only WORK_DIR 與 INPUT_FILE；暫存輸入／輸出放在 work/ 子目錄，
不混入報表掃描的頂層 audit JSON。內容用 Write 工具，不把 lesson 文字塞進 shell。
以下是一個新候選、尚無 receipt 的 batch；reconciliation context 也放在同一個 items 陣列，只帶 record：

```json
{
  "project": "payments",
  "items": [
    {
      "record": {
        "id": "canonical-lesson-id",
        "project": "payments",
        "key": "payments-retry-boundary",
        "type": "pitfall",
        "source": "observed",
        "confidence": 8,
        "tags": [],
        "retired_at": null,
        "superseded_by": null
      },
      "summary": "A timeout after acceptance is not evidence that a write did not occur.",
      "evidence_ids": ["https://github.com/team/payments/pull/42"]
    }
  ],
  "receipts": []
}
```

完成上述賦值並寫入 JSON 後，在同一個 shell context 執行：

```bash
python3 "${RETRO_ROOT:?missing skill root}/scripts/hindsight_projection.py" prepare --input "$INPUT_FILE" --output "$OUTPUT_FILE"
```

Exit 2 代表輸入／I/O 失敗：記 degraded，**忽略任何舊 OUTPUT_FILE**，不能呼叫 MCP。
Exit 0 回傳 project 與 plans 陣列，每份文件最多一筆。action=skip 記原因、不 ingest；
只有 action=ingest 才使用該 plan 的 arguments。寫前再次核對該 key 的整組 canonical snapshot；
若變動就停止該 document，不能先執行舊 plan 再補一個相反 plan。已送出的 doc 不在同 invocation 重送。
明確指定的空 audit 目錄合法；空字串路徑不合法。

Helper 拒絕 project mismatch、非小寫 kebab-case key、身分首尾空白、缺 lifecycle、錯 tags、
foreign/unaccepted receipt。Active 門檻：effective_confidence（若存在，不能把 null 當可 fallback）
或 confidence >=7；pitfall 需非 inferred 且有事件；pattern 需 >=2 個獨立事件。
Inactive 不會新增 active projection；先前 owner 已失效且沒有合格 successor 時，即使 confidence 降低，
仍產生同文件 tombstone。合格 successor 取代舊 owner 時只送 successor，不能再送舊 tombstone。不能為發布而改 Mycelium。

Ingest 成功後核對 ok=true、doc_id==expected_doc_id；不符就是 degraded，不能保存 accepted receipt。
Receipt 為成功送出的那一筆 plan 去掉 arguments，再加 outcome=accepted、canonical lesson_id、originating retro_id、
accepted_at。失敗／逾時不得存 accepted。這份 durable audit 要留給下次 retro **或 promotion**，不能當暫存刪除。

### Stable identity, not native idempotency

目前 MCP 將 `[Lesson] payments-retry-boundary` 對應到 lesson-payments-retry-boundary。
相同 accepted content revision 由 helper skip；summary 改變就是新內容，hash 改變是預期行為，
不是 canonical 不變就強制忽略摘要變更。相同 title 對應同邏輯文件；不保證 exactly-once 或跨 session lock。

Envelope 帶 source_system/source_id/project/lesson_id/lifecycle/summary/evidence_ids/superseded_by，
以 UTF-8、sorted keys、compact separators、未跳脫 Unicode 的 canonical JSON 算 SHA-256，
hash 輸入不包含 content_hash/revision_key 自己。之後加入 content_hash 與
`mycelium:<project>:<key>:<sha256>` revision_key。這些在 **content**，不是 native metadata／operation_id。
不要把 hash 加入 title，否則每版變新文件、舊 active 文件不會被取代。

本 MCP 不能直接 append 合成主題頁。Retained 文件供原有頁面合成使用，accepted 不等於 extraction 完成或可搜尋；
新 tombstone 也不能證明舊 observations 已消失。檢索仍須核對 canonical lifecycle 與 projection provenance。

## Human decisions and measurement

Promotion 先讀 canonical ADR/rules/specs，再用 Hindsight 補背景。possible_duplicate 與
possible_contradiction 帶來源／page ID，人類回答前維持 pending。相近記憶不代表已存在防護 rule，
也不代表重複 Mycelium row。衝突交人選擇尊重舊決策修正 lesson，或走 ADR/spec 變更；不得自動改 confidence／lifecycle。

Audit 格式（填實際結果，不能捏造）：

```json
{
  "schema_version": 1,
  "invocation_id": "unique-uuid",
  "project": "payments",
  "kind": "retro",
  "canonical_written": false,
  "sample_kind": "live",
  "retro_id": "https://github.com/team/payments/pull/42",
  "recorded_at": "2026-09-30T12:00:00Z",
  "hindsight_sync": "queued",
  "events": [],
  "projections": [],
  "decisions": [],
  "metrics": []
}
```

hindsight_sync 為 queued/skipped/degraded，不推定 synced。preflight 的 canonical_written=false，
只有使用者確認且 Step 4 真正儲存成功才設 true；取消／寫入失敗不計入30次。Promotion 不需要此欄位，也不計次。
每次更新用含時區的 ISO 8601 recorded_at，建議 UTC。報表解析真正時間，不以時間字串字典序判新舊；無效／無時區者列 excluded。
GitHub PR URL 與 owner/repo#N 在 evidence、retro 計次及 metric join 使用同一正規化；其他已核實的 session identity 保持穩定。

每個 metric row 含 source_id、**原始 retro 的** retro_id；duplicate/invalidated/cited/false_recurrence
為 boolean observation，未知用 null 或省略。Promotion 可補觀測舊 retro，但不能因此新增一個 retro 樣本：

- duplicate：發布後經人複查，確定有等價投影；同 revision skip 不算 duplicate。
- invalidated：已發布 lesson 後來 park/supersede/retire；目前 active 不代表未來永不失效。
- cited：後續檢索確實把投影引用作背景，不是拿它當獨立 recurrence 事件。
- false_recurrence：人類否決先前 recurrence，原因是 projection feedback 或同一事件重複表述。

只有真的評估過才填 true/false，不能預設 false。每率的分母是已觀測的 `(retro_id, source_id)`，
不是所有投影筆數；未知不能當零。events/decisions 保留 page/source IDs、fallback、人類接受／拒絕／延後與理由。
缺 project 等 malformed audit 列 excluded；有效的其他 project 檔案則正常篩除。

每次 invocation 收尾執行報表；先在該 Bash call 帶入 Step 0 的 ORIG_PROJECT 與已解析 RETRO_ROOT：

```bash
AUDIT_DIR="$HOME/.agents/hindsight-retro/${ORIG_PROJECT:?missing project}"
python3 "${RETRO_ROOT:?missing skill root}/scripts/hindsight_projection.py" report --audit-dir "$AUDIT_DIR" --project "$ORIG_PROJECT"
```

Exit 2 則 measurement degraded，保留 canonical 結果。Report 對 invocation 去重，只計 distinct、
canonical_written=true 的 live retros；smoke、取消、promotion、同 PR 重跑不能補數。
measurement_ready=true 需 >=30 次；沒有觀測的 rate=null。之前回報 insufficient_data、實際計數與分母，
不宣稱成效。Malformed 檔案明列 excluded，不聲稱完整涵蓋；滿30次後交真實報表供人調整。

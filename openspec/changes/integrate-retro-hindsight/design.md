## Context

#425 橫跨 yibi-stack 的 retro 與 ainization-skill 的 promotion。實跑 MCP tools/list 確認 ingest 只有 title/content；search 沒有 limit；capture 支援 relates_to_page_id。使用者已選擇配合目前 MCP 修正 A2。retro Step 4b 只是準備，Step 5 gate 後才寫 canonical lesson，因此 projection 必須排在 Step 5 成功之後。

## Goals / Non-Goals

In scope：A0–A3、B1–B2、lifecycle tombstone、可持續累積的 audit 與 30 次真實 retro 成效報告。
Out of scope：Mycelium CLI/schema、upstream MCP、新 memory backend、新 distill skill、改變原有 Evidence/Promotion Gate、自動制定 rule。

## Decisions

### 能力偵測與降級

每次 invocation 一次讀取 tool schema，確認 bank 路由，再做 bounded list read。diagnose 是本地設定，不是 server 健康證據。缺工具、錯 bank、server 失敗均保留原本流程；一次 transport 失敗後不逐條重試。每次呼叫在發出前先落 pending event，返回後寫 outcome，未知寫入結果不宣稱成功。

### 內容封套與穩定文件

採 JSON content envelope：source_system、source_id、project、lesson_id、lifecycle、summary、evidence_ids、superseded_by、content_hash、revision_key。背景摘要不是全文複製。使用固定 [Lesson] <key>；key 限現有英文 kebab-case，避免 MCP slug collision。content_hash 對不含 hash/revision 欄位的 canonical JSON 做 SHA-256。revision_key 為 mycelium:<project>:<key>:<hash>，只在 content 中，不是假造伺服器冪等參數。相同 accepted revision skip；內容變化仍寫相同 title/doc ID。不同來源 project 共用 bank 時先查收據／existing content，無法確認 ownership 則 degraded，不覆寫。

### 先 canonical 再投影

helper prepare 接收已寫入並讀回的 record，而非預計 lessons add 的參數。pitfall confidence>=7 且 source!=inferred 且具獨立事件證據；pattern confidence>=7 且至少兩個不同事件。parked/superseded/retired 都不能新增 active projection。先前投影過且現已失效者，即使 confidence 降低仍需 tombstone。既有 receipt 決定是否重複，不拿已合成 knowledge page 當 canonical state。MCP ok 只代表 accepted，不能記 synced。

### 人類裁決與觀測

A1 排除自己投影與其衍生摘要；沒有不同 incident ID 不加 confidence。B1/B2 先 canonical ADR/rules 再記憶背景，疑似重複不自動降級；衝突交人選保留原決策或走 ADR/spec 變更。每次 invocation 獨立 audit JSON，避免多 session 覆蓋同檔；只收必要 identifiers，不存 token/整份 transcript。報表對 invocation ID 去重、retro 與 promotion 分開，率以有觀測結果的分母計算，缺值不當成零。

## Implementation Contract

- Skill 在 Step 0 準備一次 Hindsight availability 與 audit；Step 4b 信心分數確定前 search→read/semantic compare→必要時 reflect；Step 5 成功後才 prepare/ingest 與 initiative update。
- prepare CLI：python3 hindsight_projection.py prepare --input INPUT.json --output OUTPUT.json。INPUT 含 project、record、summary、evidence_ids、previous（optional）；record 是 canonical Mycelium row。OUTPUT action=ingest/skip；ingest 含僅 title/content 的 tool arguments、expected_doc_id、content_hash、revision_key、lifecycle。invalid JSON/schema exit 2，不產生可執行 MCP 呼叫；agent 將此視為可選 integration degraded。
- lifecycle priority：retired > superseded > parked > active。缺 record ID/project/key/confidence/type/source/tags、project 不符、不能確認證據或 previous ownership，均 fail closed，不發布。
- audit 每檔含 schema_version=1、invocation_id、project、kind=retro/promotion、sample_kind=live/smoke、retro_id、recorded_at、events、projections、decisions、metrics。events 含 operation、outcome、page_ids、fallback、human_decision；projections 僅存實際 accepted receipt。歷史 revision 留在 audit，不加入本次 hash 輸入，避免每次 hash 因引用前一版而改變。tombstone 明確撤回 active 的引用資格。
- report CLI：python3 hindsight_projection.py report --audit-dir DIR --project PROJECT。讀完成或中斷的 invocation receipts；相同 invocation ID 不重複計數，sample_kind=smoke 不算真實使用；同一 retro_id 多次執行只算一次。輸出 retro_count、measurement_ready（>=30）、四個 outcome ratio（duplicate/invalidated/cited/false_recurrence）、各分母與缺值。實際不足 30 時輸出 insufficient_data，不能製造樣本。
- retro audit 額外要求 canonical_written boolean；preflight 為 false，Step 4 確認寫入成功才為 true。未寫入或取消的 invocation 不計入30次門檻；promotion 不計次。
- B1/B2 規格在 ainization-skill 的隔離 worktree 實作；依 installed growth protocol 消費共同契約，不能 import yibi-stack checkout 的 tasks。
- 驗證：helper 行為單元測試；throwaway prepare/report 真實 CLI；MCP 在獨立臨時 bank 實跑同標題 replacement 與 tombstone；對 unavailable/schema missing 路徑做流程 walkthrough。不得寫入 production lesson bank 做測試。

## Risks / Trade-offs

- 非原生 metadata → server 不能對內容欄位做原生 filter；搜尋到合成頁時必須讀 provenance，不確定就排除 recurrence。
- 非 exactly-once transport → stable doc ID 只能避免邏輯文件倍增；timeout 不自動 retry，人工／下次確認 canonical state 後 reconcile。
- async extraction／頁面合成失敗 → accepted 與 queryable 分開呈現；保留 truthful degraded，不把 HTTP acceptance 當成 knowledge 可讀。
- 多 session 的同文件更新 → 每次寫前讀回 canonical；不同 worktree 共享 bank 但 audit 各檔。最新 canonical lifecycle 下次 invocation 修正 stale projection，不能以衍生資料回寫 canonical。

## Migration Plan

交付兩 repo 的 skill 變更；不改 DB、不改全域 runtime。按既有 plugin release/install 更新 growth，promotion 消費者檢查 helper/protocol 存在才啟用。rollback 為停用可選步驟，Mycelium 資料不受影響，已存 audit 保留。

## Open Questions

無未決產品選項；30 次真實 retro 成效屬於執行期驗收，未達門檻時報告明確 pending。

## 驗證紀錄（2026-09-30）

- helper 29 個行為案例通過；取消 retro 被錯計為完成的案例已先重現紅燈，再修正 canonical_written 篩選並確認綠燈。
- yibi-stack 全套 pytest：3433 passed、14 skipped、4 deselected。兩 repo 的變更檔 pre-commit 均通過；其他既存 changes 的 testplan／skill overlap advisory 未改動。
- prepare / report CLI 實跑：相同 accepted revision skip、低信心 parked row 產生同 ID tombstone、錯 project exit 2、不輸出可呼叫參數、取消與 smoke 不計入30次樣本。
- promotion 的實際 SELECT／UPDATE 在隔離 SQLite fixture 驗證；只有批准的 current-project active ID 改變，其他 project／parked／retired／superseded／archival／malformed tags 未改動。沒有寫入真實 lessons DB。
- 真實 MCP tools/list、diagnose、list pages 成功；temporary bank 的 active／parked ingest 均回傳相同 lesson-smoke-retry-boundary。抽取因共用 server 的 gpt-5.4-mini 與帳號不相容而失敗，文件 readback=404，故不宣稱 replacement 已完成；已刪除 temporary bank。
- 流程人工檢視（不是完整 live retro session）：缺 MCP 保留 Mycelium；projection-derived thematic hit 不計 recurrence；同 initiative identity 帶 relates_to_page_id，ambiguous／unknown 不盲建；相反 ADR 提供人類 A/B 選擇，不自動升級。
- 尚未部署 plugin、commit、push 或關閉 #425；runtime readback 與30次真實使用報告仍是未完成驗收，詳見 tasks 的阻擋紀錄。

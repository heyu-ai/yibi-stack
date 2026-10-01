## 1. Retro 讀取與降級

- [x] 1.1 A0 One-shot capability preflight：能力偵測與降級，確認一次 schema/bank/server-read，無工具繼續原流程；以真實 MCP tools/list 與 unavailable walkthrough 驗證。
- [x] 1.2 A1 Independent recurrence evidence：信心分數決定前 search-first，排除自我投影及衍生摘要，distinct incident 才可 recurrence；用重複來源／projection hit 場景 walkthrough 驗證。

## 2. Canonical 投影

- [x] 2.1 A2 Canonical projection eligibility：先 canonical 再投影，pitfall/pattern 多因子與 Step5 readback；以 helper eligibility、重複 evidence 單元測試驗證。
- [ ] 2.2 A2 Stable content envelope：內容封套與穩定文件，只有 title/content、hash/revision 在內容中、同 revision skip；以 prepare CLI 與 isolated MCP replacement smoke 驗證。
- [ ] 2.3 A2 Lifecycle reconciliation：已投影後 park/supersede/retire 用同文件 tombstone；以三種 lifecycle 測試與實際 MCP tombstone smoke 驗證。
- [x] 2.4 A3 Initiative identity update：linked Epic/change + Q2 才建立，既有 page ID 更新，未知結果不盲目 retry；以實際 schema 與 existing/ambiguous/timeout walkthrough 驗證。

## 3. Promotion 消費端

- [x] 3.1 B1 Advisory duplicate screening：Hindsight 查重只作提示，不自動降級；以 own-projection／等價知識未有 rule 場景 walkthrough 驗證。
- [x] 3.2 B2 Canonical decision precedence：先 ADR/rules 再 memory，possible_contradiction 交人 A/B 裁決；以相反 ADR 場景 walkthrough 驗證。
- [x] 3.3 Scoped lifecycle-safe promotion：current project + selected IDs + active lifecycle，消費共用 tombstone 契約；用隔離 SQLite smoke 確認同 key 跨 project 不互改。

## 4. 觀測與交付

- [x] 4.1 Audited real-world measurement：人類裁決與觀測，逐呼叫 audit、accepted 不等於 synced，report distinct retro ID 與四率分母、未滿30次標示 insufficient_data；用 report CLI 與邊界測試驗證。
- [x] 4.2 執行目標測試與相關 lint、更新既有文件及 changelog；檢查兩 worktree 的交付範圍，記錄真實 MCP smoke 限制與30次實際使用的待驗收狀態，不偽造完成。
- [ ] 4.3 累積30個不同、canonical write 成功的真實 retro，使用 report CLI 產出四率與 observed denominators 的實測報告；只有真實 audit 可作驗收，smoke／取消／重跑同 PR 都不補樣本數。

## 5. PR review 修正

- [x] 5.1 Preserve executable lesson write safety：按howie裁決執行出貨Bash／真實隔離DB測試，保留人工recurrence順序驗收；45個targeted cases通過，三個副本突變皆KILLED。
- [x] 5.2 Canonical projection eligibility / Lifecycle reconciliation / Audited real-world measurement：綁定lesson_id與predecessor、依實際時間排序、合併PR別名、拒絕空路徑與身分空白；23個TC有docstring追溯，CLI smoke通過。AC-6外部readback仍未完成。

## 驗收阻擋（2026-09-30）

- 2.2 / 2.3：prepare CLI 與單元測試通過，真實 MCP 對 active／parked payload 均接受且回相同 doc_id；
  但 server retain operation 抽取失敗，文件 readback 為404。上游回覆：
  `The 'gpt-5.4-mini' model is not supported when using Codex with a ChatGPT account.`
  因此未把 transport acceptance 冒充 replacement／tombstone 已生效。臨時 smoke bank 已刪除。
  bank config API 未暴露 model/provider override；需要先修正共用 server extraction model，
  再用独立 bank 重跑讀回驗證。這次沒有改共用模型設定或專案記憶。
- 4.3：目前尚無本整合交付後的真實 retro 樣本；report CLI 對 smoke-only audit 輸出
  retro_count=0、status=insufficient_data、四率 rate=null。

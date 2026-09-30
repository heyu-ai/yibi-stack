# integrate-retro-hindsight — Test Plan

trace: enforced

此表在 PR review 準備時補齊，追溯已存在的行為測試；不是聲稱所有 manual／runtime 驗收已通過。
Review Contract AC-1～AC-8 已由使用者確認。測試邊界為已交付的 prepare/report 公開介面與 agent MCP 操作流程；不以 source-text assertion 驗證 prose。

## Test Seams

| Seam | Public interface | Why here |
|------|------------------|----------|
| projection-prepare | hindsight_projection.prepare(payload) | agent 提交 canonical snapshot 後取得 ingest/skip 或拒絕；不 mock 本 repo 模組 |
| audit-report | hindsight_projection.report(directory, project) | 消費真實檔案形狀的 audit，觀察計數／分母／排除結果 |
| agent-mcp-workflow | pr-retrospective + HINDSIGHT.md 的 MCP calls | schema、bank、canonical ordering 與遠端 readback 必須用 agent/live walkthrough 驗證 |

## TC Table

| TC-ID | Kind | Seam | Scenario Slug | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|------|------|---------------|--------------|-----------|------|--------------|-------|-----------|-----------------|
| HSP-DT-001 | auto | projection-prepare | publication-thresholds | 發布門檻組合 | DT | High | canonical snapshot | 改 type/source/confidence/evidence 後 prepare | pitfall/pattern/operational；6/7/8/9 | 僅合格資料 ingest，其餘 skip 且無 arguments |
| HSP-ST-002 | auto | projection-prepare | changed-summary | 相同 revision skip、內容變更維持 ID | ST | High | accepted receipt | prepare→重跑→改 summary | 同 project/key | hash 更新、title/doc ID 不變，只傳 title/content |
| HSP-DT-003 | auto | projection-prepare | pattern-evidence-deduplication | evidence 順序與重複不增 revision | DT | Medium | 已發布 pattern | 重排並重複 evidence | p#1/p#2/p#1 | same_accepted_revision |
| HSP-ST-004 | auto | projection-prepare | inactive-record | 三種 inactive 低信心狀態 | ST | High | 先前 active projection | confidence 降至4並 park/supersede/retire | 三種 lifecycle | 無前次 receipt 時 skip；有則同ID tombstone；再次執行 skip |
| HSP-EG-005 | auto | projection-prepare | cross-project-receipt | foreign/unaccepted receipt 不覆寫 | EP | High | accepted receipt | 改 project/key/doc_id/outcome | wrong | ValueError，沒有 ingest |
| HSP-EG-006 | auto | projection-prepare | unsafe-key | slug collision 防護 | EP | High | canonical snapshot | 傳非kebab key | 大寫、底線、雙hyphen、空格、路徑 | 拒絕而不產生共用slug |
| HSP-EG-007 | auto | projection-prepare | missing-lifecycle | missing 不等於 active | EP | High | canonical snapshot | 逐一移除 lifecycle 欄位 | tags/retired_at/superseded_by | ValueError |
| HSP-BV-008 | auto | projection-prepare | publication-thresholds | effective confidence 邊界 | BVA | High | confidence=8 | effective_confidence 6.9→7 | 6.9/7 | skip→ingest |
| HSP-BV-009 | auto | audit-report | repeated-execution | 30次真實身份門檻 | BVA | High | temp audit directory | 29次+retry+smoke+promotion，再補第30次 | distinct retro IDs | 29仍不足；第30次才ready |
| HSP-DT-010 | auto | audit-report | measurement-observations | 未知與已觀測 false 分開 | DT | High | duplicate audit + later review | report | duplicate True→False，cited unknown | distinct invocation計次；duplicate=0/1；cited=null |
| HSP-EG-011 | auto | audit-report | measurement-observations | malformed audit 顯式排除 | EP | Medium | temp audit directory | 布林欄位給字串後report | cited="false" | excluded 含原因，不計樣本 |
| HSP-ST-012 | auto | audit-report | cancelled-retro | 取消不灌樣本 | ST | High | live invocation | canonical_written=false後report | cancelled retro | retro_count=0 |

## Coverage Analysis

| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| missing-tools | manual | — | MV-001；非 source-text test |
| projection-derived-hit | manual | — | MV-002 |
| canonical-write-failure | manual | — | MV-003 |
| publication-thresholds | covered | HSP-DT-001, HSP-BV-008 | Auto |
| missing-lifecycle | covered | HSP-EG-007 | Auto |
| pattern-evidence-deduplication | covered | HSP-DT-001, HSP-DT-003 | eligibility 與 revision normalization 不重複 |
| changed-summary | partial | HSP-ST-002 | prepare有覆蓋；遠端readback仍待MV-004（AC-6） |
| cross-project-receipt | covered | HSP-EG-005 | Auto |
| unsafe-key | covered | HSP-EG-006 | Auto |
| inactive-record | partial | HSP-ST-004 | helper有覆蓋；真實tombstone待MV-004（AC-6） |
| existing-initiative | manual | — | MV-005 |
| repeated-execution | covered | HSP-BV-009 | Auto |
| measurement-observations | covered | HSP-DT-010, HSP-EG-011 | 合法值與錯誤值兩種契約 |
| cancelled-retro | covered | HSP-ST-012 | Auto |
| equivalent-memory | external | — | ainization-skill伴隨PR；不冒稱本PR已驗證 |
| conflicting-adr | external | — | ainization-skill伴隨PR |
| shared-key-projects | external | — | ainization-skill伴隨PR |

## Manual Verification

- [ ] MV-001 AC-1：確認 tools/list、diagnose、bounded list preflight；缺工具／transport failure 只降級，不中斷 Mycelium，不逐lesson重探。既有實跑紀錄在 design，human quick pass仍待確認。
- [ ] MV-002 AC-2：用 projection-derived thematic hit／同incident多份摘要走查；不增加 recurrence，未知來源不當獨立證據。
- [ ] MV-003 AC-3：cancel／canonical failure／skip-if-exists 路徑走查；沒有成功readback就不能用準備中的參數發布。
- [ ] MV-004 AC-6：獨立bank真實MCP active→changed-active→inactive，讀回同document ID最新content。當前抽取模型不支援；accepted receipt不是成功證據。
- [ ] MV-005 AC-5：同 Epic/change 使用既有page ID；多筆候選／unknown timeout不盲建。記錄schema與actual call arguments。
- [ ] MV-006 AC-7：prepare/report CLI實跑，並確認30次真實使用報告仍留部署後追蹤，未由smoke補樣本。

## Missing Coverage

- 遠端 extraction／replacement／tombstone 的成功readback未通過；AC-6保持merge blocker。
- Skill orchestration依賴agent判讀，manual未確認前不能用helper單測代替。
- 30次真實retros成效需部署後累積，不包含於本PR的自動測試結果。

## Redundant TCs

無；參數化案例覆蓋互斥門檻、lifecycle狀態與錯誤邊界。

## Traceability Matrix

TC與scenario的對應以TC Table及pytest docstring的 `tc:`／`spec:` 為唯一資料來源。
測試檔：scripts/tests/test_hindsight_projection.py；現有pytest testpaths已包含 scripts/tests。

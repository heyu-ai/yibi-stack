# Proposal：add-figma-design-sync-skill

> 版本：v1.0 | 日期：2026-07-03 | 狀態：Draft

## Why

團隊使用 Figma 做 UI 設計、用 OpenSpec/Spectra 管理規格，但兩者之間沒有落地管道：

- 展開規格時，agent 與開發者需要反覆開 Figma 查畫面、狀態、文案，設計資訊散落且不可追溯
- 設計改版後，spec 與設計悄悄漂移——沒有機制知道「哪些 scenario 受影響」
- 每台機器、每個 session 都重抓一次 Figma，token 與時間成本高

需要一個 SDD plugin skill：把 Figma 設計上下文**一次性落地**到 change 目錄
（文字進 git、截圖留本地），供 spectra-amplifier 展開規格引用；
之後只在設計異動時執行 sync 拿增量更新。

## What Changes

- 新增 plugin-only skill `plugins/sdd/skills/figma-design-sync/`（SKILL.md + design-context-template.md + manifest-schema.md）
- 產出物：`openspec/changes/<name>/design/`（design-context.md、figma-manifest.json 進 git；assets/*.png gitignore）
- spectra-amplifier 掛接：Step 0 決策表加 2 列、Step 1a 加設計輸入段、Step 3 加 UI 對應小節、兩處目錄樹加 `design/`
- `.gitignore` 加 `openspec/changes/*/design/assets/`
- sdd plugin 版本 1.5.0 → 1.6.0（package.json 與 plugin.json 手動 lockstep）

## Capabilities

### New Capabilities

- `figma-design-sync`: Figma 設計擷取（extract）與增量同步（sync）的完整行為規格

## Step 1 — User Stories

### 四元素萃取

| 元素 | 內容 |
|------|------|
| **Actors** | 規格撰寫者（跑 amplifier 的人）、後續開發者（讀 design/ 的人）、spectra-amplifier skill、Figma MCP server |
| **Actions** | extract（首次擷取）、sync（增量同步）、assets restore（補抓缺圖）、amplifier 讀取 design-context.md |
| **Data** | design-context.md、figma-manifest.json、assets/*.png、Figma node 樹 metadata（結構指紋來源；get_metadata 不含 file 版本，version/lastModified 為 best-effort） |
| **Constraints** | 截圖不進 git；Figma MCP 無 per-node 版本（指紋比對有盲點）；screens >40 必須縮小範圍；design/ 不存在時 amplifier 行為不變 |

---

### US-001：設計一次落地（extract）

**Persona**：規格撰寫者——拿到 Figma 設計稿連結，準備為新功能展開 OpenSpec change
**Action**：貼上 figma.com URL，執行 figma-design-sync 的 extract 模式
**Outcome**：change 目錄出現完整的 design/（結構化文字上下文 + manifest + 本地截圖），
後續展開規格與開發都不必再開 Figma

**Acceptance Criteria**：

- AC-001-1：GIVEN 合法的 figma.com URL 與既有 change 目錄 WHEN 執行 extract THEN 產出 design-context.md、figma-manifest.json、assets/*.png 三類產物，且文字產物可被 git 追蹤、截圖不被 git 追蹤
- AC-001-2：GIVEN Figma MCP 未連接或 auth 失敗 WHEN 執行 extract THEN 以 `[FAIL]` 停止並給出修復指引，不產出殘缺檔案
- AC-001-3：GIVEN file 內 screens 數量超過範圍上限 WHEN 執行 extract THEN 依 guard 決策表警告或要求縮小範圍，不得靜默全抓
- AC-001-4：GIVEN 某個 screen node 的 MCP 呼叫失敗 WHEN 其他 screens 擷取成功 THEN 失敗的 screen 標 `[BLOCKED]` 且不中斷整批，最終摘要列出 blocked 清單
- AC-001-5：GIVEN 掃描範圍含引用外部 library 元件的 INSTANCE WHEN 執行 extract THEN 每個 instance 記入 manifest `componentRef`，且「被引用但定義未盤點」的元件以 `[WARN]` 清單列出（不靜默略過）；skill 明文記載只讀當前 file 引用足跡、不枚舉外部 library 全目錄

### US-002：只有必要時才 sync

**Persona**：後續開發者——實作途中想確認設計是否有更新，或 fresh clone 後本地沒有截圖
**Action**：執行 figma-design-sync 的 sync 模式
**Outcome**：設計無變更時一次便宜的呼叫即回報 `[OK]`；有變更時只重抓變更的部分，
並提示哪些 spec scenario 可能受影響

**Acceptance Criteria**：

- AC-002-1：GIVEN 所有 status="ok" node 的結構指紋與 manifest 相同且本地截圖齊全 WHEN 執行 sync THEN 回報 `[OK] 設計結構無變更` 並零寫入早退
- AC-002-2：GIVEN 結構指紋全相同但本地截圖缺失 WHEN 執行 sync THEN 只對 status="ok" 缺圖 node 補抓（assets restore、跳過 blocked、補抓失敗須回報缺補清單），不改動 design-context.md 與 manifest
- AC-002-3：GIVEN node 結構指紋比對出 changed 與 added nodes WHEN 執行 sync THEN 只重抓 changed/added nodes，design-context.md 修改處帶 `[MODIFIED]`、新增處帶 `[ADDED]` delta markers
- AC-002-4：GIVEN 設計僅有文案/樣式/token 等非結構變更（結構指紋全同） WHEN 執行 sync THEN 系統結構性早退（get_metadata 無 file 版本可偵測此類變更），此盲點於 SKILL.md/manifest-schema.md 明文記載，使用者以 full re-extract 兜底
- AC-002-5：GIVEN sync 偵測到 changed screens WHEN 產出 diff 摘要 THEN 以 screen slug 檢索 specs/ 並列出可能受影響的 `#### Scenario:` 清單
- AC-002-6：GIVEN manifest 中某 node 在新 metadata 樹消失且缺失比例未觸發完整性 gate WHEN 執行 sync THEN design-context.md 加 `[REMOVED]` 墓碑；缺失超過半數時系統先 `[WARN]` 要求確認，不得直接大量標墓碑

### US-003：融入 spectra-amplifier 展開流程

**Persona**：規格撰寫者——用 spectra-amplifier 展開 change 時，希望設計資訊自動參與而非人工搬運
**Action**：執行 spectra-amplifier（design/ 已存在或需求含 Figma URL）
**Outcome**：amplifier 自動先落地/同步設計，Step 1a 四元素萃取吸收設計上下文，
design.md 以引用方式連到 design/，全程 single source

**Acceptance Criteria**：

- AC-003-1：GIVEN 需求含 figma.com URL 且 design/ 不存在 WHEN 執行 amplifier Step 0 THEN 依決策表先執行 figma-design-sync extract；Figma MCP 不可用時 `[WARN]` 略過並繼續既有流程
- AC-003-2：GIVEN design/design-context.md 存在 WHEN 執行 amplifier Step 1a THEN 必須讀取設計上下文，`[DESIGN GAP]` 項目轉為 `[NEEDS CLARIFICATION]`（計入上限 3）或 Step 0.5 的 W
- AC-003-3：GIVEN design/ 不存在且需求無 Figma URL WHEN 執行 amplifier THEN 行為與掛接前完全相同（向後相容）
- AC-003-4：GIVEN design/figma-manifest.json 已存在 WHEN 執行 amplifier Step 0 THEN 先執行 figma-design-sync（sync 模式）確認設計未過期，`[OK]` 或使用者確認忽略後才讀 design-context.md 繼續

---

## Step 1c — Gherkin Scenarios

> Gherkin scenarios 寫於 `specs/figma-design-sync/spec.md`（`#### Scenario: <slug> -- <title>` 格式）。
> 本 proposal.md 只記錄 US + AC；scenario slug 透過 Traceability Matrix 追溯。

---

## Step 4 — 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | ~~Figma MCP `get_metadata` 回傳 file 級 `version`/`lastModified`~~ **已驗證不成立**（get_metadata 只回傳 node 樹，schema：「only includes node IDs, layer types, names, positions and sizes」）。設計改採 **node 結構指紋為唯一比對依據**（原「退化路徑」轉為主路徑），成本結構不變（cheap metadata 一呼 + 選擇性昂貴重抓） | 非結構變更（文案/樣式/token）不改變指紋、亦無 file 版本可偵測，成為已記載盲點，以 full re-extract 兜底 |
| A2 | node 的 `name/type/width/height/childCount/descendantSummary` 足以偵測結構層級變更 | 指紋誤判率升高；由 S2 `[WARN]` 三選項與 full re-extract 兜底 |
| A3 | 截圖對開發者是輔助參照，文字上下文才是餵 spec 的主體 | 若截圖成為必要品，gitignore 策略需重新評估（見 Out of Scope） |
| A4 | 使用者會在 change 目錄已存在的前提下執行 extract | change 不存在時 skill 詢問使用者，不自行產 proposal.md |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | assets/*.png 不得進 git | 使用者指示：截圖留本地給人看，repo 不承受 binary 膨脹 |
| C2 | Figma MCP `get_metadata` 不提供 file 版本，也不提供 per-node 版本 | Figma MCP API 能力邊界；sync 以結構指紋比對，純文案/樣式/token 變更對指紋不可見 |
| C3 | design/ 不存在時 spectra-amplifier 行為必須與掛接前完全相同 | 向後相容；amplifier 是 sdd plugin 核心，不得破壞既有流程 |
| C4 | screens > 40 必須縮小範圍後才能 extract | 防止 design context 撐爆 agent context window |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| Git LFS 管理截圖 | 本次採 gitignore 即滿足「repo 不膨脹」；LFS 增加基礎設施成本 | 若截圖成為 spec 審查必要品再評估 |
| `download_assets` 下載 icon/插圖資產 | 截圖已足夠視覺參照；icon 屬實作期資源 | 實作期有需求時以選用步驟開啟 |
| Figma prototype 互動細節（動畫、transition） | get_design_context 不穩定提供；flows 以推斷 + `inferred` 標記表達 | Figma MCP 能力擴充後再評估 |
| design tokens 自動轉 code（CSS variables 等） | 本 skill 職責是落地資訊，不是 design-to-code | 屬另一個 skill 的範疇 |
| 枚舉外部 published library 的完整元件/token 目錄 | Figma MCP 未提供 list-library-components 類工具；本 skill 只讀當前 file 的引用足跡（instance 記入 componentRef，完整性 gate 標示未落地者） | 對 library file URL 另跑 extract 當獨立 design source；或 MCP 擴充 library endpoint 後再評估 |
| Component variant 完整盤點 | 預設只抓代表性 states 以控制 context window；full-variant 覆蓋為未定調成本的可選旗標 | 手動指定 COMPONENT_SET node-id 全抓；或加 opt-in 旗標（待定範圍） |

---

## Step 5 — 完工標準

### Done 定義

此 change 視為「完成」的條件：

- [ ] 三個 skill 檔案齊備且通過 markdownlint 與 lint_skill_bash
- [ ] spectra-amplifier 四處掛接完成，且新決策表列與本 change spec.md scenarios 對齊
- [ ] `.gitignore` 含 assets 規則；`git check-ignore` 驗證通過
- [ ] sdd plugin 版本 lockstep bump（package.json 與 plugin.json 均為 1.6.0）
- [ ] `make ci` 全綠
- [ ] design/ 不存在時 amplifier 行為不變（walkthrough 驗證）

### 冒煙測試情境

#### Scenario: smk-extract-happy-path -- SMK-001 extract 正常路徑

**GIVEN** 合法 Figma URL、change 目錄存在、Figma MCP 已認證
**WHEN** 執行 figma-design-sync extract
**THEN** 系統 MUST 產出 design-context.md + figma-manifest.json + assets/*.png，
且 git MUST NOT 追蹤 assets/

#### Scenario: smk-sync-early-exit -- SMK-002 sync 無變更早退

**GIVEN** manifest 與 Figma 現況結構指紋相同、本地截圖齊全
**WHEN** 執行 figma-design-sync sync
**THEN** 系統 MUST 回報 `[OK] 設計結構無變更` 且 MUST NOT 寫入任何檔案

#### Scenario: smk-amplifier-backward-compat -- SMK-003 amplifier 向後相容

**GIVEN** change 無 design/ 目錄且需求不含 Figma URL
**WHEN** 執行 spectra-amplifier
**THEN** 行為 MUST 與掛接前完全相同，MUST NOT 出現任何 figma 相關提示

### Traceability Matrix

| US | Gherkin Scenario slug | TC-ID | 驗證方式 |
|----|----------------------|-------|---------|
| US-001 | `extract-outputs-complete` | FDS-ST-001 | E2E extract 或 walkthrough |
| US-001 | `mcp-unavailable-fail-stop` | FDS-DT-001 | walkthrough |
| US-001 | `extract-auth-probe-fail` | FDS-DT-002 | walkthrough |
| US-001 | `extract-scope-guard-warn` | FDS-DT-003 | walkthrough |
| US-001 | `extract-partial-failure-blocked` | FDS-EG-001 | walkthrough |
| US-001 | `extract-instance-inventory-and-component-completeness` | FDS-ST-004 | E2E / walkthrough |
| US-001 | `assets-not-tracked-by-git` | FDS-VL-001 | `git check-ignore` |
| US-002 | `sync-no-change-early-exit` | FDS-DT-004 | E2E sync 或 walkthrough |
| US-002 | `sync-assets-restore` | FDS-DT-005 | E2E 刪圖再 sync |
| US-002 | `sync-incremental-delta-markers` | FDS-DT-006 | E2E 改設計再 sync |
| US-002 | `sync-fingerprint-blind-spot-warn` | FDS-EG-002 | walkthrough |
| US-002 | `sync-node-removed-tombstone` | FDS-EG-004 | walkthrough |
| US-002 | `sync-spec-impact-hint` | FDS-ST-002 | walkthrough |
| US-003 | `amplifier-step0-figma-url-detected` | FDS-DT-007 | walkthrough |
| US-003 | `amplifier-step0-manifest-exists-sync` | FDS-DT-011 | walkthrough |
| US-003 | `amplifier-step1a-reads-design-context` | FDS-ST-003 | walkthrough |
| US-003 | `amplifier-backward-compatible` | FDS-VL-002 | walkthrough |

> 本 change 為 skill/文件變更，無 Python 實作；驗證以 lint、`git check-ignore`、
> E2E（真 Figma file）與 SKILL.md 決策表逐列 walkthrough 為主，不使用 pytest trace。

## Impact

- Affected specs:
  - New: `figma-design-sync`
- Affected code:
  - New: `plugins/sdd/skills/figma-design-sync/`（SKILL.md、design-context-template.md、manifest-schema.md）
  - Modified: `plugins/sdd/skills/spectra-amplifier/SKILL.md`、`plugins/sdd/package.json`、
    `plugins/sdd/.claude-plugin/plugin.json`、`plugins/sdd/README.md`、`skills/README.md`、`.gitignore`

# figma-design-sync — Spec

## ADDED Requirements

### Requirement: Mode selection via self-contained decision table

The skill SHALL select its execution mode (extract or sync) from a self-contained
decision table keyed on the presence and content of
`openspec/changes/<name>/design/figma-manifest.json`, and MUST NOT proceed when the
Figma MCP tools are unavailable.

#### Scenario: mode-extract-when-no-manifest -- manifest 不存在時走 extract

- **GIVEN** change 目錄存在且 `design/figma-manifest.json` 不存在
- **WHEN** 使用者提供 figma.com URL 執行 figma-design-sync
- **THEN** 系統 MUST 進入 extract 模式

#### Scenario: mode-sync-when-manifest-matches -- manifest 存在且 fileKey 相同時走 sync

- **GIVEN** `design/figma-manifest.json` 存在且可解析
- **WHEN** 使用者未提供 URL，或提供的 URL 之 fileKey 與 manifest 相同
- **THEN** 系統 MUST 進入 sync 模式

#### Scenario: mode-filekey-mismatch-confirm -- fileKey 不同時須確認後才覆蓋

- **GIVEN** manifest 存在，但使用者提供的 URL 之 fileKey 與 manifest 不同
- **WHEN** 執行 figma-design-sync
- **THEN** 系統 MUST 回報兩個 fileKey 並徵求使用者確認
- **AND** 系統 MUST NOT 在未確認前覆蓋既有 design/

#### Scenario: mode-corrupt-manifest-reextract -- manifest 壞損時重建

- **GIVEN** `design/figma-manifest.json` 存在但 JSON 無法解析
- **WHEN** 執行 figma-design-sync
- **THEN** 系統 MUST 提示刪除 manifest 後以 extract 模式重建（比照 detection-cache 慣例）

#### Scenario: mcp-unavailable-fail-stop -- Figma MCP 不可用時硬停

- **GIVEN** 目前 session 的 tool 清單中沒有任何 `mcp__Figma__*` 工具
- **WHEN** 執行 figma-design-sync（任一模式）
- **THEN** 系統 MUST 以 `[FAIL] Stop.` 停止並提示連接 Figma MCP
- **AND** 系統 MUST NOT 產出任何檔案

---

### Requirement: Extract produces a complete, git-clean design context

In extract mode the skill SHALL verify authentication with a read-only probe,
build a node inventory, capture per-screen design context and screenshots, and
produce exactly three artifact classes: `design-context.md` and
`figma-manifest.json` (git-tracked) plus `assets/*.png` (git-ignored).
Every MCP call MUST be followed by an explicit failure gate.

#### Scenario: extract-auth-probe-fail -- auth probe 失敗即停

- **GIVEN** Figma MCP 已連接但認證失效
- **WHEN** extract Step 0 呼叫 `mcp__Figma__whoami`
- **THEN** 系統 MUST 以 `[FAIL]` 停止並導向 OAuth 修復指引
- **AND** 系統 MUST NOT 繼續呼叫後續 MCP 工具

#### Scenario: extract-outputs-complete -- extract 產出三類產物

- **GIVEN** 合法 Figma URL、change 目錄存在、認證有效
- **WHEN** extract 全部步驟完成
- **THEN** `design/` MUST 含 design-context.md 與 figma-manifest.json
- **AND** 每個成功擷取的 screen MUST 有對應的 `assets/<screen-slug>.png`
- **AND** design-context.md 頂部 MUST 註記「截圖不入 git；缺圖時執行 sync 補抓」

#### Scenario: extract-scope-guard-warn -- screens 數量超限時警告或必縮

- **GIVEN** node inventory 判定的 screens 數量為 N
- **WHEN** N > 15
- **THEN** 系統 MUST 輸出 `[WARN]` 並建議以 section node-id 縮小範圍，經使用者確認才全抓
- **AND** 當 N > 40 時系統 MUST 要求縮小範圍且 MUST NOT 全抓

#### Scenario: extract-partial-failure-blocked -- 單 node 失敗不中斷整批

- **GIVEN** 多個 screen nodes 待擷取
- **WHEN** 其中一個 node 的 `get_design_context` 或 `get_screenshot` 呼叫失敗
- **THEN** 該 screen 在 design-context.md 對應章節 MUST 標 `[BLOCKED: <原因>]`
- **AND** manifest 中該 node 的 `status` MUST 為 `"blocked"`
- **AND** 其餘 screens MUST 繼續擷取，最終摘要 MUST 列出 blocked 清單

#### Scenario: assets-not-tracked-by-git -- 截圖不被 git 追蹤

- **GIVEN** extract 已寫入 `design/assets/*.png`
- **WHEN** 執行 `git status`
- **THEN** assets/ 下的檔案 MUST NOT 出現在 untracked 清單
  （`.gitignore` 含 `openspec/changes/*/design/assets/`）

---

### Requirement: Sync exits early when design is unchanged

In sync mode the skill SHALL determine change status with a single
`get_metadata` call. When the file-level `version` and `lastModified` match the
manifest and all local screenshots exist, it MUST report no change and exit with
zero writes. When screenshots recorded in the manifest are missing locally, it
MUST re-download only those screenshots without treating it as a design change.

#### Scenario: sync-no-change-early-exit -- 無變更時零寫入早退

- **GIVEN** manifest 的 version 與 lastModified 與 `get_metadata` 回傳值相同
- **AND** manifest `nodes[].screenshot` 記錄的所有檔案在本地存在
- **WHEN** 執行 sync
- **THEN** 系統 MUST 回報 `[OK] 設計無變更（version <version>）`
- **AND** 系統 MUST NOT 寫入或修改任何檔案

#### Scenario: sync-assets-restore -- fresh clone 後補抓缺圖

- **GIVEN** version 與 lastModified 與 manifest 相同
- **AND** manifest 記錄的截圖中有 N 張在本地缺失（fresh clone 或換機器）
- **WHEN** 執行 sync
- **THEN** 系統 MUST 只對缺失的 N 個 nodes 重抓 `get_screenshot`
- **AND** 系統 MUST NOT 修改 design-context.md 與 manifest 的 version 欄位
- **AND** 回報 MUST 註明「補抓 N 張缺圖」而非設計變更

---

### Requirement: Sync applies incremental updates with delta markers

When the file version changes, the skill SHALL compare per-node fingerprints
(`name + type + width + height + childCount + descendantSummary`) against the
manifest, re-fetch only changed and added nodes, and mark every touched section
in `design-context.md` with `[ADDED]` / `[MODIFIED]` / `[REMOVED]` delta markers.
The fingerprint blind spot (copy or style changes invisible to metadata) MUST be
escalated to the user, never silently resolved.

#### Scenario: sync-incremental-delta-markers -- 只重抓變更 nodes 並標 delta markers

- **GIVEN** version 已變且指紋比對出 changed 與 added nodes
- **WHEN** 執行 sync
- **THEN** 系統 MUST 只對 changed/added nodes 重跑 design context 與截圖擷取
- **AND** design-context.md 更新處 MUST 帶 `[ADDED]` 或 `[MODIFIED]` 標記
- **AND** manifest MUST 更新為新的 version、lastModified、extractedAt 與 node 指紋

#### Scenario: sync-fingerprint-blind-spot-warn -- 指紋盲點交使用者決定

- **GIVEN** version 已變但所有 tracked nodes 的指紋均相同
- **WHEN** 執行 sync
- **THEN** 系統 MUST 輸出 `[WARN]` 說明可能是文案/樣式層級變更（metadata 不可見）
- **AND** 系統 MUST 提供三個選項（全量 design context 重抓 / full re-extract / 忽略）交使用者
- **AND** 系統 MUST NOT 自行選擇任一選項

#### Scenario: sync-node-removed-tombstone -- 消失的 node 標墓碑

- **GIVEN** manifest 中某 node 在新的 metadata 樹中不存在
- **WHEN** 執行 sync
- **THEN** design-context.md 對應章節 MUST 加 `[REMOVED]` 墓碑與原因
- **AND** 本地截圖檔 MAY 保留，但摘要 MUST 提示可刪

#### Scenario: sync-spec-impact-hint -- diff 摘要附 spec 影響提示

- **GIVEN** sync 產生了 changed screens 清單
- **WHEN** 輸出 diff 摘要
- **THEN** 系統 MUST 以 changed screen 的 slug 與名稱檢索
  `openspec/changes/<name>/specs/` 下的 `#### Scenario:` heading
- **AND** 有命中時 MUST 列出可能受影響的 scenario 清單並建議以 spectra-amplifier 修訂
- **AND** 無命中時 MUST 註明「未找到直接引用，請人工確認」

---

### Requirement: Spectra-amplifier integration is additive and backward compatible

The spectra-amplifier hooks SHALL only add pre-steps and reading inputs.
When `design/` does not exist and the request contains no Figma URL, amplifier
behavior MUST be identical to the pre-hook version.

#### Scenario: amplifier-step0-figma-url-detected -- Step 0 偵測 Figma URL 先落地設計

- **GIVEN** 需求描述含 figma.com URL 且 `design/` 不存在
- **WHEN** 執行 spectra-amplifier Step 0
- **THEN** 系統 MUST 依決策表先執行 figma-design-sync（extract 模式）
- **AND** 若 Figma MCP 不可用，系統 MUST 輸出 `[WARN]` 略過設計擷取並繼續既有流程

#### Scenario: amplifier-step0-manifest-exists-sync -- Step 0 偵測 manifest 先 sync

- **GIVEN** `design/figma-manifest.json` 已存在
- **WHEN** 執行 spectra-amplifier Step 0
- **THEN** 系統 MUST 先執行 figma-design-sync（sync 模式）確認設計未過期
- **AND** `[OK]` 或使用者確認忽略後才讀取 design-context.md 繼續

#### Scenario: amplifier-step1a-reads-design-context -- Step 1a 吸收設計上下文

- **GIVEN** `design/design-context.md` 存在
- **WHEN** 執行 amplifier Step 1a 四元素萃取
- **THEN** 系統 MUST 讀取 design-context.md 的畫面清單、流程、元件狀態與文案表
- **AND** `[DESIGN GAP]` 項目 MUST 轉為 `[NEEDS CLARIFICATION]`（計入上限 3）或 Step 0.5 的 W

#### Scenario: amplifier-backward-compatible -- 無 design/ 時行為不變

- **GIVEN** change 無 `design/` 目錄且需求不含 figma.com URL
- **WHEN** 執行 spectra-amplifier 完整流程
- **THEN** 系統行為 MUST 與掛接前完全相同
- **AND** 輸出 MUST NOT 出現任何 figma 相關提示或警告

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

- **GIVEN** 目前 session 的 tool 清單中沒有任何 Figma MCP 工具（無任何以 `get_design_context`/`get_metadata` 等 base name 結尾的工具；namespace 前綴依連接器註冊名而定）
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

#### Scenario: extract-instance-inventory-and-component-completeness -- 元件實例盤點與完整性 gate

- **GIVEN** 掃描範圍內存在引用某 main component 的 `INSTANCE` 節點（含外部 library 元件）
- **WHEN** extract 完成盤點
- **THEN** 每個 instance MUST 記入 manifest `nodes[].componentRef`（main component 名稱 + 是否外部 library）
- **AND** 系統 MUST 比對「被引用的 main component」與「已盤點的 component 定義」，
  被引用但定義未落地者 MUST 以 `[WARN]` 清單列出（不得靜默略過）
- **AND** 系統 MUST 記載本 skill 只讀當前 file 的引用足跡、不枚舉外部 library 完整目錄
  （需完整落地 library 時對 library file URL 另跑 extract）

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
`get_metadata` call, comparing each tracked node's structural fingerprint
(`name + type + width + height + childCount + descendantSummary`) against the
manifest. `get_metadata` does not return a file-level version, so the structural
fingerprint is the sole comparison basis. When all `status="ok"` node fingerprints
match the manifest and all local screenshots exist, it MUST report no change and
exit with zero writes. When screenshots recorded in the manifest are missing
locally, it MUST re-download only those (`status="ok"` nodes only), report any
restore-fetch failures, and MUST NOT treat it as a design change.

#### Scenario: sync-no-change-early-exit -- 結構無變更時零寫入早退

- **GIVEN** 所有 `status="ok"` tracked node 的結構指紋與 manifest 相同
- **AND** manifest `nodes[].screenshot` 記錄的所有檔案在本地存在
- **WHEN** 執行 sync
- **THEN** 系統 MUST 回報 `[OK] 設計結構無變更`
- **AND** 系統 MUST NOT 寫入或修改任何檔案

#### Scenario: sync-assets-restore -- fresh clone 後補抓缺圖

- **GIVEN** 所有 tracked node 結構指紋與 manifest 相同
- **AND** manifest 記錄的截圖中有 N 張在本地缺失（fresh clone 或換機器）
- **WHEN** 執行 sync
- **THEN** 系統 MUST 只對缺失且 `status="ok"` 的 nodes 重抓 `get_screenshot`（跳過 `status="blocked"`）
- **AND** 任一補抓失敗 MUST 列出缺補清單回報，MUST NOT 靜默宣稱已補齊
- **AND** 系統 MUST NOT 修改 design-context.md 與 manifest
- **AND** 回報 MUST 註明「補抓 N 張缺圖」而非設計變更

---

### Requirement: Sync applies incremental updates with delta markers

When per-node structural fingerprints differ from the manifest, the skill SHALL
re-fetch only changed and added nodes, and mark every touched section in
`design-context.md` with `[ADDED]` / `[MODIFIED]` / `[REMOVED]` delta markers.
Before writing `[REMOVED]` tombstones the skill MUST apply a completeness gate (a
`get_metadata` response missing a large fraction of tracked nodes is treated as
possibly truncated, not mass deletion). Non-structural changes (copy / style /
token) are invisible to metadata fingerprints and, absent a file version signal,
cannot be detected by sync; this blind spot MUST be documented and the user
directed to a full re-extract when they know content changed.

#### Scenario: sync-incremental-delta-markers -- 只重抓變更 nodes 並標 delta markers

- **GIVEN** 指紋比對出 changed 與 added nodes（既有 node 尺寸/結構改變，且另有新增 node）
- **WHEN** 執行 sync
- **THEN** 系統 MUST 只對 changed/added nodes 重跑 design context 與截圖擷取
- **AND** design-context.md 修改處 MUST 帶 `[MODIFIED]` 標記、新增處 MUST 帶 `[ADDED]` 標記
- **AND** manifest MUST 更新為新的 extractedAt 與受影響 node 的結構指紋（file version 為 best-effort）

#### Scenario: sync-fingerprint-blind-spot-warn -- 非結構變更盲點，導向 full re-extract

- **GIVEN** 設計僅有文案/顏色/樣式/token 變更，所有 tracked nodes 的結構指紋均相同
- **WHEN** 執行 sync
- **THEN** 系統判定結構無變更並早退（`get_metadata` 無 file 版本可偵測此類變更，為已記載盲點）
- **AND** SKILL.md 與 manifest-schema.md MUST 明文記載此盲點，MUST NOT 假裝能偵測
- **AND** 使用者已知有非結構變更時 MUST 能以 full re-extract 重建

#### Scenario: sync-node-removed-tombstone -- 消失的 node 標墓碑

- **GIVEN** manifest 中某 node 在新的 metadata 樹中不存在（且缺失比例未觸發完整性 gate）
- **WHEN** 執行 sync
- **THEN** design-context.md 對應章節 MUST 加 `[REMOVED]` 墓碑與原因
- **AND** 本地截圖檔 MAY 保留，但摘要 MUST 提示可刪
- **AND** 若缺失的 tracked node 超過總數一半，系統 MUST 先輸出 `[WARN]`（疑似 metadata 回應不完整）並要求確認，MUST NOT 直接寫入大量墓碑

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

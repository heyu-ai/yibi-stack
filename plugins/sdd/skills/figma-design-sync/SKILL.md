---
name: figma-design-sync
type: tool
scope: project
description: >
  Figma 設計擷取與同步 skill：把 Figma file/frame 的設計上下文（畫面清單、互動流程、
  UI 元件與狀態、design tokens、文案、edge cases）落地到
  openspec/changes/<change-name>/design/，供 spectra-amplifier 展開規格引用，
  後續開發不必反覆開 Figma。
  適用情境：使用者貼上 figma.com URL、提到「讀 Figma」「Figma 設計稿」「設計轉 spec」
  「figma sync」「設計同步」「design handoff」「把設計落地」「抓設計稿」「設計更新了」
  「UI 稿」「mockup 轉需求」「設計稿轉規格」時必須觸發。

effort: medium
---

# Figma Design Sync

你是設計資訊的落地者：把 Figma 設計轉為結構化、可追溯、進 git 的設計上下文，
讓規格展開與後續開發**不必反覆開 Figma**。你不是 design-to-code 產生器——
產出物是餵給 spectra-amplifier 的規格素材，不是前端程式碼。

## 核心理念

> **設計資訊 clone 即有（文字層），Figma 只在 sync 時開。**
> design-context.md 與 manifest 進 git 是主體；截圖留本地給人看、不進 git。
> sync 的 warm path 是一次便宜的 metadata 呼叫——設計沒變就零寫入早退。

---

## 輸出結構

```text
openspec/changes/<change-name>/design/
├── design-context.md      # 結構化設計上下文（餵 spectra-amplifier Step 1a）— 進 git
├── figma-manifest.json    # sync 比對依據（fileKey / version / node 指紋）— 進 git
└── assets/
    └── <screen-slug>.png  # 每個 screen 截圖 — 本地保留、gitignore 不進 git
```

- 文件骨架見同目錄 `design-context-template.md`（owner；amplifier 只引用不複製）。
- manifest 欄位與比對規則見同目錄 `manifest-schema.md`。
- 截圖不進 git（`.gitignore` 的 `openspec/changes/*/design/assets/` 規則）；
  fresh clone 後本機無圖時，執行本 skill 的 sync 模式會自動補抓（assets restore）。

---

## 模式決策表

依下表決定執行模式（`manifest` 指 `openspec/changes/<change-name>/design/figma-manifest.json`）：

| 狀況 | 模式 |
|------|------|
| 目前 session 的 tool 清單中沒有任何 `mcp__Figma__*` 工具 | `[FAIL] Stop. Figma MCP 未連接。請在 claude.ai 連接器設定或 claude mcp 加入 Figma 後重跑。` 不產出任何檔案 |
| manifest 不存在 | **extract** |
| manifest 存在且可解析、使用者未給 URL 或 URL 的 fileKey 與 manifest 相同 | **sync** |
| manifest 存在、URL 的 fileKey 與 manifest 不同 | 回報兩個 fileKey 與各自的 fileName，徵求使用者確認換 file 的意圖；確認後 **extract**（覆蓋，先提醒 design/ 將重建）；未確認前不得覆蓋 |
| manifest 存在但 JSON 無法解析 | `[WARN] manifest 壞損。` 提示刪除 `design/figma-manifest.json` 後重跑（自動走 extract 重建） |
| 使用者明確要求 full re-extract | **extract**（重建整個 design/） |

---

## Extract 模式

### Step 0 — 輸入解析與前置檢查

1. 解析 Figma URL：`https://www.figma.com/design/{{file_key}}/{{file_name}}?node-id={{node_id}}`。
   - 解析不出 `file_key` → 停止，請使用者提供完整 URL（在 Figma 中對 frame 按右鍵 → Copy link to selection）。
   - 沒有 `node-id` → `[WARN] URL 未含 node-id，將以整個 file 為範圍；建議提供 section/page 的 node-id 縮小範圍。` 繼續。
2. 確認 `openspec/changes/{{change_name}}/` 存在。不存在 → 詢問使用者：
   先執行 `/spectra-propose {{change_name}}` 建立 change，或確認後僅建立 `design/` 目錄
   （本 skill 只擁有 `design/` 子目錄，不產 proposal.md）。
3. Auth probe：呼叫 `mcp__Figma__whoami` 確認認證狀態。
   If the call fails or returns an auth error, stop and report:
   `[FAIL] Figma MCP 認證失敗。請在 claude.ai 連接器設定完成 Figma OAuth 授權後重跑。`
   不得繼續呼叫後續 MCP 工具。

### Step 1 — Node Inventory

呼叫 `mcp__Figma__get_metadata`（fileKey: `{{file_key}}`，有 node-id 時帶 nodeId: `{{node_id}}`）
取得 node 樹與 file 版本資訊。
If the call fails, stop and report the error to the user.

記錄 file 的 `version` 與 `lastModified`（寫入 manifest 用），然後依下表分類 nodes：

| Node | 分類 |
|------|------|
| page / section 直屬子節點且 type=FRAME | **screen**（進 Step 2 逐一擷取） |
| type=COMPONENT / COMPONENT_SET | **component**（記入 inventory；Step 2 只對代表性 states 擷取 design context，不逐 variant 截圖） |
| type=SECTION | 展開其子 FRAME 為 screens |
| 隱藏層、標註層、name 以 `_` 或 `.` 開頭 | 略過，記入 manifest 的 `skippedNodes` |

**範圍 guard**（防止 design context 撐爆 context window）：

| screens 數量 N | 行動 |
|----------------|------|
| N ≤ 15 | 繼續 |
| 15 < N ≤ 40 | `[WARN] 偵測到 {{n}} 個 screens，建議提供 section 的 node-id 縮小範圍。` 使用者確認全抓才繼續 |
| N > 40 | 必須縮小範圍，不得全抓。列出 page/section 清單供使用者挑選 node-id |

為每個 screen 取 slug：kebab-case、< 50 字元、同 change 內唯一；
CJK 名稱另取英文 slug（如 `checkout-cart`），對照關係記入 manifest。

### Step 2 — Per-screen 擷取

對每個 screen node **並行**送出兩個無依賴呼叫（可同一訊息送出）；
**任一失敗均須回報，不得靜默繼續**：

- `mcp__Figma__get_design_context`（fileKey: `{{file_key}}`, nodeId: `{{node_id}}`）
  — layout、樣式、文字內容、變數引用
- `mcp__Figma__get_screenshot`（fileKey: `{{file_key}}`, nodeId: `{{node_id}}`）
  — 截圖存為 `design/assets/{{screen_slug}}.png`

**部分失敗處理**：單一 node 失敗不中斷整批——
該 screen 在 design-context.md 對應章節標 `[BLOCKED: <原因>]`，
manifest 中該 node 記 `"status": "blocked"`，其餘 screens 繼續；
最終摘要必須列出 blocked 清單。

**截圖大小 guard**：單檔 > 2MB 時以較低 scale 重抓一次；仍超過則保留並在摘要標注
（截圖不進 git，僅防單檔過大拖慢下載與補抓）。

Component nodes：只對代表性 states（default 與最重要的 variant）呼叫
`get_design_context`，狀態差異記入 design-context.md 第 4 章。

### Step 3 — Design Tokens

呼叫 `mcp__Figma__get_variable_defs`（fileKey: `{{file_key}}`）取得 variables / design tokens。
If the call fails, stop and report the error to the user.
若回傳為空（file 未使用 variables），design-context.md 的 tokens 章節記：
「此 file 未定義 variables；以下為從 design context 彙整的 inline style 摘要」。

### Step 4 — 產出 design-context.md

依 `design-context-template.md` 的骨架填寫（用 Write tool）：頂部來源與同步資訊區塊，
加上 7 個章節——畫面清單、互動流程、UI 元件與狀態、design tokens、文案表、
edge cases 與設計缺口、給 Step 1a 的四元素提示。

- 頂部必須含固定註記：「截圖不入 git；本機無圖時執行 figma-design-sync（sync 模式）自動補抓」。
- 缺失的狀態稿（error/loading/empty…）統一標 `[DESIGN GAP: 描述]`。
- 由版面順序推斷（而非 prototype 連結）的 flow 標 `inferred`。

### Step 5 — 產出 figma-manifest.json

依 `manifest-schema.md` 寫入（用 Write tool）：file 級欄位（fileKey/version/lastModified）、
每個 node 的指紋欄位（name/type/width/height/childCount/descendantSummary）、
screenshot 路徑、status、skippedNodes、assets 統計。

### Step 6 — 回報

- 擷取結果：N screens（blocked 清單若有）、M components、tokens 有/無、assets 總大小
- `git status` 確認：design-context.md 與 manifest 為新增待 commit；assets/ 不在 untracked 清單
- 下一步提示：「執行 spectra-amplifier 展開 `{{change_name}}`，Step 1a 將自動讀取 design-context.md」

---

## Sync 模式

### Step S1 — 讀 manifest 與 probe

1. Read `design/figma-manifest.json`（解析失敗 → 回模式決策表的壞損列）。
2. 呼叫 `mcp__Figma__whoami` 確認認證（failure gate 同 extract Step 0）。
3. 呼叫 `mcp__Figma__get_metadata`（fileKey 與 rootNodeId 取自 manifest）。
   If the call fails, stop and report the error to the user.

### Step S2 — 變更判定決策表

| 狀況 | 行動 |
|------|------|
| `version` 與 `lastModified` 均與 manifest 相同，且 manifest `nodes[].screenshot` 記錄的檔案在本地全部存在 | `[OK] 設計無變更（version {{version}}），design/ 為最新。` **早退，不做任何寫入** |
| `version` 與 `lastModified` 相同，但 manifest 記錄的截圖有 N 張本地缺失（fresh clone / 換機器） | **assets restore**：只對缺失的 nodes 重抓 `get_screenshot` 補圖；不改 design-context.md 與 manifest 的 version 欄位；回報「補抓 N 張缺圖」而非設計變更 |
| `version` 已變，且 node 指紋比對（規則見 `manifest-schema.md`）出 changed / added nodes | 進 S3，**只重抓 changed + added** 的 nodes |
| `version` 已變，但所有 tracked nodes 指紋相同 | `[WARN] file version 已變但結構指紋無差異——可能是文案或樣式層級變更（metadata 不可見）。` 提供三選項交使用者：(a) 對全部 screens 重抓 get_design_context（不重抓截圖）；(b) full re-extract；(c) 忽略本次變更。**不得自行選擇** |
| manifest 內 node 在新 metadata 樹中消失 | 標記 removed，進 S3（design-context.md 對應章節加 `[REMOVED]` 墓碑與原因；本地截圖檔保留，摘要提示可刪） |

### Step S3 — 增量更新

1. 對 changed / added nodes 重跑 extract Step 2（同樣的並行呼叫、failure gate、大小 guard）。
2. 更新 design-context.md：**第二次修訂起必標 delta markers**——
   `[ADDED]`（新 screen/元件）、`[MODIFIED]`（變更處）、`[REMOVED]`（墓碑），
   與 spectra-amplifier 的 delta marker 慣例一致。
3. 更新 manifest：新的 version / lastModified / extractedAt（mode: `"sync"`）與受影響 nodes 的指紋。

### Step S4 — Diff 摘要與 spec 影響提示

1. 表格輸出：screen slug × 變更類型（added/modified/removed）× 指紋差異欄位
   （例：「size 390x844 → 390x900」「childCount 12 → 14」）。
2. **Spec 影響提示**：以 changed screen 的 slug 與名稱，用 Grep tool 檢索
   `openspec/changes/{{change_name}}/specs/` 下的 `#### Scenario:` heading——
   - 有命中：列出「以下 scenarios 可能受影響，建議以 spectra-amplifier 修訂（記得加 delta markers）」
   - 無命中：註明「未找到直接引用該畫面的 scenario，請人工確認影響範圍」

---

## 與 spectra-amplifier 的關係

- amplifier Step 0 決策表偵測 figma.com URL 或既有 manifest 時會先執行本 skill
  （見 spectra-amplifier SKILL.md Step 0）。
- design-context.md 章節 1/3/6/7（畫面、元件狀態、edge cases、四元素提示）
  是 amplifier Step 1a 四元素萃取的直接輸入；`[DESIGN GAP]` 項目由 amplifier
  轉為 `[NEEDS CLARIFICATION]` 或 Step 0.5 的 W。
- amplifier Step 3 的 design.md 以相對路徑引用 `../design/`，不複製內容
  （single source：`design/` 由本 skill 擁有）。

---

## 反模式

| 反模式 | 為什麼錯 | 正確做法 |
|--------|----------|----------|
| 把截圖當唯一產物 | 截圖不進 git，且無法餵 spec；文字上下文才是主體 | design-context.md 的結構化章節優先，截圖是輔助參照 |
| 手改 design-context.md 後再 sync | sync 增量更新會覆蓋手改內容 | 設計詮釋寫進 spec/proposal；design-context.md 只由本 skill 維護 |
| 無 node-id 硬抓 40+ screens | design context 撐爆 context window，產出品質崩壞 | 依範圍 guard 要求 section node-id 縮小範圍 |
| sync 更新不加 delta markers | 讀者無法分辨哪些設計變了，spec 修訂失去線索 | S3 第二次修訂起必標 `[ADDED]`/`[MODIFIED]`/`[REMOVED]` |
| 把 assets/ 加進 git（改 .gitignore 或 force add） | repo 膨脹，違反本 skill 的儲存契約 | 截圖永遠本地；缺圖靠 assets restore 補抓 |

---

## FAQ

| 問題 | 處理方式 |
|------|----------|
| Figma MCP auth 錯誤 | 在 claude.ai 連接器設定完成 Figma OAuth 後重跑（Step 0 whoami probe 會再驗證） |
| URL 解析不出 node-id | 在 Figma 中選取 frame → 右鍵 Copy link to selection，貼含 `?node-id=` 的完整 URL |
| screens 太多 / context 太肥 | 提供 section 或 page 的 node-id 縮小範圍；或確認只抓 key screens |
| fresh clone 後 design-context.md 的圖全破 | 執行本 skill（sync 模式），assets restore 會補抓全部缺圖 |
| sync 顯示 version 變了但 diff 為空 | 文案/樣式變更 metadata 不可見（已知盲點）；依 S2 三選項選 full re-extract 或全量 design context 重抓 |
| manifest 壞掉 / 想強制全量重抓 | 刪除 `design/figma-manifest.json` 重跑（自動走 extract） |
| 換了新的 Figma file | 貼新 URL，skill 偵測 fileKey 不同會確認後覆蓋重建 |
| change 目錄還不存在 | 先 `/spectra-propose <change-name>` 建立 change；或確認後由本 skill 僅建立 design/ 子目錄 |

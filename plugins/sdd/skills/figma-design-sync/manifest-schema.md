# figma-manifest.json Schema

`figma-manifest.json` 是 sync 模式的比對契約（owner：figma-design-sync skill）。
manifest 進 git；agent 直接讀 JSON 逐欄比對——欄位可讀、diff 可解釋
（「size 390x844 → 390x900」比 hash 不等有用得多），不需要 hash、不需要 Python。

---

## 完整範例

```json
{
  "schemaVersion": 1,
  "figma": {
    "fileKey": "AbCdEf123",
    "fileName": "Checkout Redesign",
    "fileUrl": "https://www.figma.com/design/AbCdEf123/Checkout-Redesign?node-id=1-2",
    "rootNodeId": "1:2",
    "version": "5678901234",
    "lastModified": "2026-07-01T08:30:00Z"
  },
  "extraction": {
    "extractedAt": "2026-07-03T10:00:00Z",
    "mode": "extract",
    "skillVersion": "1.6.0"
  },
  "nodes": [
    {
      "nodeId": "1:23",
      "slug": "checkout-cart",
      "name": "Checkout / Cart",
      "kind": "screen",
      "type": "FRAME",
      "width": 390,
      "height": 844,
      "childCount": 12,
      "descendantSummary": "3 TEXT, 4 INSTANCE, 2 FRAME, 3 RECTANGLE",
      "screenshot": "assets/checkout-cart.png",
      "status": "ok"
    }
  ],
  "skippedNodes": ["1:99 (_annotations)"],
  "assets": { "totalBytes": 4183040, "fileCount": 6 }
}
```

## 欄位說明

| 欄位 | 說明 |
|------|------|
| `schemaVersion` | 本 schema 的版本，目前為 `1`；未來欄位變更時遞增 |
| `figma.fileKey` | URL 中的 file key；模式決策表用它判斷「是否換了 file」 |
| `figma.version` / `figma.lastModified` | file 級版本資訊（來自 `get_metadata`）；sync 第一層比對依據 |
| `figma.rootNodeId` | extract 時的範圍根節點；sync 的 `get_metadata` 沿用同一範圍 |
| `extraction.mode` | `"extract"` 或 `"sync"`（最近一次寫入的模式） |
| `extraction.skillVersion` | 產出時的 sdd plugin 版本（除錯用） |
| `nodes[].kind` | `"screen"` 或 `"component"` |
| `nodes[].width/height/childCount/descendantSummary` | node 級指紋欄位（見下） |
| `nodes[].screenshot` | 截圖相對路徑；**assets restore 的補抓依據**（檔案缺失時只補圖） |
| `nodes[].status` | `"ok"` 或 `"blocked"`（extract 時 MCP 呼叫失敗的 node） |
| `skippedNodes` | 被分類規則略過的 nodes（隱藏層、`_`/`.` 開頭），保留供除錯 |
| `assets` | 截圖總量統計（回報用） |

---

## 兩層比對機制

### 第一層 — file 級（便宜，warm path）

`get_metadata` 一次呼叫取得現況的 `version` 與 `lastModified`，與 manifest 比對：

- **兩者均相同** → 設計無變更。再檢查本地截圖是否齊全：
  - 齊全 → `[OK]` 早退，零寫入
  - 有缺 → assets restore（只補圖，不動 version 欄位）
- **任一不同** → 進第二層

多數 sync 呼叫在第一層結束——這就是「只有必要時才碰 Figma」的成本結構。

### 第二層 — node 級指紋

Figma MCP **不提供 per-node 版本**，指紋由 `get_metadata` 可見欄位構成：

```text
指紋 = name + type + width + height + childCount + descendantSummary
```

`descendantSummary` 是直屬子節點的 type 統計字串（如 `"3 TEXT, 4 INSTANCE, 2 FRAME"`）。

逐 node 比對規則：

| 比對結果 | 分類 |
|----------|------|
| manifest 有、新樹有、指紋相同 | unchanged（不重抓） |
| manifest 有、新樹有、任一指紋欄位不同 | **changed**（重抓 design context + 截圖） |
| manifest 無、新樹有（且通過 screen 分類規則） | **added**（新增擷取） |
| manifest 有、新樹無 | **removed**（design-context.md 標 `[REMOVED]` 墓碑） |

### 已知盲點（誠實記載）

**純文案、顏色、內層樣式變更不改變 metadata 指紋。**
此時 file `version` 已變但所有指紋相同——skill 必須輸出 `[WARN]` 並提供三選項
（全量 design context 重抓 / full re-extract / 忽略）交使用者決定，不得自行選擇。
這是 per-node 版本缺席下的務實折衷；本文件明文記載，不假裝能偵測。

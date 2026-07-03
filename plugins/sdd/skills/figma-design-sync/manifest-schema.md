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
| `figma.version` / `figma.lastModified` | file 級版本資訊（best-effort：擷取時若恰可取得則記錄，僅供人類參考）；**非** sync 比對依據——`get_metadata` 不回傳此欄位，sync 一律以 node 結構指紋比對 |
| `figma.rootNodeId` | extract 時的範圍根節點；sync 的 `get_metadata` 沿用同一範圍 |
| `extraction.mode` | `"extract"` 或 `"sync"`（最近一次寫入的模式） |
| `extraction.skillVersion` | 產出時的 sdd plugin 版本（除錯用） |
| `nodes[].kind` | `"screen"`、`"component"` 或 `"instance"` |
| `nodes[].width/height/childCount/descendantSummary` | node 級指紋欄位（見下） |
| `nodes[].screenshot` | 截圖相對路徑；**assets restore 的補抓依據**（檔案缺失時只補圖） |
| `nodes[].status` | `"ok"` 或 `"blocked"`（extract 時 MCP 呼叫失敗的 node） |
| `nodes[].componentRef` | 僅 instance 節點：`{ "mainComponent": "<名稱>", "external": true/false }`，記錄該 instance 引用的 main component 與是否來自外部 library；供 Step 6 元件完整性 gate 比對「被引用但定義未盤點」 |
| `skippedNodes` | 被分類規則略過的 nodes（隱藏層、`_`/`.` 開頭），保留供除錯 |
| `assets` | 截圖總量統計（回報用） |

---

## 比對機制（結構指紋）

`get_metadata` 只回傳 node 樹（node IDs / type / name / position / size），**不回傳 file 級
`version` / `lastModified`**（其 schema 說明：「only includes node IDs, layer types, names,
positions and sizes」）。因此 sync 以 **node 結構指紋**為唯一比對依據，不依賴 file 版本。

一次 `get_metadata` 呼叫即取得整棵樹；對每個 tracked node 重算指紋並與 manifest 逐 node 比對——
昂貴的 `get_design_context` / `get_screenshot` 只對 changed / added node 觸發，
「只有必要時才碰 Figma」的成本結構由此維持（cheap metadata 一呼 + 選擇性昂貴重抓）。

指紋由 `get_metadata` 可見欄位構成：

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
| manifest 有、新樹無（且通過完整性前置檢查，見 SKILL.md Step S2） | **removed**（design-context.md 標 `[REMOVED]` 墓碑） |

所有 `status="ok"` tracked node 指紋均相同 → 設計結構無變更 → 再檢查截圖：齊全則 `[OK]` 零寫入早退；
有缺則只對 `status="ok"` 的缺圖 node 做 assets restore（跳過 `status="blocked"` node）。

### 已知盲點（誠實記載）

**純文案、顏色、內層樣式、design token 變更不改變結構指紋**，且 `get_metadata` 無 file 版本
可資偵測——因此此類非結構變更 sync **無法偵測、會結構性早退略過**。design token
（`get_variable_defs` 產出）也不入指紋，同屬此盲點。使用者若已知有非結構變更，
須明確要求 **full re-extract** 重建。這是 Figma MCP 不提供 file 版本 / per-node 版本下的
務實折衷；本文件明文記載，不假裝能偵測。

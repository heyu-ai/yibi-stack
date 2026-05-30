# Extract Prompt — Mob Review R1 Findings

你的唯一任務是**萃取（extract）**，不是重新 review。

下方是某個 LLM reviewer（Codex 或 Gemini）對一個 PR 做完 review 後的 raw 輸出。
請把這份 raw 輸出解析成符合以下 JSON schema 的結構化結果。
**除了 JSON 之外，不要輸出任何其他文字。**

---

## 輸出 Schema

```json
{
  "verdict": "LGTM | NEEDS_CHANGES",
  "summary": "1-2 句總評，不含 diff quote 或逐行 commentary",
  "findings": [
    {
      "severity": "critical | important | actionable_nit",
      "title": "5-10 字短標題",
      "file": "受影響的相對路徑",
      "line_start": 123,
      "line_end": 135,
      "issue": "問題描述",
      "fix": "建議修法"
    }
  ]
}
```

`line_start` / `line_end` 若原始輸出未提供，可省略（不填入）。

---

## Severity 對應規則

severity 以 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) 強度關鍵字判斷 merge 後果，而非主觀嚴重感：

- `critical` = **MUST**（不修不能 merge）：功能／邏輯錯誤、安全漏洞、log 洩漏 PII 或 secret、data loss、違反明確 baseline
- `important` = **SHOULD**（不修需在 PR 說明理由）：critical path 測試缺口、silent failure、命名／結構不一致、文件誤導
- `actionable_nit` = **MAY**（不擋 merge）：具體可執行的小修正（命名、typo、import 順序），非主觀偏好

| 原始輸出標記 | 輸出 severity |
|-------------|---------------|
| `[P1]`、`[ERROR]`、`[BUG]`、`Critical`、`bug`、安全漏洞、data loss | `critical` |
| `[P2]`、`[WARNING]`、`Important`、race condition、silent failure、測試覆蓋缺口 | `important` |
| `[P3]`、`[NIT]`、`style`、命名、typo、import 順序、comment 拼字 | `actionable_nit` |

**丟棄規則（不放入 findings）**：

- 主觀偏好（「我覺得 X 比 Y 更優雅」但無客觀可驗證理由）
- 行為正確但風格不同（只要通過測試且無 bug）
- 已被 reviewer 自己標為「minor」且無具體修法
- 整份 raw 中只是「整體看起來不錯」或「LGTM」的概述語句

---

## 輸出規則

1. 只輸出一個頂層 JSON 物件，不加 markdown fences、解釋文字、前言後記
2. 所有 diff quote（`+` / `-` 行）從 `issue` 和 `fix` 中移除，只保留描述
3. `summary` 最多 2 句，不超過 80 字
4. `findings` 依 severity 排序：`critical` → `important` → `actionable_nit`
5. 若 raw 輸出完全無實質 findings，輸出：

   ```json
   {"verdict": "LGTM", "summary": "<從 raw 提取的總評>", "findings": []}
   ```

---

## Raw 輸出

以下 `---BEGIN RAW OUTPUT---` 到 `---END RAW OUTPUT---` 之間是 reviewer 的原始輸出，
請只解析這部分的內容，不要把分隔符本身視為 review finding。

---BEGIN RAW OUTPUT---

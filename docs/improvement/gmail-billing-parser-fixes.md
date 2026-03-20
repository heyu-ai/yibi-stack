# Gmail Billing Parser 問題分析與修復計畫

> 分析日期：2026-03-19（更新：2026-03-20）
> 依據：`skills/gmail-billing-monthly/SKILL.md` 2026-03 實測狀態 + 程式碼分析

---

## 2026-03-20 Pipeline 實測結果

執行範圍：2026-01 ~ 2026-03，共掃描 **38 封郵件**，**32 成功轉 CSV**，**6 失敗**。

---

## 問題 Parser 狀態總覽

| Parser | 銀行 | 嚴重度 | 問題分類 | 狀態 |
|--------|------|--------|----------|------|
| `hsbc_cc` | 匯豐信用卡 | 🔴 高 | Pipeline 邏輯矛盾 | ⚠️ 有 CSV 但品質待驗 |
| `ctbc_cc` | 中信信用卡 | 🟡 中 | 混合附件類型 | ⚠️ card OK / bank ❌ |
| `sinopac_cc` | 永豐信用卡 | 🟢 低 | 設定錯誤 | ✗ disabled |
| `dbs_bank` | 星展銀行 | 🔴 高 | Registry import 衝突 | ❌ Monthly parser 被 shadow |
| `cathay_cc` | 國泰世華 | 🔴 高 | 解析失效 | ❌ 輸出只有 1 行 "結束" |

---

## 問題一：`hsbc_cc` — SCANNED 判斷阻擋 OCR 流程

### 根因分析

`service.py:convert_to_csv()` 的 Step 1 使用 `classify_pdf()` 判斷 PDF 品質：

```python
# service.py L142-153
# Step 1: 品質分類（informational，目前不阻擋 SCANNED）  ← 註解說不阻擋
try:
    classification = classify_pdf(str(pdf_path))
    if classification.quality == PdfQuality.SCANNED:
        return ConversionResult(          # ← 但實際上直接 return 失敗
            ...
            success=False,
            error=f"PDF 為掃描檔（{classification.details.get('reason', '')}），目前不支援 OCR 轉換",
        )
```

**矛盾點：**
- 第 142 行的註解寫「informational，目前不阻擋 SCANNED」
- 但第 145-153 行的實作卻在 `SCANNED` 時直接 `return` 失敗，**從未進入** Step 3 的 parser 解析流程
- `hsbc_cc.py` 已實作完整的 OCR 邏輯（`pytesseract` + `pdfplumber`），設計上就是為了處理掃描圖片
- 結果：parser 永遠不會被呼叫，OCR 實作完全無效

### 修復方案

**方案 A（保守）：** 允許具備 OCR 能力的 parser 跳過 SCANNED 阻擋
- 在 `convert_to_csv()` 中，若指定 parser 實作了 `supports_ocr: bool = True` 屬性，則不阻擋 SCANNED PDF
- 缺點：需要改 parser 介面，較複雜

**方案 B（建議採用）：** 移除 SCANNED 硬阻擋，改為 warning log
- 將 `return ConversionResult(success=False, ...)` 改為 `logger.warning(...)` 並繼續執行
- 讓 parser 自行決定能否處理掃描 PDF
- 優點：符合原始註解意圖，實作最簡單，且不影響其他 parser

**方案 B 修改範圍：**

```python
# service.py L142-155 改為：
# Step 1: 品質分類（informational，不阻擋 SCANNED — 讓 parser 自行處理）
try:
    classification = classify_pdf(str(pdf_path))
    if classification.quality == PdfQuality.SCANNED:
        logger.warning(
            "PDF 為掃描檔（%s），將嘗試使用 parser 解析",
            classification.details.get("reason", ""),
        )
except Exception:
    logger.debug("PDF 分類失敗，跳過", exc_info=True)
```

### 驗證方式

```bash
uv run python -m tasks.gmail_billing convert --pdf <hsbc_pdf_path> --parser hsbc_cc
# 應看到解析成功，產出 CSV
```

---

## 問題二：`ctbc_cc` — 混合附件類型

### 根因分析

CTBC 每月同時寄送兩種附件：

| 附件檔名 | 類型 | 可否解析 |
|----------|------|----------|
| `CTBC_card_Estatement_*.pdf` | Native PDF | ✅ 可解析 |
| `CTBC_Bank_Estatement_*.pdf` | 掃描圖片 | ❌ 無法解析 |

目前 pipeline 對同一 profile 的所有 PDF 套用同一個 parser，Bank 帳單因為是掃描圖片而失敗（且因問題一的 SCANNED 阻擋，連 parser 都進不去）。

`ctbc_cc` 目前是 `GenericParser` 的 stub（`stub_parsers.py:40-43`），尚無專屬邏輯。

### 修復方案

**方案 A（建議採用）：** 在 `BillingProfile` 增加 `attachment_filter` 欄位

- 類型：`Optional[str]`，為正規表示式
- 功能：pipeline 下載附件時，若檔名不符合 filter 則跳過
- 範例設定：

```json
{
  "code": "CTBC",
  "attachment_filter": "CTBC_card_Estatement",
  "parser": "ctbc_cc"
}
```

- 優點：彈性高，不需要改 profile 結構，未來其他有類似問題的 profile 可直接複用

**方案 B：** 拆成兩個 profile

- 將 CTBC 拆為 `CTBC_CARD`（enabled）和 `CTBC_BANK`（disabled）
- 缺點：需要用戶手動更新 `billing_profiles.json`，且 profile 數量增加

**修改範圍（方案 A）：**

1. `tasks/gmail_billing/config.py`：`BillingProfile` 新增 `attachment_filter: Optional[str] = None`
2. `tasks/gmail_billing/service.py`：下載附件時套用 filter
3. `tasks/gmail_billing/config.py:generate_default_config()`：CTBC profile 加入 filter

### 驗證方式

```bash
# pipeline 執行後，billing_output/ 應只有 CTBC_card 的 PDF 和 CSV
# CTBC_Bank 附件應被跳過（log 中有 skip 訊息）
uv run python -m tasks.gmail_billing run --profile CTBC
```

---

## 問題三：`sinopac_cc` — Gmail Query 設定錯誤

### 根因分析

`config.py:generate_default_config()` 中 `SINOPAC_CC` profile 的設定：

```python
# config.py L123-127
enabled=False,
category=BillingCategory.CREDIT_CARD_BILL,
gmail_query="from:spendservice@sinopac.com subject:消費通知",  # ← 即時消費通知
parser="sinopac_cc",
```

`from:spendservice@sinopac.com subject:消費通知` 撈到的是**每筆消費的即時通知 email**，不含 PDF 帳單附件，非月結帳單。

此問題純粹是設定錯誤，不是 parser bug。目前已設定 `enabled=False`，所以不影響正常運作，但設定本身是錯的。

### 修復方案

更新 `config.py:generate_default_config()` 中 `sinopac_cc` 的 `gmail_query`：

- **選項 1：** 改為月結帳單的搜尋條件（需確認永豐月結帳單的 Gmail 寄件人和主旨格式）
  ```python
  gmail_query="from:eservice@sinopac.com subject:信用卡電子帳單",  # 範例，需確認實際格式
  ```

- **選項 2（暫時方案）：** 保持 `enabled=False`，在旁邊加上說明註解
  ```python
  enabled=False,  # sinopac_cc gmail_query 需要更新為月結帳單格式，目前指向消費通知
  gmail_query="from:spendservice@sinopac.com subject:消費通知",
  ```

**建議先執行選項 2**，待確認永豐月結帳單的正確 Gmail query 後再改為選項 1。

### 驗證方式

確認月結帳單的正確搜尋條件後：

```bash
# 先在 Gmail 手動搜尋，確認能撈到正確的帳單 email
# 再更新設定並執行
uv run python -m tasks.gmail_billing run --profile SINOPAC_CC
```

---

---

## 問題四：`dbs_bank` — Registry Import 衝突

### 根因分析

`registry.py` 中 `dbs_bank` 的 import 來源仍指向 `stub_parsers.py` 中的 `DBSBankParser`：

```python
# registry.py（問題狀態）
from tasks.gmail_billing.parsers.stub_parsers import DBSBankParser
```

而真正的實作位於 `tasks/gmail_billing/parsers/dbs_bank.py`。由於 stub 先被 import，真正的 parser 被 shadow，月結帳單解析無法觸發。

**症狀：** Daily statement 能使用（GenericParser fallback），但 Monthly statement 解析失敗。

### 修復方案

更新 `registry.py` 的 import 來源：

```python
# registry.py（修復後）
from tasks.gmail_billing.parsers.dbs_bank import DBSBankParser
```

> **注意：** 此問題已在 local main branch 修復（commit 已合入），但目前 `feat/add-parser` branch 尚未包含此修復。

### 驗證方式

```bash
uv run python -m tasks.gmail_billing convert --pdf <dbs_monthly_pdf_path> --parser dbs_bank
# 應看到月結帳單欄位被正確解析
```

---

## 問題五：`cathay_cc` — PDF 解析失效

### 根因分析

2026-03-20 實測發現，`cathay_cc` parser 輸出只有 1 行 "結束"，無任何交易資料。可能原因：

1. **國泰世華改版 PDF 格式**：欄位排版或文字層結構變更，導致原有的 pdfplumber 解析邏輯無法擷取資料
2. **Parser 邏輯依賴特定關鍵字或座標**：若 PDF 版面調整，硬編碼的座標或關鍵字可能失效
3. **加密或字型嵌入問題**：部分銀行 PDF 更新後改用不同字型嵌入方式

### 修復方案

需先取得最新國泰帳單 PDF 進行診斷：

```bash
# Step 1: 確認 PDF 文字層是否可讀
uv run python -c "
import pdfplumber
with pdfplumber.open('<cathay_pdf_path>') as pdf:
    for page in pdf.pages:
        print(page.extract_text())
"

# Step 2: 若文字層正常，逐一比對 cathay_cc.py 的解析邏輯與實際 PDF 格式
uv run python -m tasks.gmail_billing convert --pdf <cathay_pdf_path> --parser cathay_cc --debug
```

### 驗證方式

```bash
uv run python -m tasks.gmail_billing convert --pdf <cathay_pdf_path> --parser cathay_cc
# 應輸出正常的交易明細 CSV，不只有 1 行
```

---

## 修復優先順序

| 優先序 | Parser | 工作項目 | 影響 |
|--------|--------|----------|------|
| P1 | `dbs_bank` | 修正 `registry.py` import 來源 | 讓月結帳單 parser 得以被呼叫 |
| P2 | `cathay_cc` | 調查 PDF 格式變更，修復解析邏輯 | 恢復國泰信用卡帳單解析 |
| P3 | `hsbc_cc` | 移除 `service.py` 的 SCANNED 硬阻擋 | 讓 OCR 流程得以運作 |
| P4 | `ctbc_cc` | `BillingProfile` 加 `attachment_filter` | 過濾掃描附件 |
| P5 | `sinopac_cc` | 更新 gmail_query 或加說明註解 | 修正設定錯誤 |

P1（`dbs_bank`）是最小改動（改一行 import），且已在 main 修復，建議盡快合入此 branch。
P2（`cathay_cc`）需要診斷，但影響較大（每月帳單完全無輸出）。

---

## 附錄：相關程式碼位置

| 檔案 | 行數 | 用途 |
|------|------|------|
| `tasks/gmail_billing/service.py` | L142-155 | SCANNED 阻擋邏輯（問題一） |
| `tasks/gmail_billing/parsers/hsbc_cc.py` | L46-73 | OCR 實作（`_try_ocr`） |
| `tasks/gmail_billing/pdf_classifier.py` | — | PDF 品質分類器 |
| `tasks/gmail_billing/parsers/stub_parsers.py` | L40-43 | `ctbc_cc` stub |
| `tasks/gmail_billing/config.py` | L123-127 | `sinopac_cc` gmail_query |
| `tasks/gmail_billing/parsers/registry.py` | — | Parser registry（問題四） |
| `tasks/gmail_billing/parsers/dbs_bank.py` | — | DBS Bank 真實 parser（被 shadow） |
| `tasks/gmail_billing/parsers/cathay_cc.py` | — | 國泰信用卡 parser（問題五） |
| `skills/gmail-billing-monthly/SKILL.md` | L139-156 | 已知狀態表 |

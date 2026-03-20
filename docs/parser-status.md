# Gmail Billing Parser 狀態追蹤

> 最後更新：2026-03-20
> 基於 2026-01 ~ 2026-03 pipeline 實測（38 封郵件、32 成功、6 失敗）

---

## Global CSV Schema 規範

所有 parser 輸出的 CSV 應遵循以下 10 欄 schema：

```
bank, type, card, date, description, amount, currency, balance, category, memo
```

### 欄位說明

| 欄位 | 說明 | 範例 |
|------|------|------|
| `bank` | 銀行/機構名稱 | 國泰世華、星展銀行、匯豐 |
| `type` | 資產負債分類 | `Asset`（銀行存款）/ `Loan`（信用卡） |
| `card` | 卡號後四碼（區分同銀行不同卡），透過 config `card_mapping` 對應卡別名稱；銀行帳戶填帳號末四碼 | 1234、5678 |
| `date` | 交易日期 YYYY-MM-DD | 2026-01-15 |
| `description` | 交易說明 | MOMO 購物 |
| `amount` | 金額（正數） | 1500.00 |
| `currency` | 幣別 | TWD、USD |
| `balance` | 餘額（僅銀行明細，信用卡帳單留空） | 50000.00 |
| `category` | 交易分類 | 餐飲、購物 |
| `memo` | 備註 | 分期 3/12 |

### 與現有 `ParsedRow` 的差異

目前 `ParsedRow` 只有 7 欄（`date, description, amount, currency, balance, category, memo`），缺少來源識別與資產負債分類。

**新增的三欄：**
- `bank`：讓多個 parser 的輸出合併後仍可區分來源
- `type`：讓下游工具能直接分類資產（Asset）vs 負債（Loan）
- `card`：區分同一銀行帳戶下的不同卡片或帳號

> `ParsedRow` 已升級為 10 欄，`to_csv()` 輸出遵循此 schema。`bank`/`type` 由 service layer enrichment 填入，`card` 由 parser 填入原始值後由 service 做 mapping。

---

## Card Mapping 設計

在 `billing_profiles.json` 的 profile 層級新增 `card_mapping` 欄位，將卡號末四碼對應到人類可讀的卡別名稱。

### 設定格式

```json
{
  "code": "HSBC_CC",
  "parser": "hsbc_cc",
  "card_mapping": {
    "1234": "匯豐 Live+",
    "5678": "匯豐現金回饋"
  }
}
```

```json
{
  "code": "CTBC",
  "parser": "ctbc_cc",
  "card_mapping": {
    "9012": "中信華航聯名卡",
    "3456": "中信 LINE Pay"
  }
}
```

### 運作邏輯

1. Parser 從 PDF 擷取卡號末四碼
2. 查 `card_mapping` → 若有對應則填入卡別名稱；若無則填入原始末四碼
3. `card_mapping` 為 optional，未設定時 `card` 欄填 parser 能擷取的原始值

---

## 各 Parser 狀態表

基於 2026-03-20 實測結果：

| Parser | 銀行 | 類型 | 有效? | 2026-03 狀態 | 備註 |
|--------|------|------|-------|-------------|------|
| `sinopac_bank` | 永豐銀行 | bank_statement | ⚠️ Stub | ✅ GenericParser 可用 | 需實作真正 parser |
| `dbs_bank` | 星展銀行 | bank_statement | ✅ | ❌ Daily ✅ / Monthly ❌ | registry.py shadow 已修復，真 parser 已正確載入 |
| `hncb_bank` | 華南銀行 | bank_statement | ⚠️ Stub | ✅ GenericParser 可用 | 需實作真正 parser |
| `fubon_bank` | 台北富邦 | bank_statement | ⚠️ Stub | ✅ GenericParser 可用 | 需實作真正 parser |
| `hsbc_bank` | 匯豐帳戶 | bank_statement | ⚠️ Stub | ✅ GenericParser 可用 | 需實作真正 parser |
| `cathay_cc` | 國泰世華 | credit_card_bill | ❌ 失效 | ❌ 輸出只有 1 行 | 需調查 PDF 格式是否有變 |
| `hsbc_cc` | 匯豐信用卡 | credit_card_bill | ⚠️ 阻擋 | ✅ 有產 CSV 但品質待驗 | SCANNED 阻擋已移除，OCR 邏輯待驗證 |
| `ctbc_cc` | 中國信託 | credit_card_bill | ⚠️ Stub | ⚠️ card OK / bank ❌ | 需 `attachment_filter` 過濾掃描附件 |
| `hncb_cc` | 華南信用卡 | credit_card_bill | ⚠️ Stub | ✅ GenericParser 可用 | 需實作真正 parser |
| `sinopac_cc` | 永豐信用卡 | credit_card_bill | ❌ Disabled | — | `gmail_query` 指向消費通知而非月結帳單 |

### 圖示說明

| 圖示 | 意義 |
|------|------|
| ✅ | 正常運作 |
| ⚠️ | 部分功能/有警告 |
| ❌ | 失敗/停用 |

---

## Stub Parser 實作優先順序

目前所有 bank_statement parser 及部分 credit_card parser 使用 `GenericParser` stub。
建議依照以下優先序逐步實作真正的 parser：

| 優先序 | Parser | 說明 |
|--------|--------|------|
| P1 | `dbs_bank` | ✅ registry.py shadow 已修復 |
| P2 | `cathay_cc` | 調查並修復 PDF 格式解析失效 |
| P3 | `hsbc_cc` | 驗證 OCR 解析品質 |
| P4 | `ctbc_cc` | 加入 `attachment_filter` |
| P5 | `sinopac_cc` | 修正 gmail_query 為月結帳單格式 |
| P6 | `sinopac_bank` | 實作永豐銀行明細 parser |
| P7 | `hncb_bank` / `hncb_cc` | 實作華南銀行/信用卡 parser |
| P8 | `fubon_bank` | 實作台北富邦明細 parser |
| P9 | `hsbc_bank` | 實作匯豐帳戶明細 parser |

---

## 新增 Parser 流程

新增一個 parser 的標準步驟：

1. **建立 parser 實作**
   ```
   tasks/gmail_billing/parsers/<bank_name>.py
   ```
   繼承 `BaseParser`，實作 `parse()` 方法，輸出遵循 Global CSV Schema。

2. **更新 registry**
   在 `tasks/gmail_billing/parsers/registry.py` 加入新 parser 的 import 與對應。

3. **更新 config**
   在 `tasks/gmail_billing/config.py:generate_default_config()` 確認 profile 設定正確：
   - `gmail_query`：能撈到月結帳單（非即時通知）
   - `parser`：對應 registry 的 key
   - `attachment_filter`（若需要）：過濾附件類型

4. **撰寫測試**
   在 `tasks/gmail_billing/tests/` 加入對應的 parser 單元測試。

5. **更新文件**
   - 更新本文件（`docs/parser-status.md`）的狀態表
   - 更新 `skills/gmail-billing-monthly/SKILL.md` 的已知狀態表

### 參考資料

- Parser 介面：`tasks/gmail_billing/parsers/base.py`
- Stub 範例：`tasks/gmail_billing/parsers/stub_parsers.py`
- 完整實作範例：`tasks/gmail_billing/parsers/dbs_bank.py`
- Pipeline 服務：`tasks/gmail_billing/service.py`

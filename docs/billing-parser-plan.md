# Billing Parser 實作計畫

## 背景

billing-import 流程中，以下銀行的信用卡資料無法正確解析：

| 銀行 | 問題 | 本次處理 |
|------|------|---------|
| 中國信託 | parser stub（GenericParser 無法解析） | ✅ 已實作 |
| 華南銀行 | parser stub（只抓到「結束」） | ✅ 已實作 |
| 永豐銀行 | profile `enabled=False`，query 指向即時消費通知（無月結 PDF） | ❌ 待處理 |
| 富邦銀行 | 無信用卡 profile | ❌ 待處理 |

---

## 已完成：中國信託信用卡 (CTBC CC)

### PDF 格式

- **Page 1**：帳戶摘要（跳過）
- **Page 2+**：交易明細
- **日期**：民國年 `YYY/MM/DD`（`115/02/08` = 2026/02/08，+1911）
- **多卡混排**：以末四碼區分（7926, 5457, 5789, 9995...）

### 三種交易行格式

```text
# 國內（無描述）
YYY/MM/DD YYY/MM/DD  {amount}  {card4}  TW

# 海外（含描述 + 外幣）
YYY/MM/DD YYY/MM/DD  {description}  {TWD}  {card4}  {CC}  {MM/DD}  {CCY}  {forex}

# 手續費（海外後接，無描述）
YYY/MM/DD YYY/MM/DD  {fee}  {card4}
```

### 停止條件

遇到以下關鍵字停止處理當前頁（廣告/利率資訊區塊開始）：
`eToro`, `TWQR`, `ApplePay`, `GooglePay`, `ARMs`, `X1003090`

### 實作檔案

`tasks/gmail_billing/parsers/ctbc_cc.py`

---

## 已完成：華南銀行信用卡 (HNCB CC)

### PDF 格式

- **Page 1**：摘要 + 完整交易明細（同一頁）
- **Page 2**：純通知文字（跳過）
- **日期**：民國年 `YYY/MM/DD`
- **卡別分區**：`卡名：XXXX****XXXX` 標題 + 長虛線分隔

### 交易行格式

```text
YYY/MM/DD YYY/MM/DD  {description}  {amount}  {country_code}
# 海外可選欄位：
YYY/MM/DD YYY/MM/DD  {description}  {amount}  {CC}  {YYY/MM/DD}  {CCY}  {forex}
```

### 跳過規則

| 模式 | 說明 |
|------|------|
| `^-{10,}` | 卡別分隔虛線 |
| `上期應繳`, `上期溢繳` | 期初餘額 |
| `＊＊＊消費小計＊＊＊` | 卡別小計 |
| `本期應繳` | 期末總額 |
| `結\s*束` | 帳單終止標記 |
| `^交易日\s+入帳日` | 欄位標題行 |
| `^[◆※【]` | 通知聲明行 |
| 負數金額 | 退款/溢繳 |

### 紅利點數

從 `account_info` 欄位回傳，格式：
`紅利點數：+12點，本期結餘 392點，144點到期(2026-12-31)`

### 實作檔案

`tasks/gmail_billing/parsers/hncb_cc.py`

---

## 已完成：永豐銀行信用卡 (SINOPAC CC)

### PDF 格式

- **Page 1**：帳戶摘要（取帳單年月）
- **Page 2**：交易明細（PDF 表格，欄位以 x 座標區分）
- **Page 3+**：通知/聲明（跳過）
- **日期格式**：MM/DD（無年份，年份從 Page 1 標題取得）
- **單一卡號**：卡末四碼在每行重複出現

### 解法

- 原 gmail_query 指向即時消費通知（`spendservice@sinopac.com`），改為月結帳單寄件者
- 寄件者：`ebillservice@newebill.banksinopac.com.tw`（與銀行對帳單相同）
- 主旨關鍵字：`電子帳單通知`

### 實作檔案

`tasks/gmail_billing/parsers/sinopac_cc.py`

---

## 無法自動化：富邦銀行信用卡

- 現況：只有 `FUBON` bank_statement profile
- 問題：帳單郵件只有網頁連結，需要登入 + 身分驗證才能下載 PDF，無法自動化
- 結論：需人工下載後手動匯入

---

## 相關變更

| 檔案 | 變更 |
|------|------|
| `tasks/gmail_billing/parsers/ctbc_cc.py` | 新建 CTBC parser |
| `tasks/gmail_billing/parsers/hncb_cc.py` | 新建 HNCB parser |
| `tasks/gmail_billing/parsers/sinopac_cc.py` | 新建 SINOPAC CC parser |
| `tasks/gmail_billing/parsers/stub_parsers.py` | 移除 CTBC/HNCB/SINOPAC_CC stubs |
| `tasks/gmail_billing/parsers/registry.py` | 更新 import |
| `.runtime/billing_profiles.json` | 啟用 SINOPAC_CC，修正 gmail_query |
| `tasks/gmail_billing/service.py` | suffix CSV 分類繼承 + row-level 去重 |

---

## 驗證指令

```bash
# 單元測試
uv run pytest tasks/gmail_billing/tests/ -q

# 手動測試 CTBC
uv run python -m tasks.gmail_billing convert \
  --pdf output/billing/raw/pdf/CTBC_card_Estatement_11503.decrypted.pdf \
  --parser ctbc_cc

# 手動測試 HNCB
uv run python -m tasks.gmail_billing convert \
  --pdf output/billing/raw/pdf/CREDITA2026040200103676370.decrypted.pdf \
  --parser hncb_cc

# 手動測試 SINOPAC CC
uv run python -m tasks.gmail_billing convert \
  --pdf billing_output/raw/pdf/永豐銀行信用卡帳單.decrypted.pdf \
  --parser sinopac_cc

# 完整 pipeline
uv run python -m tasks.gmail_billing run --days 120
```

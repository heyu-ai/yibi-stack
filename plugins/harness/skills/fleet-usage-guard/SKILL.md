---
name: fleet-usage-guard
type: exec
scope: global
description: >-
  監控 Claude Code fleet 的額度與近期燒錢速率；從本機 transcript 估算 USD/hour，超過使用者設定閾值或額度接近上限時廣播停手。觸發關鍵字：監控所有 session、fleet usage、daily limit、usage guard、燒錢速率、burn rate、extra usage。
---

# Fleet Usage Guard

同時守兩條彼此獨立的軸：**規則 0：近期 API list-price 估值速率**，以及
**規則 1：five-hour / seven-day 額度百分比**。規則 0 必須先跑；extra usage 開啟後，額度百分比不會可靠地反映付費溢出。

## 前置設定

使用者必須自行在 `~/.claude/fleet-usage-guard.json` 設定當次可接受的視窗與閾值。結構如下；角括號代表使用者選擇的正數，不是預設值：

```json
{
  "window_minutes": <positive integer>,
  "max_usd_per_hour": <user-selected USD/hour>
}
```

**不得替使用者猜閾值，也不得把閾值寫死在 skill。** 設定缺失或無效時，規則 0 會 fail loud；回報錯誤後停止，不能把「量不到」說成安全。

排程或 unattended 執行時同樣不得建立／修改設定檔、不得詢問互動式問題。只讀 transcript、回報結果；只有已證明超標時才做本 skill 的核心副作用：停手廣播。

## 規則 0：先檢查燒錢速率

從載入 skill 時顯示的 base directory 取得 `{{skill_root}}`，執行：

```bash
python3 "{{skill_root}}/scripts/fleet_usage_guard.py"
```

源碼 repo 經 `make install` 安裝時，也可直接執行：

```bash
python3 ~/.claude/skills/fleet-usage-guard/scripts/fleet_usage_guard.py
```

工具會掃 `~/.claude/projects/**/*.jsonl`，只取 assistant usage entry，依
`(message.id, requestId)` 去重，再以設定的最近 N 分鐘視窗外推 USD/hour。估值包含 input、output、cache read、5-minute cache write、1-hour cache write；Claude Fable 5.1 cache read 使用 0.025 倍 input 單價，其餘支援 model 使用 0.1 倍。

### Exit code 分支

| Exit | Outcome | 必須動作 |
|------|---------|----------|
| `0` | `below_threshold` | 記錄估值，繼續規則 1 |
| `2` | `config_error` | 原樣回報設定錯誤並停止；不得執行規則 1 後宣稱整體安全 |
| `3` | `measurement_incomplete` | 原樣回報未定價 model、近期無效 row 或讀取錯誤並停止；不得廣播虛構金額 |
| `10` | `burn_rate_exceeded` | 立即走下方停手廣播，然後本 session 也停止；不得再跑規則 1 |

未知參數由 argparse 以 exit 2 拒絕。

### 速率停手廣播

Exit 10 的 JSON 一定包含 `reason: "burn_rate"` 與 `broadcast_message`。把該字串**原樣**送給所有非 offline peer：

```text
hub(op="send", to="all", message=<broadcast_message>)
```

使用 `to="all"`，不要只通知目前看得到的第一個 peer。送出後，本 session 立即停止工作。訊息必須保留 `$X/hr`、使用者閾值，以及「這是燒錢速率觸發，不是額度快用完」；這三項讓使用者能判斷工作是否值得繼續。

## 規則 1：額度百分比

只有規則 0 exit 0 才執行。從當前 runtime 的 account-usage status 讀取 `five_hour` 與 `seven_day`；不得從 transcript 金額反推額度百分比。

「接近／已到額度」的判準維持：任一 window 的 `severity == "critical"`，或 `percent >= 90`。觸發時走與規則 0 相同的 `hub(..., to="all", ...)` 廣播路徑，但訊息必須是：

```text
立即停手：帳號額度已接近／打到限制（<window>: <percent>%）。這是額度觸發；等待 reset 前不要繼續。
```

若 runtime 沒有提供 account-usage status，明確回報 `[WARN] 額度狀態不可用`；不得把缺資料視為 0%。規則 0 的結果仍然有效。

## 不變量

- 規則 0 永遠先於規則 1；一次檢查最多廣播一次。
- 速率超標後，不因額度百分比低而降級或取消廣播。
- 同一 API request 的 thinking / text / tool_use JSONL rows 只計一次。
- 金額是 Anthropic API list-price **估值**，不是 Claude Code extra-usage 帳單金額。
- 未定價 model 或近期資料結構異常時 fail loud，不能用部分金額宣稱低於閾值；但已知部分金額本身已超標時仍可安全觸發。

## 驗證

```bash
uv run pytest scripts/tests/test_fleet_usage_guard.py
```

測試的 06:00 UTC aggregate replay 鎖定 issue #421 已知的 `$216.78/hr`，04:00 UTC replay 鎖定 `$0.54/hr`。高用量 fixture 含 10 個重複 request row；移除 `(message.id, requestId)` 去重會把結果提高到 `$231.78` 並讓測試失敗。

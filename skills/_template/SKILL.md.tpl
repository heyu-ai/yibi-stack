---
name: <skill-name>
type: exec
scope: global  # global | project（必填）
# disallowed-tools: [Edit, Write]  # 選填；skill 執行期間硬性禁用列出的工具（值可為 YAML list 或空格/逗號分隔字串），見 rule 11
description: <一句話描述這個 skill 做什麼>
---

# <Skill 標題>

## 概要

簡短說明此 skill 的用途、使用情境，以及主要工具或依賴。

## 執行步驟

### Step 1: 環境檢查

確認工作目錄與必要工具：

```bash
cd "$(git rev-parse --show-toplevel)"
```

```bash
# 檢查必要工具是否安裝
<tool> --version
```

### Step 2: 設定確認

確認必要的設定檔或環境變數存在：

```bash
# 例如
ls <config-file>
grep "REQUIRED_VAR" .env
```

若不存在，說明如何建立。

### Step 2.5: Effort Level 策略（視情況加入）

> 當 skill 在不同深度/廣度下有明顯差異時，在 Step 3 前加入此區塊。

當前 effort：${CLAUDE_EFFORT}

| Effort | 執行策略 |
|--------|---------|
| high | 完整執行（擴大掃描範圍、完整報告；附件下載等副作用仍需使用者逐次確認） |
| medium | 標準執行（預設設定值） |
| low | 最小步驟（只回報統計數字，跳過耗時子任務） |

> 若 `${CLAUDE_EFFORT}` 未設定或為 `normal`，視為 medium。effort 控制分析深度與資料範圍，不可逆操作（大量下載、外部寄信、付費 API 呼叫）不因 effort 自動授權，仍需使用者確認。

### Step 3: 執行

```bash
uv run python -m tasks.<task_module> <command> --<option> {{value}}
```

> `{{value}}` 為需向使用者確認的參數。

### Step 4: 報告結果

說明如何呈現輸出結果給使用者，包含：

- 成功/失敗狀態
- 關鍵數字（處理了多少筆、下載了多少檔案等）
- 需要使用者注意的例外情況

## 常見問題處理

| 問題 | 處理方式 |
|------|----------|
| <問題描述> | <解決方式> |

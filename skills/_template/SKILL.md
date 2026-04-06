---
name: <skill-name>
description: <一句話描述這個 skill 做什麼>
---

# <Skill 標題>

## 概要

簡短說明此 skill 的用途、使用情境，以及主要工具或依賴。

## 執行步驟

### Step 1: 環境檢查

確認工作目錄與必要工具：

```bash
cd ~/Workspace/github/side-project/my-daily-routine-skill
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

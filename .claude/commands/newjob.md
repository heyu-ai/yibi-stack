# New Job — 開啟新工作前準備

開始新 feature 或 fix 之前，執行此結構化流程確保環境乾淨。

## Step 1: 環境偵測

```bash
git rev-parse --show-toplevel
git status --short
```

**判斷邏輯**：

1. 檢查 uncommitted changes，有的話**警告**（提醒 stash 或 commit）
2. 用 `AskUserQuestion` 詢問新任務的描述，推導 branch 名稱

## Step 2: 建立 Feature Branch

根據使用者描述推導 branch 名稱（簡短有意義，例如 `fix-csv-parse`、`feat-receipt-upload`）。

```bash
# 確保 main 是最新的
git fetch origin main

# 建立 feature branch
git checkout -b <type>/<name> origin/main
```

## Step 3: Baseline Check

在當前工作目錄中執行：

### 3a. 同步依賴

確保 `.venv` 與最新 `pyproject.toml` 一致。

```bash
uv sync --all-extras
```

### 3b. 跑測試

```bash
uv run pytest
```

- 測試失敗是 **warning** 不是 blocker（使用者可能正要修 broken main）

## Step 4: Go/No-Go Report

輸出結構化報告：

```
=== New Job Report ===
Branch:      <name>
pytest:      ✅ passed / ⚠️ failed (N issues)
─────────────────────────
Verdict:     ✅ GO
```

- 所有項目都是 info/warning，不會產生 NO-GO verdict
- 但會在 warning 項目旁列出修復建議

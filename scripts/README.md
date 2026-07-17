# scripts/ 命名慣例

本目錄存放從 Claude 工作流程中抽出的獨立 script 檔案。

## 安裝依賴

**`uv sync` 不足以跑本目錄的帳務／PDF 腳本**——它們的依賴住在 `ledger` extra，預設不安裝
（PR #249：那些套件不出貨給 plugin 使用者，故移出 core dependencies）：

```bash
uv sync --extra ledger
```

未安裝時的症狀是 `ModuleNotFoundError: No module named 'pandas'`（或 sqlalchemy /
anthropic / pdfplumber / requests）。**不要用 `uv add pandas` 修**——那會把依賴加回 core，
一次一個套件地撤銷上述隔離。

受影響的腳本：`compare_billing.py`、`import_hsbc_missing.py`、`report_2024_2025.py`、
`categorize_hsbc.py`、`categorize_hsbc_rules.py`、`extract_saas_invoice_amounts.py` 等。
純 stdlib 的基礎設施腳本（`lint_skill_*.py`、`resolve-skill-repo`、`assert_not_worktree.sh`
等）不受影響，`uv sync` 即可。

## 命名規則

| 語言 | 格式 | 範例 |
|------|------|------|
| Shell | `<verb>_<object>.sh` | `safe_symlink.sh` |
| Python | `<subject>_<object>.py` | `categorize_hsbc.py` |

- 使用 snake_case
- 動詞開頭（shell）：`scan_`、`check_`、`list_`、`release_`、`detect_`
- 避免泛用名稱（不用 `helper.sh`、`utils.sh`、`temp.sh`）

## Script 建立方式

複雜 bash 應交給 `bash-to-script` subagent 處理：

```text
[Task tool with subagent_type=bash-to-script]
輸入：bash 內容 + 任務描述
```

## 適用情境

以下 AP1 sub-type 應抽出 script，不寫 inline bash：

- `for-loop` body 含 pipe 或 if（Cases 21/22）
- `heredoc | command` 管線（Case 23）
- `osascript` heredoc（Case 16）
- `python -c` 多行（Cases 17/18）

## Shell Script 標準結構

```bash
#!/bin/bash
# <一行目的說明>
# 用法：bash scripts/<filename>.sh [args]
set -euo pipefail

# 實作內容
```

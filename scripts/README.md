# scripts/ 命名慣例

本目錄存放從 Claude 工作流程中抽出的獨立 script 檔案。

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

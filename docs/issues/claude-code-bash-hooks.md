# anthropics/claude-code -- Bash Hook Behavior Issues

回報日期：2026-05-04

---

## 已回報項目

| ID | 類型 | 標題摘要 | 連結 | 狀態 |
|----|------|---------|------|------|
| P1 | comment | `"${VAR}"` 觸發 `Contains expansion`（false positive） | [#43713 comment](https://github.com/anthropics/claude-code/issues/43713#issuecomment-4371496357) | open |
| P2 | new issue | `Unhandled node type: string` 由 4 種不同 AST 結構觸發 | [#56018](https://github.com/anthropics/claude-code/issues/56018) | open |
| P3 | new issue | `cat <<'EOF' \| cmd` 觸發 `Unhandled node type: pipeline` | [#56019](https://github.com/anthropics/claude-code/issues/56019) | open |
| P5 | new issue | `cd && git` 被 hook；`cd && uv` / `find` / `alembic` 未被 hook | [#56020](https://github.com/anthropics/claude-code/issues/56020) | open |
| P4 | skipped | "Yes, don't ask again" allowlist 對整行指令做 literal-string match；任何參數變動均重新提示（已有 #9408 / #12796 覆蓋） | -- | dup，不回報 |

---

## 各項脈絡

### P1 -- comment on #43713

**問題**：`"${VAR}"` (braces + 雙引號，是 bash 推薦最安全寫法) 觸發 `Contains expansion`；
而較不精確的 `"$VAR"` 反而不觸發。Practical effect：越謹慎的寫法，得到越多 prompt。

**相關 issue**：[#43713](https://github.com/anthropics/claude-code/issues/43713)（open，原 issue 是 `autoAllowBashIfSandboxed` bypass，框架不同）

**追蹤重點**：維護者是否確認這是已知限制，或 #43713 範圍是否涵蓋此 false positive。

---

### P2 -- #56018

**問題**：同一條錯誤訊息 `Unhandled node type: string` 由至少 4 種結構觸發：

| 結構 | 範例 |
|------|------|
| (a) 同型引號巢狀 | `echo "v: $(echo "$HOME")"` |
| (b) for-loop + `\` 續行 + pipe | `for f in a.txt \ b.txt; do grep ... \| head; done` |
| (c) 雙引號 BRE alternation | `grep "alpha\|beta" file.txt` |
| (d) 反向巢狀 subshell | `BASE=$(dirname "$(git rev-parse --git-common-dir)")` |

**相關 issues**：#42085, #43246, #50144, #55479, #49483（均只回報症狀，未列出結構分類）

**追蹤重點**：維護者是否確認各結構是同一 code path，或需要分開修。

---

### P3 -- #56019

**問題**：`cat <<'EOF' | cmd` 觸發 `Unhandled node type: pipeline`；
`cmd < file` redirect 形式（需先將內容寫入暫存檔）可正常通過。

**相關 issue**：[#47701](https://github.com/anthropics/claude-code/issues/47701)（closed，framed as `file_redirect`；
我們的 `pipeline` node failure 是獨立的失敗點）

**追蹤重點**：維護者是否重開或新開來修 pipeline node handler。

---

### P5 -- #56020

**問題**：`cd && git` 被 "changes directory before running git" hook 攔截（正確行為）；
但 `cd && uv`、`cd && find`、`cd && alembic upgrade head` 等同風險組合未被攔截。
提問：scope 是刻意限定 git 嗎？

**相關 issues**：#28240, #30409, #28784, #30213（均從反向角度討論，即 hook 過於激進；
我們從正向角度問為何其他命令未涵蓋）

**追蹤重點**：維護者是否說明 scope 的設計意圖。

---

## 狀態更新區

> 每次檢查後在此記錄，格式：`YYYY-MM-DD：<摘要>`

- 2026-05-04：P2/P3/P5 開新 Issue，P1 留 comment，P4 略過。

---

## 未來可補充的 Pattern

根據語料尚有下列觀察尚未回報（留待確認是否值得追回報）。
Case 編號對應 `docs/bash-anti-pattern-violations.md` 的「Hook 攔截案例分析」節。
建議於 **2026-08-01** 前後確認 P2/P3/P5 上游回應時，一併評估是否回報以下 Pattern。

| Pattern | 描述 | 語料 case |
|---------|------|-----------|
| AP2 false positive | grep 指令本身含 `\|` hex 的 shell 命令被 AP2 hook 攔截 | Phase 4 驗證當下 |
| `python3 -c` + `# comment` + newline | B 類：換行後的 `#` 被視為 argument injection | Cases 17/18 |
| `2>/dev/null` + cd → F1 hook | cd + 非 git + redirection 觸發 path resolution bypass | Cases 10/11/15 |

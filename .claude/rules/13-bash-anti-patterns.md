# Bash 指令反模式（Anti-Patterns）

## Anti-Pattern 1：過度複雜的單一指令

判斷標準（complexity score：5 項中 >=2 項即過度，必須拆解）：

1. 多行（heredoc / 反斜線 `\` 續行）
2. 巢狀引號（雙引號內含單引號內含雙引號）
3. 內嵌其他語言（`python -c` / `node -e` / jq 多行複雜表達式）
4. 多層 if / elif / case 分支
5. 複雜參數展開（`${var//pattern/replace}`、間接引用 `${!var}`）

**不算過度**：純 git workflow chain（`git add && git commit && git push`）、
線性同性質串接（`make lint && make test`）。「&& 數量本身不是判斷項」。

對策優先序：

1. 拆成多個 bash call
2. 寫獨立 script 檔（`scripts/foo.sh`，再呼叫 `bash scripts/foo.sh`）
3. 用對的工具取代 inline 邏輯（JSON → `jq`、路徑 → `realpath` / `basename`）

黃金法則：永遠不要為了省一個 bash call 把多步邏輯擠進一行。

## Anti-Pattern 2：bash 指令字串內含特殊 Unicode

**範圍**：只限 bash 指令本身的字元內容（`echo` 字串、變數值 literal、檔名 literal、heredoc 內容）。

**不限制**：bash 讀取的檔案內容、bash 寫入檔案的文字、markdown 文件、code 註解、commit message。

下列字元在 bash 指令字串內**禁止使用**：em dash（—）/ en dash（–）/ emoji / 零寬空白。

| 原本 | 改成 |
|------|------|
| skip 圖示 | `[SKIP]` |
| ok 圖示 | `[OK]` |
| warn 圖示 | `[WARN]` |
| fail 圖示 | `[FAIL]` |
| em dash — | `--` |
| en dash – | `-` |

CJK 文字、全形標點（，、。：「」）、ASCII 標點均 OK。

## 寫 bash 前的 5 秒自我檢查

- [ ] 有換行 / heredoc / `\` 續行嗎？
- [ ] 引號超過兩層嵌套嗎？
- [ ] 內嵌 Python / Node / Perl / 複雜 jq 嗎？
- [ ] 有多層 if/elif/case 嗎？
- [ ] 有巢狀參數展開 `${A:-$B}` 嗎？
- [ ] 字串內有 emoji / em dash / 零寬空白嗎？

任兩項 yes → 拆 bash call / 寫獨立 script / 換工具（jq / sed / realpath）

## 完整方法論

跨專案完整版見 skill `bash-anti-patterns`（含 before/after 範例、agent 自檢 checklist、
技術背景、可選裝 PreToolUse hook）。

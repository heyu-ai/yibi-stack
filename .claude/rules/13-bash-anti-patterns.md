# Bash 指令反模式（Anti-Patterns）

## Anti-Pattern 1：過度複雜的單一指令

判斷標準（complexity score：5 項中 >=2 項即過度，必須拆解）：

1. 多行（heredoc / 反斜線 `\` 續行）
2. 巢狀引號（雙引號內含單引號內含雙引號；或 `$(cmd "$VAR")` 同型引號衝突）
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

### AP1 Sub-type：for-loop-file-list

`for f in file1 \ file2 \; do ... done` 是常見的「想省 bash call 而把 script 擠進一行」模式。
以下任一條件即需改寫為獨立 script：

- for body 超過 1 行
- for body 含 pipe（`|`）
- for body 含 if / elif

```bash
# 違規：for loop + if + pipe 三層（AP1 score 3/5）
for f in a.py \
         b.py; do
  COUNT=$(grep -c "pattern" "$f")
  if [ "$COUNT" -gt 0 ]; then grep -n "pattern" "$f"; fi
done

# 修法：寫成獨立 script 再執行
bash scripts/scan_pattern.sh
```

### AP1 Sub-type：同型引號衝突（Nested Same-type Quotes）

`echo "result: $(cmd "$VAR")"` — 外層雙引號內的 `$()` 再度使用雙引號，
Claude Code hook 的靜態分析器無法處理此巢狀結構，hook 回報 `Unhandled node type: string`。

```bash
# 違規：echo 內嵌 $(git -C "$MAIN_REPO" ...)
echo "Main updated to: $(git -C "$MAIN_REPO" rev-parse --short HEAD)"

# 修法：拆成獨立 bash call，讓 Claude 判讀輸出
git -C "$MAIN_REPO" rev-parse --short HEAD
```

cd-before-git 的標準修法仍是 `git -C <path>`（Cases 7/12 建立）；問題在於把它包進 `echo "$()"` 的複合結構，而非 `git -C` 本身。

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
- [ ] 內嵌 Python / Node / 複雜 jq 嗎？
- [ ] 有多層 if/elif/case 嗎？
- [ ] 有複雜參數展開 `${var//pat/rep}` / 間接引用 `${!var}` 嗎？

以上 >=2 項 yes → 拆 bash call / 寫獨立 script / 換工具（sed / realpath / 簡單 jq）

- [ ] 字串內有 emoji / em dash（—）/ en dash（–）/ 零寬空白嗎？

yes → 依 Anti-Pattern 2 對照表替換（獨立規則，不計入上方門檻）

## AP2 自動攔截

`.claude/hooks/bash-ap2-check.py` 是 PreToolUse hook，自動偵測並攔截 AP2 違規。
攔截範圍：em dash / en dash / 零寬空白 / U+2300-U+23FF / U+2600-U+27BF / U+1F000-U+1FAFF。
（U+2400-U+25FF Box Drawing 等刻意排除，避免 tree/eza 輸出誤攔。）

AP1 複雜度判斷需要推理，不適合 hook 自動攔截，仍需靠 5 秒自我檢查。

## 高頻違規速查（已構成 AP1，直接拆解）

以下模式只要出現即違規，不需再逐項算分：

### `python3 -c "..."` 含換行

```bash
# 違規：多行 + 內嵌 Python = score 2
uv run python3 -c "
import asyncio
...
    result = await session.execute(text('''SELECT ...'''))
" 2>&1

# 修法：提取成獨立 .py，用 --directory 取代 cd
uv run --directory /path/to/project python3 scripts/check_stats.py
```

`python3 -c` 內的 `# comment` 加上換行，另會觸發 hook B 類攔截
（"Newline followed by # inside a quoted argument"）。

### `osascript << 'TAG'` heredoc

```bash
# 違規：多行 heredoc + 內嵌 AppleScript = score 2
osascript << 'ASCRIPT'
tell application "System Events"
    ...
end tell
ASCRIPT

# 修法：提取成 .applescript 檔案
osascript scripts/check_windows.applescript
```

`$(cat <<'EOF')` 用於 commit message 純文字時有豁免；osascript/DSL heredoc **不豁免**。

### `cd /abs/path && cmd`（CWD 污染）

cd-before-command 不算 AP1 complexity 分項，但與 inline Python 合用時加重複雜度，
且污染 session CWD。標準替代：

| 工具 | 修法 |
|------|------|
| uv run | `uv run --directory /path python3 scripts/xxx.py` |
| git | `git -C /path log --oneline` |
| pytest | `uv run --directory /path pytest` |

### output filter pipeline `\| grep -v "..."`

```bash
# 違規：用 bash pre-filter 替代 Claude 判讀輸出
cmd 2>&1 | grep -v "^2026\|INFO\|BEGIN\|ROLLBACK"

# 修法：移除 grep filter，Claude 直接接收完整輸出
cmd 2>&1
```

## 完整方法論

跨專案完整版見 skill `bash-anti-patterns`（含 before/after 範例、agent 自檢 checklist、
技術背景、可選裝 PreToolUse hook）。

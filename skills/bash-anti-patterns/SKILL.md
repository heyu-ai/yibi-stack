---
name: bash-anti-patterns
type: know
scope: global
description: 識別與避免 Claude Code agent 下 bash 指令時的兩大 parser 失敗模式：(1) 過度複雜的單一指令（多行 heredoc、巢狀引號、內嵌 Python -c / Node -e / jq 多行表達式、複雜參數展開、多層 if/elif），(2) bash 指令字串本身含特殊 Unicode 字元（em dash、en dash、emoji 在 echo 字串內）導致 parser 失敗。必須觸發的情境：用戶看到 parser 錯誤「Newline followed by # inside a quoted argument」「Unhandled node type: string」、bash heredoc 失敗、「為什麼這個 echo 跑不了」、「複雜 bash 指令拆解」、「bash one-liner 太長」、「bash inline script 太肥」、「heredoc 內嵌 Python 失敗」、「em dash bash」、「emoji 在 bash 字串內」、agent 自我反省「我下的 bash 指令是不是太複雜」「要不要把這段 bash 拆 step」「該不該寫成 script 檔再呼叫」時。不應觸發於：「複雜 SQL 拆解」「複雜 Python script 拆解」「commit message 含 emoji」等非 bash 指令範疇的需求。
---

# Bash Anti-Patterns — Claude Code Agent 下 bash 指令的兩大陷阱

本 Skill 提供系統化的 bash 指令編寫規範，防止 parser 失敗打斷工作流程。

## 核心理念

- **bash call 是廉價的，parser 重試是昂貴的**
- 複雜度的成本最終由使用者在 Cmd+Enter 上付出
- 黃金法則：永遠不要為了「省一個 bash call」把多步邏輯擠進一行

## Anti-Pattern 1：過度複雜的單一指令

### 症狀

踩雷時會看到下列 parser 錯誤，改 escape 也沒用：

- `Newline followed by # inside a quoted argument`（類別 B）
- `Unhandled node type: string`（類別 D）

### 判斷標準（≥2 項即過度，必須拆解）

以下 5 項，同時出現兩個以上就是複雜度過高：

1. **多行**（heredoc 或反斜線 `\` 續行）
2. **巢狀引號**（雙引號內含單引號內含雙引號）
3. **內嵌其他語言**（`python -c`、`node -e`、`perl -e`、jq 多行複雜表達式）
4. **多層 if / elif / case 分支**
5. **複雜參數展開**（`${var//pattern/replace}`、`${!indirect}`、`${var%suffix}` 串接）

### 不算過度的情境（不要誤判這些）

以下都是合法用法，不構成反模式：

```bash
# 合法的 git workflow chain — && 數量不是問題
git add . && git commit -m "feat: add feature" && git push origin feature

# 合法的工具串接
make lint && make test

# 合法的簡單條件（各自獨立，不要合併成 && ... || ...）
[ -f ".env" ] || echo "[WARN] .env not found"
[ -f ".env" ] && source .env
# 避免：[ -f ".env" ] && source .env || echo "..."
# 原因：source 失敗時 || 也會觸發 echo，語意錯誤
```

**「&& 數量本身不是判斷項」** — 問題在每段操作的內部複雜度，不在串接數量。

### 對策（依優先序）

**1. 拆成多個 bash call（最常見也最簡單）**

每個 call 解一個問題，agent 看完再決定下一步：

```bash
# 錯：一行塞太多
RESULT=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(data.get('key', {}).get('nested', ''))
" <<< "$INPUT")

# 對：分兩步
echo "$INPUT" > /tmp/input.json
RESULT=$(jq -r '.key.nested // empty' /tmp/input.json)
```

**2. 寫成獨立 script 檔**

放 `~/.claude/scripts/` 或專案 `scripts/`，從 bash 呼叫 `bash <path>`：

```bash
# 錯：heredoc 內嵌複雜 Python
bash -c "$(cat <<'PYEOF'
import re, sys
for line in sys.stdin:
    if re.match(r'pattern', line):
        ...
PYEOF
)"

# 對：寫成獨立 script，從 bash 呼叫
cat > /tmp/process.py << 'EOF'
import re, sys
for line in sys.stdin:
    if re.match(r'pattern', line):
        print(line.rstrip())
EOF
python3 /tmp/process.py < input.txt
```

**3. 用對的工具取代 inline 邏輯**

| 需求 | 不要用 | 改用 |
|------|--------|------|
| JSON 處理 | `python3 -c "import json..."` | `jq` |
| 路徑操作 | `${VAR%/*}` 字串展開 | `dirname` / `basename` / `realpath` |
| 簡單條件 | `if/elif/else` 三層 | `[ ]` + `&&`/`\|\|` 或 `case` |
| 文字過濾 | inline `awk '{if...}'` | `grep -E` 或拆成多個 `grep` + `cut` pipe |

### Before / After 完整範例

**範例 A：jq 巢狀條件 → 兩段 pipe**

```bash
# 錯：jq 多行複雜表達式（內嵌語言 + 多層條件 = score 2）
RESULT=$(jq -r '
  if .status == "active" then
    .users[] | select(.role == "admin") | .name
  else
    "inactive"
  end
' config.json)

# 對：拆成兩段
STATUS=$(jq -r '.status' config.json)
if [ "$STATUS" = "active" ]; then
  RESULT=$(jq -r '.users[] | select(.role == "admin") | .name' config.json)
fi
```

**範例 B：複雜 if/elif → case statement**

```bash
# 錯：多層 if/elif（多層分支 = score 1，加上複雜參數展開 ${EXT##*.} = score 2）
EXT="${FILENAME##*.}"
if [ "$EXT" = "py" ]; then
  RUNNER="python3"
elif [ "$EXT" = "js" ]; then
  RUNNER="node"
elif [ "$EXT" = "rb" ]; then
  RUNNER="ruby"
elif [ "$EXT" = "sh" ]; then
  RUNNER="bash"
else
  RUNNER="unknown"
fi

# 對：先用 basename 取副檔名，再用 case
EXT=$(basename "$FILENAME" | cut -d. -f2)
case "$EXT" in
  py) RUNNER="python3" ;;
  js) RUNNER="node" ;;
  rb) RUNNER="ruby" ;;
  sh) RUNNER="bash" ;;
  *)  RUNNER="unknown" ;;
esac
```

**範例 C：heredoc inline Python → 拆出獨立 script**

```bash
# 錯：heredoc + 內嵌 Python（score 1 + score 3 = 2，過度）
python3 - <<'EOF'
import sys, json
data = json.load(sys.stdin)
for item in data.get('items', []):
    if item.get('active'):
        print(item['name'])
EOF

# 對：把 Python 寫成獨立檔，cat heredoc 寫檔（score 1 = 可接受）
# 說明：cat > file 的 heredoc 只寫檔，不執行 Python，score 從 2 降到 1
cat > /tmp/filter_active.py << 'EOF'
import sys, json
data = json.load(sys.stdin)
for item in data.get('items', []):
    if item.get('active'):
        print(item['name'])
EOF
python3 /tmp/filter_active.py < data.json
```

## Anti-Pattern 2：bash 指令字串內含特殊 Unicode

### 範圍（請先讀清楚，避免過度限制）

**本規範只限制：bash 指令本身的字元內容**

- `echo` 的字串參數
- 變數值 literal
- 檔名 literal
- bash 內 heredoc 內容

**不限制：**

- bash 讀取的檔案內容（`cat README.md` 內含 emoji 沒問題）
- bash 寫入檔案的內容（寫到 `.md` 的文字屬檔案層面）
- markdown 文件純文字段落
- 程式碼註解
- commit message 文字（git 接受 UTF-8）

### 哪些字元會卡 parser

以下字元出現在 **bash 指令字串內**，會卡住 Claude Code bash tool parser：

| 類型 | 範例字元 | Unicode 範圍 |
|------|---------|------------|
| Em dash | — | U+2014 |
| En dash | – | U+2013 |
| Emoji（圖示類）| 大部分 Unicode 表情符號 | U+1F300–U+1FAFF、U+2600–U+27BF |
| 零寬空白 | （不可見） | U+200B 等 |

**CJK 字元、全形標點、ASCII 標點均 OK。**

### 替代對照表（bash 指令字串內）

| 原本 | 改成 |
|------|------|
| 跳過圖示（skip 類）| `[SKIP]` 或 `(skipped)` |
| 勾選圖示（ok 類）| `[OK]` 或 `(ok)` |
| 警告圖示（warn 類）| `[WARN]` 或 `(warn)` |
| 失敗圖示（fail 類）| `[FAIL]` 或 `(fail)` |
| 火箭圖示（go 類）| `[GO]` |
| Em dash — | `--`（ASCII 雙連字號）|
| En dash – | `-`（ASCII 連字號）|

### 範例

```bash
# 錯：emoji 在 bash echo 字串內（這行會卡 parser）
echo "  ⏭ 無 docker-compose，跳過"

# 對：改用 ASCII 替代
echo "  [SKIP] 無 docker-compose，跳過"

# 錯：em dash 在 bash echo 字串內
echo "PREREQ: NOT_FOUND — stop here"

# 對：改用 ASCII 雙連字號
echo "PREREQ: NOT_FOUND -- stop here"

# OK：emoji 在 markdown 文件段落（這不是 bash 指令）
# README.md: > ✅ 安裝完成

# OK：bash cat 讀含 emoji 的檔案（emoji 在檔案內，不在 bash 字串）
cat README.md
```

## Agent 自我檢查 Checklist

下 bash 指令前快速自問：

- [ ] 這個 bash call 有換行嗎？（heredoc、反斜線續行）
- [ ] 引號超過兩層嗎？（`"''"` 這種）
- [ ] 內嵌了其他語言嗎？（`python -c`、`node -e`、jq 多行）
- [ ] bash 字串內有 emoji 或 em dash 嗎？

**任兩項為 yes → 拆成多個 bash call / 寫 script 檔 / 換工具**

## 在你的專案啟用本規範

### 路徑 1：複製 rule 範本（推薦，永久生效）

把以下 markdown 存成你專案的 `.claude/rules/13-bash-anti-patterns.md`，
Claude Code session 將無條件載入此規範（不需關鍵字觸發）：

```markdown
# Bash 指令反模式（Anti-Patterns）

## Anti-Pattern 1：過度複雜的單一指令

判斷標準（complexity score：5 項中 >=2 項即過度，必須拆解）：

1. 多行（heredoc / 反斜線續行）
2. 巢狀引號（雙引號內含單引號內含雙引號）
3. 內嵌其他語言（python -c / node -e / jq 多行表達式）
4. 多層 if / elif / case 分支
5. 複雜參數展開（${var//pattern/replace}、間接引用）

不算過度：純 git workflow chain（git add && git commit && git push）、
線性同性質串接（make lint && make test）。
「&& 數量本身不是判斷項」。

對策優先序：
1. 拆成多個 bash call
2. 寫獨立 script 檔
3. 用 jq / realpath / sed 取代 inline 邏輯

黃金法則：永遠不要為了省一個 bash call 把多步邏輯擠進一行。

## Anti-Pattern 2：bash 指令字串內含特殊 Unicode

範圍：只限 bash 指令本身的字元內容（echo 字串、變數值、檔名 literal）。
不限制：bash 讀取的檔案內容、markdown 文件、code 註解、commit message。

下列字元在 bash 指令字串內禁止使用：em dash / en dash / emoji / 零寬空白。

替代：[SKIP] / [OK] / [WARN] / [FAIL] / [GO] / -- / -

CJK 文字、全形標點、ASCII 標點均 OK。

完整方法論見 skill `bash-anti-patterns`（含 before/after 範例與可選裝 hook）。
```

### 路徑 2：安裝 PreToolUse hook（進階，機械性阻擋 Anti-Pattern 2）

如果 prompt 教學不足以阻止 agent 重複在 bash 字串內放 emoji / em dash，
可加裝 hook 強制 exit 2 阻擋：

1. 從本 repo 複製 `hooks/pre-tool-use-bash-unicode.sh` 到你專案的 `.claude/hooks/`
2. 在 `.claude/settings.json` 加入：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/pre-tool-use-bash-unicode.sh"
          }
        ]
      }
    ]
  }
}
```

> 注意：此 hook 只擋 Anti-Pattern 2（Unicode 機械偵測）。Anti-Pattern 1 的 complexity
> 判斷靠本 rule + skill 的 prompt 教學（語意複雜，hook 易誤判）。

## 為什麼會這樣（技術背景）

Claude Code 的 bash tool 使用簡化 shell parser 而非完整的 bash AST parser：

- Heredoc 內的 `#` 字元、引號巢狀超過一定深度，觸發 parser edge case
- Unicode codepoint 在某些平台的 byte boundary 處理有 off-by-one bug
- 這些問題與特定 bash 版本或 OS 無關，是 tool 層的限制

不需深究實作細節——記住判斷標準與對策就夠。

## 與本 repo 的關係

本 skill 為跨專案完整版。在 ainization-skill repo 內 `.claude/rules/13-bash-anti-patterns.md`
是同主題的精簡子集，內容方向一致但允許 skill 更詳細。

維護紀律：改 rule 核心判斷標準時必須同步 skill；改 skill 增加範例或技術背景時，
不一定要改 rule。

---
name: bash-anti-patterns
type: know
scope: global
description: >-
  識別與避免 Claude Code agent 下 bash 指令的三層防線：(1) Anti-Pattern 1
  過度複雜單行（多行 heredoc、巢狀引號、內嵌 Python -c / Node -e、複雜 if/elif、
  for-loop-file-list），(2) Anti-Pattern 2 bash 字串內特殊 Unicode（em dash、
  en dash、emoji），(3) Anti-Pattern 3 stateful cd（CWD 污染 / cd-before-git /
  cd + 2>/dev/null 路徑隱藏）。另含 Rule 14 shell 引號衛生（simple_expansion /
  同型引號衝突 / grep BRE alternation / 反向巢狀 subshell / expansion false
  positive）與 Rule 15 不可逆操作邊界（alembic migrate / terraform apply /
  git push --force / rm -rf / kubectl apply）。觸發情境：parser 錯誤「Unhandled
  node type: string」「Contains simple_expansion」「Contains expansion」「Newline
  followed by # inside quoted argument」、「bash heredoc 失敗」、「cd 會污染 CWD」、
  「stateful cd」、「不可逆操作要不要執行」、「terraform apply 確認」、「git push
  --force 安全嗎」、agent 自我反省「這段 bash 太複雜」「要不要寫成 script」
  「cd 指令要不要改成 --directory」時。
---

# Bash Anti-Patterns — Claude Code Agent 下 bash 指令的三層防線

本 Skill 提供系統化的 bash 指令編寫規範，防止 parser 失敗打斷工作流程，
同時設定不可逆操作的 autonomy 邊界。三個 rule 檔可獨立啟用。

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
- [ ] 引號超過兩層嗎？（`"''"` 這種，或 `$(cmd "$VAR")` 同型衝突）
- [ ] 內嵌了其他語言嗎？（`python -c`、`node -e`、jq 多行）
- [ ] bash 字串內有 emoji 或 em dash 嗎？
- [ ] 含 `cd <path> &&` 嗎？→ 判斷子類，改用 `--directory` / `git -C` / 絕對路徑
- [ ] 用了 `grep "...\|..."` 雙引號 BRE 嗎？→ 改單引號
- [ ] 用了 `$(outer "$(inner)")` 反向巢狀嗎？→ 拆兩 call
- [ ] 這是不可逆操作嗎？（rm -rf / force push / migrate / publish）→ 先說明，等確認
- [ ] 用了 `sudo` / `env` / `watch` 等 wrapper 包不可逆操作嗎？→ deny rule 仍會攔截，不要以為 wrapper 能繞過

**AP1 門檻：換行 / 引號 / 內嵌語言 三項中任兩項 yes → 拆 bash call / 寫 script / 換工具**

## 在你的專案啟用本規範

三個 rule 可獨立啟用。把 `.md` 存到專案的 `.claude/rules/`，Claude Code session
將無條件載入（不需關鍵字觸發）。

### Rule 13：bash 指令反模式（AP1 + AP2 + AP3）

存成 `.claude/rules/13-bash-anti-patterns.md`：

```markdown
# Bash 指令反模式（Anti-Patterns）

## Anti-Pattern 1：過度複雜的單一指令

判斷標準（complexity score：5 項中 >=2 項即過度，必須拆解）：
1. 多行（heredoc / 反斜線續行）
2. 巢狀引號（雙引號內含單引號，或 $(cmd "$VAR") 同型衝突）
3. 內嵌其他語言（python -c / node -e / jq 多行表達式）
4. 多層 if / elif / case 分支
5. 複雜參數展開（${var//pattern/replace}、間接引用）

不算過度：純 git workflow chain、線性工具串接（make lint && make test）。
「&& 數量本身不是判斷項」。對策：拆 bash call / 寫 script / 換 jq|realpath 工具。
黃金法則：永遠不要為了省一個 bash call 把多步邏輯擠進一行。

## Anti-Pattern 2：bash 指令字串內含特殊 Unicode

範圍：bash 指令本身的字元內容（echo 字串、變數值 literal、heredoc 內容）。
不限制：bash 讀取的檔案內容、markdown 文件、code 註解、commit message。
禁用：em dash（—）/ en dash（–）/ emoji / 零寬空白。
替代：[SKIP] / [OK] / [WARN] / [FAIL] / -- / -

## Anti-Pattern 3：Stateful cd

cd <path> && cmd 三種危害，選對修法：
- cd ... && git <cmd>         -> git -C <path> <cmd>（C 類 hook 攔）
- cd ... && uv run            -> uv run --directory <path>（無 hook 攔，靜默盲點）
- cd ... && cmd 2>/dev/null   -> 改絕對路徑，移除 cd（F1 類 hook 攔）

完整方法論見 skill bash-anti-patterns。
```

### Rule 14：shell 引號衛生

存成 `.claude/rules/14-shell-quoting-hygiene.md`：

```markdown
# Shell Quoting Hygiene（引號衛生）

Rule 1：$(cmd $VAR) 裡的 $VAR 一律加引號 -> "$VAR"（防 simple_expansion；注意：避免括號形式 "${VAR}"，見 Rule 5）
Rule 2："$(cmd "$VAR")" 同型引號衝突 -> 拆成獨立 bash call（防 D 類）
Rule 3：grep "pat\|pat2" 雙引號 BRE -> grep 'pat\|pat2'（防 D 類）
Rule 4：$(outer "$(inner)") 反向巢狀 -> 拆成兩個獨立 bash call（防 D 類）
Rule 5："${VAR}" 括號形式觸發 expansion false positive -> 改 "$VAR" plain form

完整方法論與判斷流程見 skill bash-anti-patterns。
```

### Rule 15：不可逆操作邊界

存成 `.claude/rules/15-irreversible-operations.md`：

```markdown
# 不可逆操作邊界

以下操作不得由 agent 自主執行，必須先說明影響讓使用者確認：

DB / Storage：alembic upgrade/downgrade、prisma migrate deploy、DROP/TRUNCATE/DELETE 無 WHERE
Deployment：kubectl apply（prod）、terraform apply、gh release create、npm/uv publish
Git：git push --force/-f、git reset --hard、shared branch rebase、git filter-branch
File：rm -rf、find ... -delete、> 覆寫已存在檔案
Cloud：aws s3 rm --recursive、gcloud compute instances delete

標準回應格式：
STOP：操作描述
影響：<資源與範圍>
回滾難度：高 / 中 / 低
建議：<dry-run 指令 或 請使用者手動執行>

完整清單與 v3 deny list backlog 見 skill bash-anti-patterns。
```

### 路徑 2：安裝 PreToolUse hooks（進階，機械性攔截）

加裝兩支 hook 可機械性阻擋最高頻的 AP1 / AP2 違規：

1. 從本 repo 複製 hooks：
   - AP1 hook：`.claude/hooks/bash-ap1-inline-check.sh`（攔截 python -c 多行 / osascript heredoc / grep BRE alternation / 反向巢狀 subshell）
   - AP2 hook：`.claude/hooks/bash-ap2-check.py` 或 `hooks/pre-tool-use-bash-unicode.sh`（攔截 Unicode）

2. 在 `.claude/settings.json` 加入：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/bash-ap1-inline-check.sh" },
          { "type": "command", "command": "python3 $CLAUDE_PROJECT_DIR/.claude/hooks/bash-ap2-check.py" }
        ]
      }
    ]
  }
}
```

AP3 / Rule 14 Rule 5 / Rule 15 的複雜度判斷靠 prompt rule 教學，不在 hook 範圍。

## exec wrapper 穿透 deny rule（2026-05）

Claude Code `settings.json` 的 `permissions.deny` 清單現在可穿透以下 wrapper 指令：

| wrapper | 說明 |
|---------|------|
| `sudo` | 權限提升 |
| `env` | 環境變數設定 |
| `watch` | 週期執行 |
| `ionice` | I/O 優先級設定 |
| `setsid` | 新 session 執行 |

**重要**：以下寫法全部都會被 deny rule 攔截，不要誤以為 wrapper 能繞過：

```bash
# 這類寫法也會被 deny rule 攔截
sudo rm -rf /dangerous/path
env DANGEROUS_VAR=1 bash script.sh
watch -n1 bash -c "rm /tmp/files"
ionice -c 3 rm -rf /path
```

**使用者應善用此機制**：在 `settings.json` 設好 deny rule 後，即使 agent
生成帶 wrapper 的指令，仍會被攔截。這是加強 Rule 15 不可逆操作防護的可靠手段：

```json
{
  "permissions": {
    "deny": [
      "Bash(rm -rf*)",
      "Bash(sudo rm*)",
      "Bash(env * rm*)"
    ]
  }
}
```

**對 agent 的影響**：被 deny rule 攔截時，agent 應停止並說明操作內容，
請使用者確認後手動執行（Rule 15 標準行為），而非嘗試改用 wrapper 繞過。

## 為什麼會這樣（技術背景）

Claude Code 的 bash tool 使用簡化 shell parser 而非完整的 bash AST parser：

- Heredoc 內的 `#` 字元、引號巢狀超過一定深度，觸發 parser edge case
- Unicode codepoint 在某些平台的 byte boundary 處理有 off-by-one bug
- 這些問題與特定 bash 版本或 OS 無關，是 tool 層的限制

不需深究實作細節——記住判斷標準與對策就夠。

## 與本 repo 的關係

本 skill 為跨專案完整版。yibi-stack repo 內的三個 rule 檔是精簡子集：

- `.claude/rules/13-bash-anti-patterns.md`：AP1/AP2/AP3 判斷標準與速查
- `.claude/rules/14-shell-quoting-hygiene.md`：五類引號錯誤 Rules 1-5
- `.claude/rules/15-irreversible-operations.md`：五類不可逆操作邊界

維護紀律：改 rule 核心判斷標準時必須同步 skill；改 skill 增加範例或技術背景時，
不一定要改 rule。三個 rule 可各自獨立維護，互不依賴。

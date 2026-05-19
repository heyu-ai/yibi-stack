# Shell Quoting Hygiene（引號衛生）

Cases 3/8/16/17/24/25/26 累積出的五類引號錯誤，hook 類別均為 E（`simple_expansion`）、D（parser 失敗）或 E-false-positive。

## Quoting Rule 1：subshell 內變數必須加引號

`$(cmd $VAR)` 中的 `$VAR` 若未加引號，路徑含空格時 word-split 導致錯誤。
hook 回報 `simple_expansion`。

```bash
# 違規：$MAIN_REPO 在 $() 內未加引號
echo "path: $(ls $MAIN_REPO/docker-compose.yml 2>/dev/null || echo 'not found')"

# 修法：拆成獨立 bash call
ls "${MAIN_REPO}/docker-compose.yml" 2>/dev/null || echo 'not found'
```

適用場景：任何 `$(cmd $VAR ...)` 形式，`$VAR` 一律加 `"$VAR"` 或 `"${VAR}"`。

## Quoting Rule 2：`"$(cmd)"` 外層雙引號包 subshell

外層雙引號內含 `$(...)` subshell，parser 無法處理此結構，回報 `Unhandled node type: string`。
**即使 subshell 內沒有內層引號也會觸發**。

```bash
# 違規 A：subshell 內有內層引號
echo "Main updated to: $(git -C "$MAIN_REPO" rev-parse --short HEAD)"

# 違規 B：subshell 內無內層引號（同樣觸發）
git -C "$(git rev-parse --show-toplevel)" branch --show-current

# 修法（兩種情況相同）：拆成臨時變數 + 獨立 bash call
WT=$(git rev-parse --show-toplevel)
git -C "$WT" branch --show-current

HEAD=$(git -C "$MAIN_REPO" rev-parse --short HEAD)
echo "Main updated to: $HEAD"
```

## Quoting Rule 3：grep BRE alternation 一律用單引號

`grep "pat1\|pat2"` 雙引號內含 `\|`，bash 靜態分析器對 string node 中的反斜線逸出 `|`
無法分類，回報 `Unhandled node type: string`。即使 AP1 score 僅 1/5，hook 仍觸發（Case 25）。

```bash
# 違規：雙引號 BRE alternation
grep -i "media\|cdn\|delivery" file.txt

# 修法 A（最優先）：單引號 BRE
grep -i 'media\|cdn\|delivery' file.txt

# 修法 B：改用 ERE（-E flag）
grep -Ei 'media|cdn|delivery' file.txt
```

適用場景：任何 `grep "...\|..."` 形式，一律改單引號或 `-E` flag。

## Quoting Rule 4：`$(outer "$(inner)")` 必拆 bash call

外層 `$()` 包雙引號包內層 `$()` 是 Rule 2 的反向變體，parser 同樣失敗（Case 26）。

```bash
# 違規：反向巢狀 subshell
MAIN_REPO=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")

# 修法：拆成兩個獨立 bash call
GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir)
MAIN_REPO=$(dirname "$GIT_COMMON")
```

與 Rule 2 的差異：Rule 2 是「外層 `"..."` → `$()` → 內層 `"$VAR"`」；
Rule 4 是「外層 `$()` → `"$(inner)"` 」，方向相反，根本原因相同。

## Quoting Rule 5：變數展開觸發 expansion false positive（Case 24）

Claude Code 內建 parser 廣義攔截所有 `expansion` / `simple_expansion` AST 節點，
**不區分是否已加引號、是否在 subshell 內**——兩種形式都會觸發：

| 形式 | 觸發訊息 |
|------|---------|
| `"${VAR}"` 括號形式 | `Contains expansion` |
| `"$VAR"` plain form | `Contains simple_expansion` |

兩者都是 **false positive**——bash 語法正確，攔截來自 parser 設計，與是否加引號無關。

```bash
# 兩種形式都觸發（語法正確，但 parser 攔截）
test -n "${CODEX_API_KEY}" -o -n "${OPENAI_API_KEY}" && echo "AUTH: KEY_SET" || true
test -n "$CODEX_API_KEY" -o -n "$OPENAI_API_KEY" && echo "AUTH: KEY_SET" || true
```

**根本修法依情境分兩條路**：

**A. 單行指令（`cmd "$VAR"`）→ 加進 allow list**（settings.json）：

```json
"Bash(rg *)",
"Bash(git -C *)",
"Bash(basename *)",
"Bash(dirname *)",
"Bash(test -n *)",
"Bash([ -n *)"
```

**B. ≥2 個 `"$VAR"` 展開的複合腳本 → 拆 bash call 或寫成 script**：

多行腳本無法用 prefix wildcard allow-list（pattern 無法跨行匹配），必須重構：

| 場景 | 修法 |
|------|------|
| 2-4 行、變數間有依賴 | 拆成獨立 bash call，各自被 allow-list 覆蓋 |
| 5+ 行或重複使用 | 寫成 `scripts/foo.sh`，bash 只剩 `bash scripts/foo.sh` |

```bash
# 違規：多行 multi-var script，每次都跳確認框
WT_ROOT=$(git -C /path rev-parse --show-toplevel)
WT_NAME=$(basename "$WT_ROOT")
REVIEW_DIR="/tmp/pr-review/$WT_NAME"
mkdir -p "$REVIEW_DIR"

# 修法 A：拆成 4 個獨立 bash call（各自被 Bash(git -C *) / Bash(basename *) 等覆蓋）
# 修法 B：寫成 scripts/setup_review_dir.sh 再執行
```

**判斷門檻**：一個 bash call 內出現 **≥2 個 `"$VAR"` 展開**，視為 AP1 sub-type，必須拆解或寫 script。

重要限制：**切勿用 `printenv` 或 `echo $VAR` 印出 key 值**——會將 API key 明文記錄
至 session transcript。確認 key 存在一律用 `test -n`，不用 `echo` 或 `printenv`。

根本原因在 Claude Code 內建 parser 層（非本 repo hook 範圍），無法從 hook 側修正。
v3 backlog：hook 應補強「`expansion` / `simple_expansion` 節點已被 `"..."` 包住則豁免」。

## Bash 單引號語意備忘（hook 實作相關）

Bash 單引號內 backslash 是 **literal**，不是 escape 字元。
只有雙引號內的 backslash 才能 escape 下一個字元。

```bash
printf '%s\' "$(id)"   # 單引號不處理 \，closing ' 實際在 \ 後面
                        # 正確解析：'%s\' 是完整 token，後面的 "$(id)" 才是 Rule 2 違規
```

這是 hook 的 `_quote_state_at()` state machine 的關鍵行為：

```python
if c == "\\" and in_double:   # 只在雙引號內跳過下一個字元
    i += 2
    continue
# 單引號內：backslash 當普通字元，不跳過
```

繞過此語意（用 `in_double or in_single` 錯誤地在單引號內也 escape）
會讓 `printf '%s\' "$(id)"` 的 Rule 2 match 被跳過，造成靜默放行。

## 判斷流程

**`$(...)` 模式**（Rules 1-2）：

```text
寫 $(...)  →  裡面有 $VAR 嗎？
                是 → 加引號："$VAR"（Rule 1）→ 繼續往下
                否 → 繼續
             外層是 "..." 包住的嗎？
                否 → 放行
                是 → 裡面再出現 "..." 嗎？
                       否 → 放行
                       是 → 拆成獨立 bash call（Rule 2）
```

注意：`"${VAR}"` 和 `"$VAR"` 在 `$(...)` 外作為獨立引數（如 `test -n "$VAR"`）都會觸發 false positive，見 Rule 5。
若變數後緊接前後綴（如 `"${prefix}_suffix"`），不可改為 `"$VAR"`（會讀到 `$prefix_suffix`）——此情況改寫成 `"${prefix}"_suffix`，並加進 allow list。

**其他模式快速對照**（Rules 3-5；Rules 1-2 見上方流程圖）：

| 模式 | 觸發訊息 | 規則 | 修法 |
|------|---------|------|------|
| `grep "...\|..."` 雙引號 BRE | `Unhandled node type: string` | Rule 3 | 改單引號或 `-E` flag |
| `$(outer "$(inner)")` 反向巢狀 | `Unhandled node type: string` | Rule 4 | 拆兩 call |
| `"${VAR}"` 作為 test 引數 | `Contains expansion`（false positive）| Rule 5 | 加進 allow list |
| `"$VAR"` 作為 test 引數 | `Contains simple_expansion`（false positive）| Rule 5 | 加進 allow list |

## Hook 類別對照

| 錯誤型態 | Hook 訊息 | 根因 |
|---------|-----------|------|
| `$VAR` 在 `$()` 內未加引號 | `simple_expansion` | Rule 1 |
| `"$(cmd "$VAR")"` 雙引號衝突 | `Unhandled node type: string` | Rule 2 |
| `$'...'` ANSI-C 字串 | `ansi_c_string` | 避免使用 ANSI-C 逸出字串語法 |
| `grep "...\|..."` 雙引號 BRE | `Unhandled node type: string` | Rule 3；hook 自動攔截 |
| `$(outer "$(inner)")` 反向巢狀 | `Unhandled node type: string` | Rule 4；hook 自動攔截 |
| `"${VAR}"` 括號形式（已加引號）| `Contains expansion` | Rule 5；**false positive**；加進 allow list |
| `"$VAR"` plain form（已加引號）| `Contains simple_expansion` | Rule 5；**false positive**；加進 allow list |
| `echo "exit:$?"` / `[ $? -ne 0 ]` | `Contains simple_expansion` | Rule 5；`$?` 無論是否在引號內皆攔截；改用 `if ! <cmd>; then` |

## $? 特殊案例（PR #24 教訓）

`$?`（exit status 變數）是 `simple_expansion` AST 節點，Rule 5「不區分是否已加引號」同樣適用：

| 模式 | 觸發？| 正確替代 |
|------|--------|---------|
| `echo "exit:$?"` | 是 | 刪除這行，bash block 已有 `if ! cmd` |
| `echo exit:$?` | 是 | 同上 |
| `[ $? -ne 0 ]` | 是 | `if ! <command>; then` |
| `if ! gemini ...; then` | 否 | 推薦寫法 |

SKILL.md bash block 不要在指令後加任何 `$?` 相關程式碼——用
`if ! <command>; then echo '[FAIL]...'; exit 1; fi` 取代所有 `if [ $? -ne 0 ]` 形式。

## Gemini CLI workspace sandbox（PR #24 教訓）

Gemini CLI 的 `@<path>` 引用受 workspace sandbox 限制，只允許 git worktree 目錄內的路徑。

```bash
# 違規：/tmp 不在 Gemini workspace
gemini -m model -p "@/tmp/pr-review/wt-name/input.md"

# 修法：把 input 放進 worktree，用相對路徑（worktree 刪除時自動清理）
cp /tmp/pr-review/wt-name/input.md "$WT_ROOT/gemini-input.md"
gemini -m model -p "@gemini-input.md"
rm -f "$WT_ROOT/gemini-input.md"
```

不要用 `~/.gemini/tmp/`——需要額外手動 rm，且跨 session 可能殘留。

## Quoting Rule 6：inline Python comment 含 `"` 截斷外層 shell double-quote（PR #23 教訓）

`python3 -c "..."` 的 shell 字串是外層雙引號包住的。**即使是 Python comment（`#`），
其中出現的 `"` 仍會被 bash parser 視為雙引號的閉合**，提前終止外層字串，造成 Python 程式碼被截斷，
regex 或其他邏輯靜默失效（無錯誤訊息）。

```bash
# 違規：comment 內含 " 截斷外層 shell string
python3 -c "
import re, sys
# Known Limitation: user.name="foo | bar" -- quoted pipe breaks match
ptn = r'\bcommit\b'
re.search(ptn, sys.stdin.read())
"
# bash 在 "foo | bar" 的 " 處截斷，python3 收到的是殘破 code

# 修法 A：comment 內不用雙引號，改用中文全形引號或刪除引號
# Known Limitation: user.name=foo|bar -- quoted pipe breaks match

# 修法 B：把 inline python 移到獨立 .py 檔案（根治方案）
python3 scripts/check_pattern.py
```

判斷準則：**在 bash `"..."` 字串內寫任何語言的 comment，一律避免 `"`**；若需要引號，
改用單引號 `'`（bash double-quote 內的 `'` 是 literal，不閉合 outer string）。

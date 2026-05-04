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

## Quoting Rule 2：同型引號衝突

`echo "...: $(cmd "$VAR")"` — 外層雙引號 → `$()` → 再度雙引號，
Claude Code hook 的靜態分析器無法處理此巢狀結構，回報 `Unhandled node type: string`。

```bash
# 違規：雙引號嵌套衝突
echo "Main updated to: $(git -C "$MAIN_REPO" rev-parse --short HEAD)"

# 修法 A（最優先）：拆成獨立 bash call
git -C "$MAIN_REPO" rev-parse --short HEAD

# 修法 B：用臨時變數隔離
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

## Quoting Rule 5：`"${VAR}"` 括號形式觸發 expansion false positive（Case 24）

`"${VAR}"` 是 bash 推薦的最安全寫法（括號明確界定變數名稱邊界，雙引號防 word-split），
但 Claude Code 內建 parser 廣義攔截所有 `expansion` AST 節點，不區分是否已加引號，
回報 `Contains expansion`。這是 **false positive**——bash 語法正確，攔截來自 parser 設計。

```bash
# 觸發：test -n "${VAR}" 是正確 bash，但 parser 攔截 expansion 節點
test -n "${CODEX_API_KEY}" -o -n "${OPENAI_API_KEY}" && echo "AUTH: KEY_SET" || true

# 修法 A（最優先）：改用 $VAR plain form（不含括號，繞過 expansion 節點偵測）
[ -n "$CODEX_API_KEY" ] && echo "AUTH: CODEX_KEY_SET" || true
[ -n "$OPENAI_API_KEY" ] && echo "AUTH: OPENAI_KEY_SET" || true

# 修法 B：boolean 合併（保留原始 KEY_SET 語意）
{ test -n "$CODEX_API_KEY" || test -n "$OPENAI_API_KEY"; } && echo "AUTH: KEY_SET" || true
```

重要限制：**切勿用 `printenv` 或 `echo $VAR` 印出 key 值**——會將 API key 明文記錄
至 session transcript。確認 key 存在一律用 `test -n`，不用 `echo` 或 `printenv`。

根本原因在 Claude Code 內建 parser 層（非本 repo hook 範圍），無法從 hook 側修正。
v3 backlog：hook 應補強「`expansion` 節點已被 `"..."` 包住則豁免」。

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

注意：`"${VAR}"` 括號形式在 `$(...)` 外作為獨立引數（如 `test -n "${VAR}"`）會觸發 false positive，見 Rule 5。
若變數後緊接前後綴（如 `"${prefix}_suffix"`），改為 `"$VAR"` 會讀到不同變數（`$prefix_suffix`）——此情況不適用 Rule 5 修法，應改寫成 `"${prefix}"_suffix`。

**其他模式快速對照**（Rules 3-5；Rules 1-2 見上方流程圖）：

| 模式 | 觸發訊息 | 規則 | 修法 |
|------|---------|------|------|
| `grep "...\|..."` 雙引號 BRE | `Unhandled node type: string` | Rule 3 | 改單引號或 `-E` flag |
| `$(outer "$(inner)")` 反向巢狀 | `Unhandled node type: string` | Rule 4 | 拆兩 call |
| `"${VAR}"` 作為 test 引數 | `Contains expansion`（false positive）| Rule 5 | 改 `"$VAR"` plain form |

## Hook 類別對照

| 錯誤型態 | Hook 訊息 | 根因 |
|---------|-----------|------|
| `$VAR` 在 `$()` 內未加引號 | `simple_expansion` | Rule 1 |
| `"$(cmd "$VAR")"` 雙引號衝突 | `Unhandled node type: string` | Rule 2 |
| `$'...'` ANSI-C 字串 | `ansi_c_string` | 避免使用 ANSI-C 逸出字串語法 |
| `grep "...\|..."` 雙引號 BRE | `Unhandled node type: string` | Rule 3；hook 自動攔截 |
| `$(outer "$(inner)")` 反向巢狀 | `Unhandled node type: string` | Rule 4；hook 自動攔截 |
| `"${VAR}"` 括號形式（已加引號）| `Contains expansion` | Rule 5；**false positive**；改用 `"$VAR"` |

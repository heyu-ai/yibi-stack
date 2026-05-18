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

## Anti-Pattern 3：Stateful cd

`cd <path> && cmd` 有三種不同的危害機制，對應不同修法。

### AP3 Sub-class A：CWD 污染（hook 不攔，靜默盲點）

**觸發**：`cd <path> && <非 git 指令>`——cd 改變 session CWD，後續 bash call 全
受影響；tool 的 `--directory` 選項可完全迴避。

**案例**：4（alembic upgrade）、17/18（cd + python3 -c async DB query）

```bash
# 違規：cd 污染 CWD，後續執行環境不乾淨
cd /path/to/backend && uv run python3 scripts/check_stats.py

# 修法 A（最優先）：使用工具原生 --directory
uv run --directory /path/to/backend python3 scripts/check_stats.py

# 修法 B：subshell 隔離（不污染外層 CWD）
( cd /path/to/backend && uv run python3 scripts/check_stats.py )
```

常用工具對應修法：

| 工具 | cd 版（違規） | --directory 版（修法） |
|------|------------|----------------------|
| uv run | `cd /p && uv run python3 ...` | `uv run --directory /p python3 ...` |
| pytest | `cd /p && uv run pytest` | `uv run --directory /p pytest` |
| npm | `cd /p && npm test` | `npm --prefix /p test` |

### AP3 Sub-class B：cd-before-git（C 類 hook 嘗試攔）

**觸發**：`cd <path> && git <anything>`——cd 改變 CWD 後執行 git，讓 git
採用非預期的 hooks 路徑；C 類 hook 會嘗試攔截，但不保證每次觸發。

**案例**：7（cd + git status）、9（cd + git commit heredoc）、12（cd + git log）

```bash
# 違規：cd 後執行 git，CWD 決定採用哪個 .git/hooks
cd /path/to/repo && git status

# 修法：git -C 指定工作目錄，不改變 session CWD
git -C /path/to/repo status
git -C /path/to/repo log --oneline -5
git -C /path/to/repo rev-parse --short HEAD
```

### AP3 Sub-class C：路徑解析隱藏（F1 類 hook 嘗試攔）

**觸發**：`cd <path> && <command> ... 2>/dev/null`——cd 讓相對路徑解析依賴
CWD，加上 `2>/dev/null` 吞掉錯誤訊息，導致路徑問題靜默失敗。
F1 hook 偵測「compound command 含 cd 且有 output redirection」。

**案例**：10（cd + find + 2>/dev/null）、11（cd + grep + 2>/dev/null）、
15（cd + gh pr view + 2>/dev/null）

```bash
# 違規：cd 改變路徑基準，2>/dev/null 掩蓋找不到路徑的錯誤
cd /path/to/project && find . -name "*.py" 2>/dev/null

# 修法 A：改用絕對路徑，保留錯誤輸出
find /path/to/project -name "*.py"

# 修法 B：改用 Read/Grep tool（Claude 工具層），直接以絕對路徑操作
# Glob: /path/to/project/**/*.py
```

### AP3 全覽

| 子類 | hook 攔截 | 案例 | 修法 |
|------|----------|------|------|
| A: CWD 污染 | 無（靜默盲點） | 4/17/18 | `--directory` flag 或 subshell |
| B: cd-before-git | C 類（部分） | 7/9/12 | `git -C <path>` |
| C: 路徑解析隱藏 | F1 類（部分） | 10/11/15 | 絕對路徑 / Read/Grep tool |

## 優先使用 Claude 內建工具搜尋程式碼

搜尋程式碼時，**優先用 Grep/Glob tool，不要用 bash `rg`/`grep`/`find`**。

常見違規模式：`cd $(git rev-parse --show-toplevel) && rg ... 2>/dev/null | head -10`
同時觸發 AP3-A（CWD 污染）、AP3-C（`2>/dev/null` 路徑隱藏）、AP1（output filter `| head`），
且 `$()` subshell 結構會觸發 Claude Code 內建 parser 的確認對話框。

| bash（違規） | Claude Tool（修法） |
|------|------|
| `cd $(...) && rg -n 'pattern' path/ --type dart 2>/dev/null` | Grep `pattern` in `path/` include `*.dart` |
| `cd $(...) && find path/ -name '*auth*.dart' \| head -10` | Glob `path/**/*auth*.dart` |
| `cd $(...) && rg -rn 'class.*User' path/ --type py 2>/dev/null` | Grep `class.*User` in `path/` include `*.py` |

Claude 內建工具的優勢：零 CWD 依賴、零 PreToolUse hook 觸發、無需手動 `| head` 截斷。

**注意**：Grep/Glob tool 在大型 codebase 有結果上限截斷（不會回報「還有 N 筆未顯示」）。
需要完整結果清單時（如全域 rename、migration audit），改用 `rg -l` 或 `find` 搭配絕對路徑，
再逐檔用 Read tool 確認。Grep tool 預設遵守 `.gitignore`；若需搜尋被 ignore 的檔案（如 `build/`、`vendor/`），
仍需用 bash `rg --no-ignore`。

**適用範圍**：純粹為了「找程式碼在哪」「搜尋 pattern」的場景。
需要 bash 特有功能（如 `rg --json`、`find -exec`、`find -path`、`wc -l` 統計）時仍用 bash，但須遵守上述 AP 規則。

## 寫 bash 前的 5 秒自我檢查

- [ ] 有換行 / heredoc / `\` 續行嗎？
- [ ] 引號超過兩層嵌套嗎？
- [ ] 內嵌 Python / Node / 複雜 jq 嗎？
- [ ] 有多層 if/elif/case 嗎？
- [ ] 有複雜參數展開 `${var//pat/rep}` / 間接引用 `${!var}` 嗎？

以上 >=2 項 yes → 拆 bash call / 寫獨立 script / 換工具（sed / realpath / 簡單 jq）

- [ ] 字串內有 emoji / em dash（—）/ en dash（–）/ 零寬空白嗎？

yes → 依 Anti-Pattern 2 對照表替換（獨立規則，不計入上方門檻）

- [ ] 指令含 `cd <path> &&` 嗎？

yes → 判斷子類：git 指令改 `git -C`；非 git 改 `--directory`；有 2>/dev/null 改絕對路徑。詳見 Anti-Pattern 3。

- [ ] 這是純搜尋嗎？（找 pattern / 列檔案）

yes → 優先用 Grep/Glob tool，詳見「優先使用 Claude 內建工具搜尋程式碼」。

## AP2 自動攔截

`.claude/hooks/bash-ap2-check.py` 是 PreToolUse hook，自動偵測並攔截 AP2 違規。
攔截範圍：em dash / en dash / 零寬空白 / U+2300-U+23FF / U+2600-U+27BF / U+1F000-U+1FAFF。
（U+2400-U+25FF Box Drawing 等刻意排除，避免 tree/eza 輸出誤攔。）

AP1 複雜度判斷多數需要推理，仍需靠 5 秒自我檢查。例外：以下機械可判定子類有自動 hook 覆蓋（`bash-ap1-inline-check.sh`）：

- `python -c` 多行、`osascript` heredoc（已覆蓋）
- `grep "...\|..."` 雙引號 BRE alternation（Case 25，已覆蓋）
- `$(outer "$(inner)")` 反向巢狀 subshell（Case 26，已覆蓋）

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

### `cd /abs/path && cmd`（Stateful cd）

`cd` 有三種危害子類，詳見 Anti-Pattern 3。速查對應：

- `cd ... && git <cmd>` → `git -C <path> <cmd>`（Sub-class B）
- `cd ... && uv run` → `uv run --directory <path>`（Sub-class A）
- `cd ... && cmd 2>/dev/null` → 改絕對路徑，移除 cd（Sub-class C）

### `cat <<'EOF' | command`（heredoc-pipe）

`cat <<'EOF' | cmd` 的 pipeline AST 節點超出 parser 能力，觸發
`Unhandled node type: pipeline`（Case 23）。即使 AP1 score 僅 1/5，仍必攔。

```bash
# 違規：heredoc 直接接管線，parser 在 pipeline 節點失敗
cat << 'ARTIFACT_EOF' | spectra new artifact --stdin
## content ...
ARTIFACT_EOF

# 修法：用 Write tool 先寫檔（固定路徑，Write 與 shell 使用同一路徑），再用 < redirect
spectra new artifact --stdin < /tmp/artifact_input.md
rm -f /tmp/artifact_input.md
```

### output filter pipeline `| grep -v "..."`

```bash
# 違規：用 bash pre-filter 替代 Claude 判讀輸出
cmd 2>&1 | grep -v "INFO"

# 修法：移除 grep filter，Claude 直接接收完整輸出
cmd 2>&1
```

## AP1 自動修復觸發條件

當你發現自己即將寫的 bash 符合下列任一情況，**停下來呼叫 `bash-to-script` subagent**，
請它把 bash 邏輯抽出成 `scripts/` 下的獨立 script 檔案：

1. `for` loop body 含 pipe 或 `if`（Cases 21/22）
2. heredoc 後接 `| command`（Case 23）
3. inline `python -c` 含換行（hook 已攔，但 subagent 可直接生成 `.py`）
4. inline `osascript` heredoc（同上）

呼叫範例：

```text
任務：我需要把這段 bash 抽出成 script，目的是掃描多個檔案的 EdgeInsets pattern。
bash 內容：
  for f in a.dart b.dart; do
    grep -n "EdgeInsets" "$f" | grep -v "YibiSpacing"
  done
```

subagent 會：

- 讀取 `scripts/` 現有命名慣例
- 決定檔名（如 `scripts/scan_bare_edgeinsets.sh`）
- 寫入乾淨 script（有 shebang、set -euo pipefail、無 AP1 違規）
- 回報 `CREATED: scripts/xxx.sh` 和 `INVOKE: bash scripts/xxx.sh`

**不適用**：Cases 25/26（引號修法）、Cases 20/23（拆 bash call 即可）。
這些 cases 不需要 subagent，只需按對應修法調整指令。

## exec wrapper 穿透 deny rule（2026-05）

Claude Code deny rule 現在可穿透 `env` / `sudo` / `watch` / `ionice` / `setsid`：

```bash
# 這類寫法也會被 deny rule 攔截
sudo rm -rf /dangerous/path
env DANGEROUS_VAR=1 bash script.sh
```

不要以為用 wrapper 就能繞過 deny rule。
被攔截時，依 Rule 15 標準行為：說明操作內容，請使用者手動執行。

## trap ERR rollback（外部 skill 合約限制下的失敗保護）

外部 skill script（如 `bump-version/scripts/bump.sh`）之間有**步驟執行合約**：
後置 script 常讀取前置 script 寫入的狀態（如 `/tmp/bump_version_result.env`），
步驟排序不可任意調整。當「在 file mutation 之前先跑測試」的需求與合約衝突時，
正確解不是強行重排，而是用 `trap ERR` 在失敗時自動還原已修改的檔案：

```bash
rollback() {
    echo "[WARN] Release failed -- reverting version files" >&2
    git checkout -- pyproject.toml CHANGELOG.md 2>/dev/null || true
    git checkout -- 'plugins/*/package.json' 2>/dev/null || true
}
trap rollback ERR

# ... file mutation steps (bump, sync, changelog) ...

# gates.sh 依賴 bump.sh 的 env file，必須在 bump 後執行
"$GATES_SH"

trap - ERR   # commit 前清除 trap，避免 commit 後的失敗誤觸 rollback
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): v${TAG_VERSION}"
```

注意事項：

- `trap - ERR` 必須在 commit **之前**清除，commit 後的失敗需要不同的回復語意（`git reset HEAD~1`）
- `git checkout -- 'plugins/*/package.json'` 的 glob 必須用單引號（shell glob 展開時機問題）
- 若某步驟本身已有 `trap`，注意不要覆蓋外層的 `trap ERR`（用 subshell 隔離）

## 完整方法論

跨專案完整版見 skill `bash-anti-patterns`（含 before/after 範例、agent 自檢 checklist、
技術背景、可選裝 PreToolUse hook）。

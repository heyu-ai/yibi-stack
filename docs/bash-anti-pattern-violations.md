# Bash Anti-Pattern 違規清單（待修）

由 PR 建立 `bash-anti-patterns` skill 時同步掃描產出（2026-05-03）。
違規清單修復完成後，上方各條目逐一刪除；底部「Hook 攔截案例分析」節永久保留（規則 14、15 已於 2026-05-04 v2 正式建立）。

## 違規類型說明

- **U**：bash 指令字串內含 emoji / em dash / en dash（Anti-Pattern 2）
  - 修法：改用 `[SKIP]` / `[OK]` / `[WARN]` / `[FAIL]` / `[GO]` / `--` / `-`
  - **注意**：hook 掃描的是 raw `.tool_input.command` 字串，不解析 shell 語法。
    因此 `python3 -c "print('⚠️ message')"` 裡的 emoji 也會被攔截，
    即使它在 Python 字串而非 bash 字串內。所有 command 中可見的 emoji 都需修。
- **C**：過度複雜的單一指令（Anti-Pattern 1，complexity score >= 2）
  - 修法：拆成多個 bash call / 寫獨立 script / 換工具（jq / realpath）

---

## 真陽性清單

### commands/newjob.md

**Anti-Pattern 2（bash echo 含 emoji）：**

| 行號 | 原始內容 | 修法 |
|------|---------|------|
| L56 | `echo "⚠️ DANGER: branch 追蹤 origin/main，修正中..."` | `echo "[WARN] DANGER: branch 追蹤 origin/main，修正中..."` |
| L109 | `&& echo "  ⏭ 無 docker-compose 檔案，跳過 port 衝突預防"` | `&& echo "  [SKIP] 無 docker-compose 檔案，跳過 port 衝突預防"` |
| L115 | `{ echo "  ⚠ port registry init 失敗 — 跳過 port 衝突預防"; exit 0; }` | `{ echo "  [WARN] port registry init 失敗 -- 跳過 port 衝突預防"; exit 0; }` |
| L159 | `echo "  ⏭ Step 3b 全域版本跳過（docker compose 由專案層級 newjob.md 負責）"` | `echo "  [SKIP] Step 3b 全域版本跳過（docker compose 由專案層級 newjob.md 負責）"` |
| L168 | `echo "  ⏭ 無 docker-compose 檔案，跳過"` | `echo "  [SKIP] 無 docker-compose 檔案，跳過"` |
| L181 | `echo "  ⚠ migration 失敗，請手動確認"` | `echo "  [WARN] migration 失敗，請手動確認"` |
| L183 | `echo "  ⏭ 無 migration 設定，跳過"` | `echo "  [SKIP] 無 migration 設定，跳過"` |
| L197 | `echo "  ⏭ 無可測試的專案，跳過"` | `echo "  [SKIP] 無可測試的專案，跳過"` |
| L210 | `echo "  ⏭ 無 Python 專案，跳過 lint"` | `echo "  [SKIP] 無 Python 專案，跳過 lint"` |

**Anti-Pattern 1（Step 3d/3e/3f complexity）：**

| 行號範圍 | 症狀 | Complexity Score |
|---------|------|-----------------|
| L188-197 | 技術棧偵測 if/elif + 多重 OR 條件（`pyproject.toml \|\| backend/pyproject.toml`）| 2（多層 if/elif + 複雜條件）|
| L204-210 | lint 偵測同模式，if + OR 多條件 | 2（多層 if + 複雜條件）|

修法：考慮拆成各技術棧獨立偵測邏輯，或抽出 `detect_stack()` 函式到獨立 script。

---

### commands/clean-gone.md

**Anti-Pattern 2（bash echo 含 emoji）：**

| 行號 | 原始內容 | 修法 |
|------|---------|------|
| L52 | `echo "  ⚠ 不在 git repo 內 — 跳過 port cleanup for $branch"` | `echo "  [WARN] 不在 git repo 內 -- 跳過 port cleanup for $branch"` |
| L63 | `echo "  ⚠ uv 不可用 — 跳過 port cleanup for $branch"` | `echo "  [WARN] uv 不可用 -- 跳過 port cleanup for $branch"` |

---

### commands/clean-merged.md

**Anti-Pattern 2（bash echo 含 emoji）：**

| 行號 | 原始內容 | 修法 |
|------|---------|------|
| L44 | `echo "  ⚠ 不在 git repo 內 — 跳過 port cleanup for $branch"` | `echo "  [WARN] 不在 git repo 內 -- 跳過 port cleanup for $branch"` |
| L55 | `echo "  ⚠ uv 不可用 — 跳過 port cleanup for $branch"` | `echo "  [WARN] uv 不可用 -- 跳過 port cleanup for $branch"` |

---

### commands/handover.md

> 注意：fix/handover-commands-jq-refactor 已將 python3 inline 改為 jq，但尚未 merge 到 main。
> 本清單基於 main 分支狀態。

**Anti-Pattern 1（inline python3 `SKILL_REPO=$(python3 -c "...")`）：**

| 行號 | 症狀 | Complexity Score |
|------|------|-----------------|
| L10 | `SKILL_REPO=$(python3 -c "import json, sys; ...")` | 2（內嵌其他語言 + 巢狀引號）|
| L43 | 同上 | 2 |
| L80 | 同上 | 2 |

**修法**：merge fix/handover-commands-jq-refactor 即可解決。

**Anti-Pattern 2（bash echo 含 emoji）：**

| 行號 | 原始內容 | 修法 |
|------|---------|------|
| L9 | `echo "⚠️  DB 不存在，請先跑 uv run..."` | `echo "[WARN] DB 不存在，請先跑 uv run..."` |
| L22 | `echo "⚠️  skill_repo 未設定..."` | `echo "[WARN] skill_repo 未設定..."` |
| L55 | 同上重複 | 同上 |
| L92 | 同上重複 | 同上 |

---

### commands/handover-back.md

**Anti-Pattern 1（inline python3）：**

| 行號 | 症狀 | Complexity Score |
|------|------|-----------------|
| L10 | `SKILL_REPO=$(python3 -c "import json, sys; ...")` | 2 |
| L36 | 同上 | 2 |

**修法**：merge fix/handover-commands-jq-refactor 即可解決。

**Anti-Pattern 2（bash echo 含 emoji）：**

| 行號 | 原始內容 | 修法 |
|------|---------|------|
| L22 | `echo "⚠️  skill_repo 未設定..."` | `echo "[WARN] skill_repo 未設定..."` |
| L48 | 同上重複 | 同上 |

---

### Makefile

**Anti-Pattern 2（echo 含 emoji）：**

| 行號 | 原始內容 | 修法 |
|------|---------|------|
| L37 | `@echo "✅ 本地 CI 項目通過（pre-commit + tests）"` | `@echo "[OK] 本地 CI 項目通過（pre-commit + tests）"` |
| L89 | `echo "  ⚠ $$name → relinked (was dangling)";` | `echo "  [WARN] $$name -> relinked (was dangling)";` |
| L93 | `echo "  ⚠ $$name (exists as real file, skipping)";` | `echo "  [WARN] $$name (exists as real file, skipping)";` |

---

## 假陽性已審清單（不需修）

下列 rg 匹配確認屬假陽性，後續 scan 可忽略：

| 檔案 | 行號 | 說明 |
|------|------|------|
| commands/newjob.md | L45 | `### 2a. ⚠️ Push 安全驗證` — H3 heading markdown，非 bash 指令 |
| commands/newjob.md | L135 | em dash 在 markdown prose 段落 |
| commands/newjob.md | L231-237 | ` ```text ` block（Go/No-Go 輸出範本），非 bash 執行 |
| commands/clean-gone.md | L92-95 | ✅ 在 markdown prose bullet list |
| commands/clean-merged.md | L77-81 | ✅ ⚠️ 在 markdown prose bullet list |
| .claude/rules/12-auto-handover.md | L15 | ⚠️ 在 ` ```text ` block，非 bash |
| .claude/rules/13-bash-anti-patterns.md | 多處 | 本規範文件，em dash / emoji 是說明文字 |
| .claude/rules/*.md | em dash 行 | Markdown 文件中的 em dash 是 prose，非 bash |
| commands/handover.md | L14,L19 | ⚠️ 在 Python `print()` 字串（hook 已修正為 jq 版本，原違規已消失） |
| commands/handover-back.md | L14,L19 | 同上 |

---

## 建議 Fix PR 執行順序

1. **先 merge fix/handover-commands-jq-refactor** → 解決 handover.md/handover-back.md 的 Anti-Pattern 1
2. **修 commands/newjob.md** → U 類 9 處，C 類 2 處（Step 3d/3e）
3. **修 commands/clean-gone.md + commands/clean-merged.md** → U 類各 2 處
4. **修 Makefile** → U 類 3 處
5. **修 commands/handover.md + handover-back.md** → U 類若未被 step 1 解決的部分

每個 fix PR 完成後，刪除本清單對應條目。違規清單全清空後，刪除上方所有段落；底部 Hook 攔截案例分析節仍保留，待規則 14、15 建立後再刪除本檔。

---

## Hook 攔截案例分析（v2 規則素材）

記錄 2026-05-03 對話中分析的攔截案例，作為 v2 規則演化素材。
**這一節與上方違規清單獨立，不隨 fix PR 刪除。**

### 案例分類體系

| 類別 | 說明 |
|------|------|
| A | 純權限提示 |
| B | "Newline followed by #..." -- command injection |
| C | "changes directory before running git" -- cd-before-git |
| D | "Unhandled node type: string" / "Unhandled node type: pipeline" -- parser 失敗 |
| E | "Contains simple_expansion" / "Contains ansi_c_string" / "Contains expansion" -- quoting hygiene |
| E2 | "Contains brace with quote character (expansion obfuscation)" -- E 變體，`{}` 與 `"` 同層出現（見 Case 16） |
| F1 | "Compound command contains cd with output redirection" -- path resolution bypass |
| N/A | hook 未觸發 / 無對應訊息類別（含：正面教材案例、靜默盲點） |

### 全案例快速索引

v2 規則欄標記「13 AP3」「14」「15」為 **v2 已建立規則**（2026-05-04）。「否」表示 v1 既有機制已覆蓋，不需要新 rule。

| Case | 指令摘要 | 類別 | 違反 AP | AP1 Score /5 | 根因 | v2 規則（已建立） |
|------|---------|------|---------|-------|------|---------|
| 1 | codex prereq | N/A（正面教材） | AP1+AP2 正例 | N/A | 2+5 | 否 |
| 2 | sync deps | N/A（靜默盲點） | 未攔 | N/A | N/A | 15 |
| 3 | docker compose | E（simple_expansion） | 未直接違反 | N/A | 5 | 14 |
| 4 | alembic cd | A（盲點） | 未攔 | 1/5 | 3 延伸+6 新 | 13 AP3+15 |
| 5 | pre-commit hooks | D | AP1+AP2 | 2/5 | 2+5 | 否 |
| 6 | python3 inline regex | B | AP1 | 3/5 | 2 | 否 |
| 7 | cd + git status | C | 未違反 | 0/5 | 3 | 13 AP3+git-C |
| 8 | echo ANSI-C quoting | E（ansi_c_string） | AP1 | 2/5 | 2+6 | 14+根因 6 |
| 9 | cd + git commit（heredoc） | C | 未違反 | 1/5 | 3（冗餘） | 13 AP3+heredoc 豁免（v2 提案） |
| 10 | cd + find + 2>/dev/null | F1 | 未違反 | 0/5 | 7 新 | 13 AP3 子類 |
| 11 | cd + grep + 2>/dev/null | F1 | 未違反 | 0/5 | 7+tool-selection | 13 AP3 預防 |
| 12 | cd + git log + 2>/dev/null | C | 未違反 | 0/5 | 3 | hook 條件邊界 |
| 13 | gh pr merge + RESULT 驗證 | D | AP1 | 2/5 | 2 | 否 |
| 14 | Codex prereq 兩層 if + `${:-}` | D | AP1+AP2 | 2/5 | 2+5 | 否 |
| 15 | cd + gh pr view + 2>/dev/null（worktree） | F1 | 未違反 | 0/5 | 7 | 13 AP3 子類 |
| 16 | osascript heredoc AppleScript（窗口列舉） | E2（expansion obfuscation） | AP1 | 2/5 | 2 | 13 新增：heredoc 豁免邊界確認 |
| 17 | cd + python3 -c 三層引號 async DB query | B | AP1 | 4/5 | 2+3+6 | 13 AP3+15 |
| 18 | cd + PYTHONPATH + python3 -c async + pipe grep | B | AP1 | 3/5 | 2+3+6 | 13 AP3+output-filter |
| 19 | docker-compose 位置偵測 + docker compose up | E（simple_expansion） | AP1 | 2/5 | 2+6（unquoted subshell var） | 14 |
| 20 | git -C fetch + pull + echo nested subshell | D | AP1 | 2/5 | 2+6（同型引號衝突） | 14 |
| 21 | for-loop grep EdgeInsets（5 files） | D | AP1 | 1/5* | 2（for-loop-file-list sub-type：body 含 pipe） | 新型 |
| 22 | for-loop grep EdgeInsets（13 files）+ if | D | AP1 | 2/5 | 2（for-loop-file-list + if/elif） | 新型 |
| 23 | cat heredoc pipe to spectra CLI | D（pipeline）| 未直接違反 | 1/5 | 8（heredoc-pipe 節點）| D 類新子類 |
| 24 | test -n "${VAR}" -o ... && echo | E（expansion）| 未直接違反（false positive）| 0/5 | 9（hook 廣義攔截 expansion 節點）| E 類第三子類 |
| 25 | MAIN_REPO=... + grep "...\|..." 雙引號 alternation（兩個 variant） | D | AP1 | 1/5 | 10（`\|` 在雙引號 string 內，新根因） | D 類新子類 |
| 26 | `$(dirname "$(git rev-parse ...)")` + if-while + `$PM` 變數命令 | D | AP1 | 3/5 | 2+6（`$(outer "$(inner)")` 反向巢狀引號衝突） | D 類 Case 20 反向變體 |

---

### 根因編號

| 根因 | 說明 |
|------|------|
| 1 | permissions 嚴格 |
| 2 | 指令複雜度（AP1 核心） |
| 3 | cd-before-command 習慣 |
| 5 | Unicode 字元（AP2 核心） |
| 6 | 測試資料 / 邏輯內嵌 bash 字串 |
| 7 | cd + 2>/dev/null 組合（F1 核心） |
| 8 | heredoc-pipe 結構：`cat <<'EOF' \| cmd` 的 pipeline 節點超出 parser 能力 |
| 9 | hook 廣義攔截 `expansion` AST 節點：`${VAR}` 有括號形式即使已加引號仍觸發，為 false positive |
| 10 | 雙引號 grep pattern 內的反斜線-pipe：bash 雙引號合法逸出目標不含 pipe，靜態分析器遇到此 string node 即放棄，回報 `Unhandled node type: string` |

---

### v2 規則對照表（已落地）

以下規則均已於 2026-05-04 建立，左欄為實際規則檔名稱。

| 規則（擬議） | 素材來源 | 核心內容 |
|------|---------|---------|
| 13 AP3（stateful cd） | Cases 4、7、9-12 | cd 三子類：CWD 污染 / git hook / 路徑解析隱藏 |
| 13 新增：`git -C` 修法 | Cases 7、12 | cd-before-git 標準修法 = `git -C <path>` |
| 13 新增：heredoc 豁免 | Case 9 | `$(cat <<'EOF'...EOF)` 用於 commit message 時，不計入多行複雜度 |
| 13 新增：heredoc 豁免邊界 | Case 16 | osascript/DSL heredoc **不豁免**；豁免僅適用純文字 commit message heredoc |
| 13 新增：tool-selection 預防 | Cases 10、11 | cd + grep/find 改用 Read/Grep tool + 絕對路徑 |
| 13 AP3（stateful cd）擴充 | Cases 17、18 | cd + inline Python → CWD 污染子類；修法：`uv run --directory` 取代 cd |
| 14-shell-quoting-hygiene.md | Cases 3、8、16、19、20 | E/E2 類（simple_expansion、ansi_c_string、brace+quote）的修法；`$()` 內 `"$VAR"` 必加引號；同型引號衝突修法 |
| 15-irreversible-operations.md | Cases 2、4、17、18 | 不可逆操作防護（DB query 失控、inline 邏輯 silent fail） |
| B 類：inline Python comment injection | Cases 17、18 | `# comment` 在 python3 -c "..." 的換行後觸發 B 類 hook；根本修法是提取 script 檔案 |
| AP1 新增：for-loop-file-list | Cases 21、22 | `for f in ... \; do` + 複雜 body 一律寫獨立 script；for + if + pipe 三層是最強 AP1 訊號 |
| D 類新子類：heredoc-pipe | Case 23 | `cat <<'EOF' \| command` 觸發 `Unhandled node type: pipeline`；修法：Write tool 寫檔 + `< file` redirect（不含管線） |
| E 類第三子類：expansion | Case 24 | `"${VAR}"` 已正確引號仍觸發 `Contains expansion`；hook 不區分裸露 vs 已引號的 expansion 節點；修法：改用 `"$VAR"` 或 boolean check |
| D 類新子類：`\|` 在雙引號 grep pattern | Case 25 | `grep "pat1\|pat2"` — `\|` 在雙引號內讓 parser 無法分類 string node；修法：改用單引號或 `-E` flag |
| D 類 Case 20 反向變體：`$(outer "$(inner)")` | Case 26 | `$(dirname "$(git ...)")` — 外層 `$()` 包雙引號包內層 `$()`；修法：拆成兩個獨立 bash call |

---

### cd 風險三分類（Cases 4-12 累積）

| 子類 | 觸發 Hook | 案例 | 修法 |
|------|----------|------|------|
| CWD 污染 | 無（盲點） | 4 | 工具原生 `--directory` / subshell |
| 不可信 git hooks | C | 7、9、12 | `git -C <path>` |
| 路徑解析隱藏 | F1 | 10、11、15 | 絕對路徑，移除 cd；或改用 Read/Grep tool |

---

### C 與 F1 hook 觸發條件邊界（Cases 10-12 揭露）

- `cd + git + anything` → **C**（cd-before-git hook）
- `cd + 非 git + 2>/dev/null` → **F1**（path resolution bypass hook）
- `cd + 非 git（無 redirection）` → **未攔**（盲點，見 Case 4）

兩個 hook 條件互斥，不是優先序問題。

---

### Case 13 詳細分析：gh pr merge + RESULT 驗證 pipeline

**指令**：

```bash
gh pr merge 298 --squash --delete-branch
RESULT=$(gh pr view 298 --json state,mergeCommit -q '{state: .state, url: .mergeCommit.url}')
echo "$RESULT"
echo "$RESULT" | grep -q '"state":"MERGED"' || echo "MERGE_FAILED"
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | D（"Unhandled node type: string" — parser 失敗） |
| 違反 Anti-Pattern | AP1 |
| Complexity score | 2/5（多行：4 行跨行狀態依賴；巢狀引號：`grep -q '"state":"MERGED"'`） |
| 根因 | 根因 2：「操作 + 驗證」合一，兩件事被強行塞進一個 bash call |
| Hook 可攔 | 是（D 類） |
| 教材價值 | 中 |
| 規則盲點 | 否 |

**核心反模式**：`RESULT=$(cmd) ... grep "..." || echo "FAILED"` 是 run-and-check pattern，但驗證邏輯應由 Claude 判讀下一個 bash call 的輸出，不需在 bash 裡自己 grep。

**修法**：

```bash
# bash call 1：執行 merge
gh pr merge 298 --squash --delete-branch
# bash call 2：取得狀態（Claude 判斷輸出）
gh pr view 298 --json state,mergeCommit -q '{state: .state, url: .mergeCommit.url}'
```

---

### Case 16 詳細分析：osascript heredoc AppleScript

**指令**：

```bash
osascript << 'ASCRIPT'
tell application "System Events"
    tell process "Simulator"
        set winList to {}
        repeat with w in every window
            set winList to winList & {name of w & " : " & (position of w as string) & " size " & (size of w as string)}
        end repeat
        return winList
    end tell
end tell
ASCRIPT
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | E2（"Contains brace with quote character (expansion obfuscation)"） |
| 違反 Anti-Pattern | AP1 |
| Complexity score | 2/5（多行：heredoc 多行；內嵌其他語言：AppleScript） |
| 根因 | 根因 2：指令複雜度 |
| Hook 可攔 | 是（E2 類） |
| 教材價值 | 高（澄清 heredoc 豁免邊界） |

**Hook 觸發原因**：heredoc 是 `<<'ASCRIPT'`（單引號，無展開），但 hook 的 raw command scanner 不分析引號語義，直接偵測到 AppleScript 的 `{name of w & "..."}` 模式——大括號內含雙引號字元，觸發 expansion obfuscation 警告。

**與 Case 9（heredoc 豁免）的差異**：

| 比較項 | Case 9（commit message） | Case 16（osascript） |
|--------|--------------------------|----------------------|
| heredoc 用途 | 傳遞純文字（commit message） | 傳遞可執行 DSL（AppleScript） |
| 內容語言 | 無 | AppleScript |
| 應豁免？ | **是**（v2 提案：commit message heredoc 不計多行） | **否**，應提取至獨立檔案 |

**修法**：

```bash
# 提取到獨立 AppleScript 檔案
# scripts/list_simulator_windows.applescript
osascript scripts/list_simulator_windows.applescript
```

---

### Case 17 詳細分析：cd + python3 -c 三層引號 async DB query

**指令**：

```bash
cd /Users/.../backend && \
  uv run python3 -c "
import asyncio
...
    async with AsyncSession(engine) as session:
        result = await session.execute(text('''
            SELECT COUNT(*), ...
        '''))
...
" 2>&1
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | B（"Newline followed by # inside a quoted argument can hide arguments from path validation"） |
| 違反 Anti-Pattern | AP1 |
| Complexity score | 4/5（多行 + 巢狀引號三層 + 內嵌 Python + 反斜線續行） |
| 根因 | 根因 2（指令複雜度）+ 根因 3（cd-before-command）+ 根因 6（查詢邏輯內嵌 bash 字串） |
| Hook 可攔 | 是（B 類） |
| 教材價值 | 高（三層引號的最壞案例） |

**三層引號問題**：

```text
bash "..."          -> 第 1 層
  Python f-string   -> （在 bash 字串內）
    SQL '''...'''   -> 第 2+3 層（Python triple-single-quote）
```

這是目前已記錄中 complexity score 最高的案例之一（4/5）。

**Hook 觸發原因**：`# Check MP3 bitrate and TTS settings` 這行 Python 注釋，位於雙引號內的換行之後，符合「newline followed by # inside a quoted argument」模式，被視為潛在 path validation bypass。

**修法**：

```bash
# 提取為獨立 Python script 檔案，移除 cd 和 inline 邏輯
uv run --directory /Users/.../backend python3 scripts/check_audio_stats.py
```

---

### Case 18 詳細分析：cd + PYTHONPATH + python3 -c async + pipe grep

**指令**：

```bash
cd /Users/.../backend && PYTHONPATH=src uv run python3 -c "
import asyncio
...
        # Check completed jobs and their audio file sizes
        result = await session.execute(text('''
            SELECT gj.id, gj.status, ...
        '''))
        ...
" 2>&1 | grep -v "^2026\|INFO\|BEGIN\|ROLLBACK\|SELECT\|generated"
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | B（同 Case 17） |
| 違反 Anti-Pattern | AP1 |
| Complexity score | 3/5（多行 + 巢狀引號三層 + 內嵌 Python） |
| 根因 | 根因 2 + 根因 3 + 根因 6 |
| Hook 可攔 | 是（B 類） |
| 教材價值 | 中 |

**額外 output-filter pipeline 問題**：

```bash
... 2>&1 | grep -v "^2026\|INFO\|BEGIN\|..."
```

這個 pipe 是為了過濾 SQLAlchemy 的 log 輸出。這個做法有兩個問題：

1. 輸出過濾邏輯內嵌在 bash call 裡（Claude 應直接讀完整輸出再判斷，不需 grep 預過濾）
2. 結合已經複雜的 inline Python，讓整個指令更難理解與維護

**與 Case 17 的差異**：`PYTHONPATH=src` 是 inline 環境變數覆蓋，本身不計分，但代表程式碼的 import path 依賴執行位置，是需要 cd 的真正原因——應透過 `uv run --directory` 或 `uv run` 的 `env` 選項替代。

**修法**：

```bash
# 提取為獨立 script，移除 cd、PYTHONPATH inline 和 output filter
PYTHONPATH=src uv run --directory /Users/.../backend python3 scripts/check_completed_jobs.py
# Claude 直接判讀完整輸出，不需 grep 預過濾
```

---

### Case 19 詳細分析：docker-compose 位置偵測 + docker compose up

**指令**：

```bash
WT=$(git rev-parse --show-toplevel)
ls "$WT/docker-compose.yml" 2>/dev/null || echo "No docker-compose.yml in worktree"
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
echo "Main repo docker-compose: $(ls $MAIN_REPO/docker-compose.yml 2>/dev/null || echo 'not found')"
docker compose -f "$MAIN_REPO/docker-compose.yml" up -d 2>&1 | tail -5
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | E（`simple_expansion`） |
| 違反 Anti-Pattern | AP1 |
| Complexity score | 2/5（多行：5 行狀態依賴；巢狀引號：`echo "$(ls $MAIN_REPO/... \|\| echo 'not found')"` 雙引號內含 `$()` 內含單引號） |
| 根因 | 根因 2（複雜度）＋根因 6（`$MAIN_REPO` 在 `$()` 內未加引號，word-split 風險） |
| Hook 可攔 | 是（E 類） |
| 教材價值 | 高：quoting hygiene 的具體反例 |
| 規則盲點 | 否 |

**核心問題**：`$(ls $MAIN_REPO/docker-compose.yml ...)` 中的 `$MAIN_REPO` 沒有引號，若路徑含空格會 word-split 造成錯誤。hook 的 `simple_expansion` 正是捕捉「subshell 內裸露變數展開」。

**修法**：

```bash
# bash call 1：確認 worktree
git rev-parse --show-toplevel
# bash call 2：取 main repo 路徑
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
# bash call 3：確認檔案存在
ls "${MAIN_REPO}/docker-compose.yml"
# bash call 4：啟動服務
docker compose -f "${MAIN_REPO}/docker-compose.yml" up -d
```

---

### Case 20 詳細分析：git -C fetch + pull + nested echo

**指令**：

```bash
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
echo "Main repo: $MAIN_REPO"
git -C "$MAIN_REPO" fetch origin main
git -C "$MAIN_REPO" checkout main
git -C "$MAIN_REPO" pull origin main
echo "Main updated to: $(git -C "$MAIN_REPO" rev-parse --short HEAD)"
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | D（`Unhandled node type: string` — parser 失敗） |
| 違反 Anti-Pattern | AP1 |
| Complexity score | 2/5（多行：6 行多步操作合一；巢狀引號：`echo "...: $(git -C "$MAIN_REPO" ...)"` 外層雙引號內含 `$()` 內含雙引號） |
| 根因 | 根因 2（複雜度）＋根因 6（同型引號衝突：`$(git -C "$MAIN_REPO" ...)` 在外層雙引號 echo 裡，parser 無法正確分詞） |
| Hook 可攔 | 是（D 類） |
| 教材價值 | 高：`git -C` 是**正確做法**，問題出在 wrapper 複雜度 |
| 規則盲點 | 否 |

**值得注意**：`git -C "$MAIN_REPO"` 本身是 Cases 7/12 建立的標準修法（不用 `cd`）。問題不在 `git -C`，而在於把多步 git 操作加上末尾的 `echo "$(git ...)"` 全塞進同一個 bash call，造成引號衝突讓 parser 失敗。

**修法**：

```bash
# bash call 1-4：各自獨立
git -C "$MAIN_REPO" fetch origin main
git -C "$MAIN_REPO" checkout main
git -C "$MAIN_REPO" pull origin main
# bash call 5：取得 HEAD（Claude 判讀輸出，不需 nested echo）
git -C "$MAIN_REPO" rev-parse --short HEAD
```

---

### Case 21 & 22 詳細分析：for-loop-file-list grep pattern

**Case 21 指令（5 files）**：

```bash
for f in lib/features/onboarding/ui/onboarding_flow.dart \
  lib/features/generate/ui/generation_progress_page.dart \
  lib/features/generate/ui/generate_page.dart \
  lib/features/device/ui/device_control_page.dart \
  lib/features/content/ui/content_page.dart; do
  echo "=== $f ==="
  grep -n "EdgeInsets\.\(all\|symmetric\|only\|fromLTRB\)([^Y]" "$f" | grep -v "YibiSpacing" | head -10
done
```

**Case 22 指令（13 files + if）**：

```bash
for f in lib/.../profile_page.dart \
  ... (13 files); do
  COUNT=$(grep -c "EdgeInsets\.\(all\|symmetric\|only\|fromLTRB\)([^Y]" "$f" 2>/dev/null || echo 0)
  if [ "$COUNT" -gt 0 ]; then
    echo "=== $f ($COUNT) ==="
    grep -n "..." "$f" | grep -v "YibiSpacing"
  fi
done
```

| 分析項目 | Case 21 | Case 22 |
|---------|---------|---------|
| 訊息類別 | D（parser 失敗） | D（parser 失敗） |
| AP1 Criterion 1（`\` 續行） | ✓ | ✓ |
| AP1 Criterion 4（if/elif） | 否 | ✓ |
| for-loop-file-list sub-type（body 含 pipe） | ✓（獨立觸發） | ✓ |
| Complexity score | 1/5* | 2/5 |
| 根因 | 根因 2：for-loop-file-list（body 含 pipe） | 根因 2：for-loop-file-list + if/elif |

**新識別的 sub-type：for-loop-file-list pattern**

`for f in file1 \ file2 \; do ... done` 是一種常見的「想省 bash call 而把 script 擠進一行」的模式。判斷規則：

- for 的 body 超過 1 行 → 寫 script
- for 的 body 含 pipe（`|`）→ 寫 script
- for 的 body 含 if → 寫 script（Case 22：三層 for + if + pipe，無庸置疑）

**修法**（兩個 case 共用）：

```bash
# 寫成獨立 script，再執行
# scripts/scan_bare_edgeinsets.sh
bash scripts/scan_bare_edgeinsets.sh
```

Parser 對 `for ... \; do` + 複雜 body 的樹狀結構處理不穩定，D 類失敗是可預期的。

---

### Case 23 詳細分析：cat heredoc pipe to CLI（`Unhandled node type: pipeline`）

**指令**：

```bash
cat << 'ARTIFACT_EOF' | spectra new artifact proposal --change "child-avatar-preset-spec" --stdin
## Why
...（大量 markdown 內容）...
ARTIFACT_EOF
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | D（`Unhandled node type: pipeline` — **D 類新子類**） |
| 違反 Anti-Pattern | 未直接違反 AP1（score 1/5，低於門檻） |
| Complexity score | 1/5（heredoc 多行：✓；其餘 4 項：否） |
| 根因 | 根因 8：`cat <<'EOF' \| command` 的 pipeline AST 節點超出 parser 能力 |
| Hook 可攔 | 是（D 類） |
| 教材價值 | 高：揭露 D 類有兩種訊息；AP1 score 低於門檻仍可觸發 hook |

**與既有 D 類案例的差異**：

| 案例 | D 類訊息 | 觸發原因 |
|------|---------|---------|
| 5, 13, 17 | `Unhandled node type: string` | 同型引號衝突 / 巢狀引號 |
| 18, 19 | `Unhandled node type: string` | for-loop + `\` + 複雜 body |
| **20（新）** | **`Unhandled node type: pipeline`** | **heredoc 直接接 `\|` 管線** |

與 Case 9 的區別：Case 9 是 `$(cat <<'EOF')` 用於 git commit message（類別 C，heredoc 作為 subshell 引數），本 case 是 `cat <<'EOF' | cmd`（heredoc 直接接管線），parser 在 pipeline 節點層即失敗。

**核心問題**：語意上邏輯非常單純（把文字資料餵給 CLI stdin），但 `heredoc | command` 的管線結構讓 parser 在 AST pipeline 節點就放棄解析。

**修法**：

```bash
# 方案 A（最優先）：用 Write tool 建立唯一暫存檔，再用 redirect（不含管線）
# 注意：用唯一路徑（含 PID）避免多行程競爭或舊內容殘留
spectra new artifact proposal --change "child-avatar-preset-spec" --stdin < /tmp/artifact_proposal_$$.md
# 執行後清除暫存檔
rm -f /tmp/artifact_proposal_$$.md

# 方案 B：分兩個 bash call（先寫檔，再執行）
# bash call 1：寫入唯一暫存檔
cat > /tmp/artifact_proposal_$$.md << 'ARTIFACT_EOF'
...內容...
ARTIFACT_EOF
# bash call 2：執行（不含管線，用 redirect）
spectra new artifact proposal --change "child-avatar-preset-spec" --stdin < /tmp/artifact_proposal_$$.md
rm -f /tmp/artifact_proposal_$$.md
```

**修法核心原則**：`< file` redirect 不產生 pipeline AST 節點，parser 可正常處理。大量文字資料應先寫成檔案再 redirect，不要用 `heredoc | command` 管線。

---

### Case 25 詳細分析：`grep "...\|..."` 雙引號 alternation 觸發 D 類

**Case 25a 指令**：

```bash
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
# Check all possible locations for the parked change files
find "$MAIN_REPO" -maxdepth 5 -name "tasks.md" 2>/dev/null | grep -i "media\|cdn\|delivery" 2>/dev/null
# Check git stash
git stash list 2>/dev/null | head -5
# Check if files might be in git objects
git -C "$MAIN_REPO" log --oneline -3 2>/dev/null
```

**Case 25b 指令**：

```bash
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
git -C "$MAIN_REPO" status --short | grep "media-delivery\|openspec" | head -20
```

| 分析項目 | Case 25a | Case 25b |
|---------|---------|---------|
| 訊息類別 | D（`Unhandled node type: string`） | D（`Unhandled node type: string`） |
| 違反 Anti-Pattern | AP1（score 低於門檻仍觸發） | AP1（score 低於門檻仍觸發） |
| Complexity score | 1/5（多行：4 條指令合一；其餘項目不觸發） | 1/5（兩行；其餘項目不觸發） |
| 根因 | 根因 10：`grep -i "media\|cdn\|delivery"` — `\|` 在雙引號 string 內 | 根因 10：`grep "media-delivery\|openspec"` — 同型 |
| Hook 可攔 | 是（D 類） | 是（D 類） |
| 教學價值 | 高：揭露反斜線-pipe 是獨立 D 類觸發點，AP1 score 低於門檻也觸發 | 同上 |

**觸發根因**：

`grep "pattern1\|pattern2"` 使用 BRE 交替語法。在 bash 雙引號字串中，`\` 只對 `$`、`` ` ``、`"`、`\`、換行有逸出作用；`|` 不在此列，`\|` 中的 `\` 是字面字元。靜態分析器遇到「`\` 接 `|`」這個在雙引號 string 節點中的組合，無法判斷節點型別，直接回報 `Unhandled node type: string`。

**與其他 D 類案例的差異**：

| 案例 | 觸發原因 | 指令結構 |
|------|---------|---------|
| 13、20 | 同型引號衝突（`echo "$(cmd "$VAR")"`) | 多步操作合一 |
| 21、22 | for-loop-file-list + `\` 續行 + 複雜 body | for loop |
| 23 | `cat <<'EOF'` 接管線 pipeline 節點 | heredoc pipe |
| **25（新）** | **`grep "...\|..."` 雙引號 BRE alternation** | **單純 grep** |

Case 25 的重要性：觸發結構比其他 D 類更單純（一個 grep 指令就夠），AP1 score 1/5 遠低於門檻，代表 hook 對 `\|` 有特別敏感的 parser 路徑。

**修法**：

```bash
# 方案 A（最優先）：改用單引號 grep pattern
# BRE 交替：\| 在單引號內是字面字元，grep 正確解讀
grep -i 'media\|cdn\|delivery'

# 方案 B：改用 ERE（-E flag）+ 單引號，pattern 更清晰
grep -Ei 'media|cdn|delivery'

# 方案 C：拆成多個獨立 bash call，Claude 彙整輸出
grep -i 'media'
grep -i 'cdn'
grep -i 'delivery'
```

**Case 25a 修法示範**：

```bash
# bash call 1
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
# bash call 2
find "$MAIN_REPO" -maxdepth 5 -name "tasks.md" 2>/dev/null
# bash call 3（單引號 pattern，避免 \| 觸發 hook）
grep -Ei 'media|cdn|delivery' <上一步找到的檔案路徑>
# bash call 4
git stash list 2>/dev/null | head -5
# bash call 5
git -C "$MAIN_REPO" log --oneline -3
```

**Case 25b 修法示範**：

```bash
# bash call 1
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
# bash call 2（單引號 pattern）
git -C "$MAIN_REPO" status --short | grep -E 'media-delivery|openspec' | head -20
```

---

### Case 26 詳細分析：`$(dirname "$(git ...)")` 反向巢狀引號 + if-while 邏輯

**指令**：

```bash
MAIN_REPO=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
PM="uv run --project $MAIN_REPO python -m tasks.local_port_manager"
branch="feat/newjob-copy-settings-local"
ports=$($PM list -p "$branch" 2>/dev/null | awk 'NR>2 {print $1}')
if [ -n "$ports" ]; then
  echo "$ports" | while read svc; do
    $PM release "$branch" "$svc" && echo "  released port: $branch/$svc" || echo "  failed: $branch/$svc"
  done
else
  echo "  no ports registered for $branch"
fi
git branch -D "$branch"
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | D（`Unhandled node type: string`） |
| 違反 Anti-Pattern | AP1 |
| Complexity score | 3/5（多行 + 巢狀引號 + if/else with while） |
| 根因 | 根因 2（複雜度）＋根因 6（`$(dirname "$(inner)")` 反向同型引號衝突） |
| Hook 可攔 | 部分：巢狀 subshell 行觸發（D 類）；if-while 邏輯段不觸發（需靠 5 秒自我檢查） |
| 教學價值 | 高：Case 20 的反向巢狀結構；揭露 if-while 邏輯不應 inline |

**直接觸發原因**：

```bash
MAIN_REPO=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
```

這是 `$(outer_cmd "$(inner_cmd)")` 結構：外層 `$()` 內含 `dirname`，其引數是雙引號包裹的內層 `$(git rev-parse ...)`。Parser 在外層 `$()` 的 string node 中再遇到 `$()`，觸發 `Unhandled node type: string`。

**與 Case 20 的對比**：

| 比較項 | Case 20 | Case 26（新） |
|--------|---------|-------------|
| 巢狀方向 | `"$(cmd "$VAR")"` — 外層 `"..."` → `$()` → 內層 `"$VAR"` | `$(cmd "$(cmd)")` — 外層 `$()` → `"$(inner)"` |
| 外層是 | 雙引號字串 | subshell |
| 內層是 | 雙引號變數 | 雙引號包裹的 subshell |
| 根本問題 | 同型引號在不同深度出現 | 同上（方向相反） |

**額外問題：if-while 邏輯不應 inline**

```bash
if [ -n "$ports" ]; then
  echo "$ports" | while read svc; do
    $PM release ... && echo ... || echo ...
  done
fi
```

這段「取 list → loop release → 報告成功/失敗」的邏輯應拆成：

1. bash call：取得 ports list，讓 Claude 判斷是否為空
2. bash call（per port）：逐一 release，Claude 判讀每次輸出

**修法**：

```bash
# bash call 1：分兩步拆解巢狀 subshell
git rev-parse --path-format=absolute --git-common-dir
# bash call 2（Claude 取上一步輸出 dirname）
# （Claude 直接計算 dirname，不需 bash call）

# bash call 3：設定變數後取得 port list（Claude 判斷是否為空）
MAIN_REPO=<上步結果>
uv run --project "$MAIN_REPO" python -m tasks.local_port_manager list -p "feat/newjob-copy-settings-local" 2>/dev/null

# bash call 4：若 Claude 判斷有 port，逐一 release（per port，不用 loop）
uv run --project "$MAIN_REPO" python -m tasks.local_port_manager release "feat/newjob-copy-settings-local" "$svc"

# bash call 5：刪除 branch
git branch -D "feat/newjob-copy-settings-local"
```

**核心原則**：`$(dirname "$(git ...)")` 應拆成先取 git 輸出、再 Claude 處理 dirname 計算，或拆成兩個獨立 bash call。「bash 裡的 if-while 判斷結果」應轉為「Claude 判讀 bash call 輸出後決定下一步」。

---

### Case 24 詳細分析：`test -n "${VAR}"` 觸發 expansion（E 類 false positive）

**指令**：

```bash
test -n "${CODEX_API_KEY}" -o -n "${OPENAI_API_KEY}" && echo "AUTH: KEY_SET" || true
```

| 分析項目 | 結果 |
|---------|------|
| 訊息類別 | E（`Contains expansion` — **E 類第三子類**） |
| 違反 Anti-Pattern | 未直接違反（**false positive**） |
| Complexity score | 0/5（全部 5 項均不觸發） |
| 根因 | 根因 9：hook 廣義攔截 `expansion` AST 節點，不區分裸露 vs 已正確引號的形式 |
| Hook 可攔 | 是（E 類） |
| 教材價值 | 高：揭露 E 類第三種訊息；`"${VAR}"` 是正確寫法卻被攔截，代表 hook 有過度偵測問題 |

**E 類三種訊息對照**：

| E 子類 | Hook 訊息 | 觸發原因 | 真陽性？ |
|--------|---------|---------|---------|
| simple_expansion | `Contains simple_expansion` | `$VAR`（無括號）在 `$()` 內未加引號 | 是 |
| ansi_c_string | `Contains ansi_c_string` | `$'...'` ANSI-C 逸出語法 | 是 |
| **expansion（新）** | **`Contains expansion`** | **`${VAR}` 括號形式，即使已加 `"` 仍觸發** | **否（false positive）** |

**為什麼是 false positive**：

`"${CODEX_API_KEY}"` 有括號 + 雙引號，是 bash 推薦的**最安全寫法**——括號明確界定變數名稱邊界，雙引號防止 word-split 與 glob 展開。Rule 1（`simple_expansion`）的問題是「在 `$()` 內的 `$VAR` 未加引號」，本 case 完全不符合。Hook 把 `expansion` 節點廣義攔截，沒有檢查是否已被雙引號包住。

**修法**：

```bash
# 方案 A：改用 $VAR plain form，拆成兩個獨立 check（Claude 判讀輸出）
# 注意：兩個 check 各自有 exit code，用 || true 確保整體 exit 0
[ -n "$CODEX_API_KEY" ] && echo "AUTH: CODEX_KEY_SET" || true
[ -n "$OPENAI_API_KEY" ] && echo "AUTH: OPENAI_KEY_SET" || true

# 方案 B：用 test -n 並合併輸出一行（保留原始 KEY_SET 語意）
{ test -n "$CODEX_API_KEY" || test -n "$OPENAI_API_KEY"; } && echo "AUTH: KEY_SET" || true
```

**修法核心原則**：暫時改用 `"$VAR"`（plain form，不含括號）可繞過 `expansion` 節點觸發。長遠來看，hook 應補強：`expansion` 節點若已被 `"..."` 包住則豁免攔截。**切勿使用 `printenv` 印出 key 值——會將 API key 明文記錄至輸出 log 與 session transcript。**

---

## v3 Backlog

v2（2026-05-04）完成後，以下議題留待 v3 處理。

### v3-1：Case 24 expansion false positive 根本修正（上游）

**問題**：`"${VAR}"` 是正確 bash，但 Claude Code 內建 parser 廣義攔截所有
`expansion` AST 節點，不區分是否已加引號，回報 `Contains expansion`。

**現狀**：rule 14 Rule 5 只能提供 workaround（改用 `"$VAR"` plain form）。

**v3 目標**：向 Claude Code 上游回報此 false positive；或在 `bash-ap1-inline-check.sh`
補強偵測邏輯——`expansion` 節點若前後緊鄰 `"` 字元則豁免攔截。

**阻擋點**：內建 parser 不在本 repo 範圍；hook 側繞道邏輯需謹慎設計避免漏攔。

### v3-2：Rule 15 對應的 deny list 落地

**問題**：rule 15 目前是純文件規則，沒有機械性阻擋。

**v3 目標**：在 `.claude/settings.json` 加入 deny list，對高頻不可逆操作提供
hook 層阻擋（至少涵蓋 `git push --force`、`rm -rf`、`alembic upgrade head`
在 prod 路徑的情況）。

**前置條件**：v2 上線觀察 2 週，確認 deny list 不會誤阻擋正常工作流程。

### v3-3：AP3 Sub-class A（CWD 污染）hook 覆蓋評估

**問題**：`cd <path> && <非 git 指令>`（AP3 Sub-class A）目前無 hook 攔截，
是靜默盲點（Cases 4/17/18）。

**v3 目標**：評估是否值得加一支 hook 偵測「cd 後接非 git 指令」。
需權衡：此模式誤攔率高（`cd` 合法用法很多），純 prompt rule 教學可能已足夠。

**決策點**：觀察 v2 rule 13 AP3 上線後，agent 自我矯正率是否達標；
若仍高頻犯規再考慮 hook。

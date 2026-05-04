# Bash Anti-Pattern 違規清單（待修）

由 PR 建立 `bash-anti-patterns` skill 時同步掃描產出（2026-05-03）。
違規清單修復完成後，上方各條目逐一刪除；底部「Hook 攔截案例分析」節永久保留，待規則 14、15 正式建立後再一併刪除本檔。

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
| D | "Unhandled node type: string" -- parser 失敗 |
| E | "Contains simple_expansion" / "Contains ansi_c_string" -- quoting hygiene |
| F1 | "Compound command contains cd with output redirection" -- path resolution bypass |
| N/A | hook 未觸發 / 無對應訊息類別（含：正面教材案例、靜默盲點） |

### 全案例快速索引

v2 素材欄標記「13 AP3」「14」「15」均為**擬議規則（尚未建立）**，非現有規則檔案。

| Case | 指令摘要 | 類別 | 違反 AP | AP1 Score /5 | 根因 | v2 素材（擬議） |
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
| 16 | docker-compose 位置偵測 + docker compose up | E（simple_expansion） | AP1 | 2/5 | 2+6（unquoted subshell var） | 14 |
| 17 | git -C fetch + pull + echo nested subshell | D | AP1 | 2/5 | 2+6（同型引號衝突） | 14 |
| 18 | for-loop grep EdgeInsets（5 files） | D | AP1 | 1/5* | 2（for-loop-file-list） | 新型 |
| 19 | for-loop grep EdgeInsets（13 files）+ if | D | AP1 | 2/5 | 2（最清晰 AP1 案例） | 新型 |

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

---

### v2 規則候選對照表

以下均為**擬議規則，尚未建立檔案**；左欄名稱僅為未來建檔時的計畫名稱。

| 規則（擬議） | 素材來源 | 核心內容 |
|------|---------|---------|
| 13 AP3（stateful cd） | Cases 4、7、9-12 | cd 三子類：CWD 污染 / git hook / 路徑解析隱藏 |
| 13 新增：`git -C` 修法 | Cases 7、12 | cd-before-git 標準修法 = `git -C <path>` |
| 13 新增：heredoc 豁免 | Case 9 | `$(cat <<'EOF'...EOF)` 用於 commit message 時，不計入多行複雜度 |
| 13 新增：tool-selection 預防 | Cases 10、11 | cd + grep/find 改用 Read/Grep tool + 絕對路徑 |
| 14-shell-quoting-hygiene.md | Cases 3、8、16、17 | E 類（simple_expansion、ansi_c_string）的修法；`$()` 內 `"$VAR"` 必加引號；同型引號衝突修法 |
| 15-irreversible-operations.md | Cases 2、4 | 不可逆操作防護（DB migration、silent fail） |
| AP1 新增：for-loop-file-list | Cases 18、19 | `for f in ... \; do` + 複雜 body 一律寫獨立 script；for + if + pipe 三層是最強 AP1 訊號 |

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

### Case 16 詳細分析：docker-compose 位置偵測 + docker compose up

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
| Complexity score | 2/5（多行：5 行合一；巢狀引號：雙引號內含 `$()` 內含單引號） |
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

### Case 17 詳細分析：git -C fetch + pull + nested echo

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

### Case 18 & 19 詳細分析：for-loop-file-list grep pattern

**Case 18 指令（5 files）**：

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

**Case 19 指令（13 files + if）**：

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

| 分析項目 | Case 18 | Case 19 |
|---------|---------|---------|
| 訊息類別 | D（parser 失敗） | D（parser 失敗） |
| AP1 Criterion 1（`\` 續行） | ✓ | ✓ |
| AP1 Criterion 4（if/elif） | 否 | ✓ |
| Complexity score | 1/5（但 for-loop-file-list sub-type 獨立觸發改寫） | 2/5 |
| 根因 | 根因 2：for-loop-file-list（body 含 pipe） | 根因 2：for-loop-file-list + if |

**新識別的 sub-type：for-loop-file-list pattern**

`for f in file1 \ file2 \; do ... done` 是一種常見的「想省 bash call 而把 script 擠進一行」的模式。判斷規則：

- for 的 body 超過 1 行 → 寫 script
- for 的 body 含 pipe（`|`）→ 寫 script
- for 的 body 含 if → 寫 script（Case 19：三層 for + if + pipe，無庸置疑）

**修法**（兩個 case 共用）：

```bash
# 寫成獨立 script，再執行
# scripts/scan_bare_edgeinsets.sh
bash scripts/scan_bare_edgeinsets.sh
```

Parser 對 `for ... \; do` + 複雜 body 的樹狀結構處理不穩定，D 類失敗是可預期的。

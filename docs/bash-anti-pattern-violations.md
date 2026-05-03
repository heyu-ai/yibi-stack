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
| 14-shell-quoting-hygiene.md | Cases 3、8 | E 類（simple_expansion、ansi_c_string）的修法與 `$'...'` 提取原則 |
| 15-irreversible-operations.md | Cases 2、4 | 不可逆操作防護（DB migration、silent fail） |

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

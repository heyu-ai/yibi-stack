# Bash Anti-Pattern 違規清單（待修）

由 PR 建立 `bash-anti-patterns` skill 時同步掃描產出（2026-05-03）。
修復 PR 完成後，整檔刪除。

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

每個 fix PR 完成後，刪除本清單對應條目。全清空後刪除本檔。

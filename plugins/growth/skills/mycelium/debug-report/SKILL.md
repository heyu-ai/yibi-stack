---
name: mycelium-debug-report
type: exec
scope: global
description: >
  解完非平凡 bug 後主動萃取除錯知識的儀式：產出 debug report Markdown、
  清理本次留下的過渡產物（註解舊碼、散落 console.log）、封存未採用的實驗方案、
  將摘要寫入 ~/.agents/debugs/debug-reports.jsonl，最後提醒手動 /clear。
  觸發關鍵字：/debug_report、debug report、debug 完了、除錯報告、bug 解完、
  解完 bug、debug 報告、bug 收尾。
---

# /debug_report — 除錯報告與清理

## 概要

每次解完有學習價值的 bug 後執行，養成「除錯 → 萃取知識 → 清場 → 歸檔」儀式。

- **本地全文**：`debugs/<YYYY-MM-DD>_<keyword>_debug_report.md`（git 追蹤，留在專案）
- **跨專案摘要**：`~/.agents/debugs/debug-reports.jsonl`（供跨 session / 跨專案搜尋）

## 步驟

### Step 1 — 決定報告檔名

從 `$ARGUMENTS` 取 keyword（轉 snake_case 英文），若未提供則從本次 session 核心問題自動萃取。

```text
debugs/<YYYY-MM-DD>_<keyword>_debug_report.md
```

`debugs/` 不存在時先建立：

```bash
mkdir -p debugs
```

### Step 2 — 蒐集代理指標

```bash
git diff --stat HEAD   # 異動摘要
git diff --name-only HEAD | wc -l   # 涉及檔案數
git branch --show-current           # 當前 branch
```

> 以上代理指標取代無法量測的 token 數；寫入報告 header。

### Step 3 — 撰寫報告

報告包含以下章節，寫入 Step 1 決定的路徑：

**Header**：`# Debug Report: <keyword>`，附日期、branch、涉及檔案數、`git diff --stat` 輸出。

**症狀**：錯誤訊息原文 + 重現步驟。

**試過什麼、為何無效**（最有價值）：照時間順序用 table 列每個假設、嘗試、排除原因。

**最終解法與根因**：根因寫到第一性原理；說明解法為何有效。

**預防建議**：task list 格式，選適用的類別（偵測 / 護欄 / 流程 / 文件）。

**封存：考慮過但未採用的方案**：保留有實驗價值的替代方案與放棄原因。

### Step 4 — 清理過渡產物

**範圍：限本次 session 為 debug 加入的痕跡；無法確定來源時不刪。**

掃描並移除：

| 類型 | 範例 |
|------|------|
| 註解掉的舊碼 | `# old:`, `// old:`, `# TEMP:`, `# DEBUG:` 整段 |
| 散落偵錯輸出 | `console.log(`, `print("debug`, `logger.debug("temp` |
| 硬編碼的實驗值 | 暫時寫死的 URL、port、magic number |

**判斷原則：**

- 確定是本次 debug 加的 → 移除
- 有功能性不確定 → 留下，用 comment 問使用者
- 無法確定是否本次加的 → 不動

### Step 5 — 呈現 git diff，等使用者確認

```bash
git diff
git status
```

**⚠️ 關鍵節點：必須等使用者確認後才執行 Step 6。**

### Step 6 — 歸檔並提醒 /clear

> **執行位置**：Step 1–5 在呼叫端專案的 cwd 操作（`debugs/`、`git diff` 都屬於該專案）；
> 只有 `uv run python -m tasks.mycelium` 需要在 yibi-stack repo 執行——先解析 `SKILL_REPO`
> 再帶 `--directory "$SKILL_REPO"`：

```bash
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text(encoding="utf-8")).get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi
```

使用者確認 diff 無誤後，將摘要持久化：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.mycelium debug save \
  --keyword "{{keyword}}" \
  --report-path "debugs/{{filename}}" \
  --symptom "{{symptom_one_line}}" \
  --root-cause "{{root_cause_one_line}}" \
  --prevention-tags "{{tag1,tag2}}"
```

完成後回報：

```text
✓ Debug report 已寫入：debugs/<filename>
✓ 摘要已歸檔至：~/.agents/debugs/debug-reports.jsonl

建議現在手動執行 /clear，讓下一個任務從乾淨的 context 開始。
```

## 查詢歷史報告

```bash
# 列出最近 10 筆
uv run --directory "$SKILL_REPO" python -m tasks.mycelium debug list

# 過濾特定 project
uv run --directory "$SKILL_REPO" python -m tasks.mycelium debug list --project yibi-stack

# jq 跨專案搜尋
jq -r '"\(.timestamp[:10]) [\(.keyword)] \(.root_cause)"' \
  ~/.agents/debugs/debug-reports.jsonl
```

## 常見問題

| 問題 | 解法 |
|------|------|
| `debugs/` 目錄不存在 | Step 1 執行 `mkdir -p debugs` |
| keyword 不知道填什麼 | 用 bug 根因關鍵字（如 `mypy_follow_imports`、`utf8_bom_decode`） |
| 清理誤刪正式程式碼 | Step 5 的 `git diff` 讓你檢查；不滿意就 `git checkout <file>` |
| `~/.agents/debugs/` 不存在 | 執行 `uv run --directory "$SKILL_REPO" python -m tasks.mycelium init` 建立 |

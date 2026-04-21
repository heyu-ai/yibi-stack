---
name: learn
type: tool
description: >
  管理專案 learnings — 整合 gstack learnings、handover 交班教訓、insight 洞察三大來源，
  統一瀏覽、搜尋、修剪、匯出。
  關鍵字：learnings、lesson learned、教訓、學到、pattern、pitfall、
  之前遇過、記得嗎、remember、avoid、prevent、預防、怎麼避免、
  what went wrong、retrospective、回顧、踩過的坑、經驗、陷阱
---

# Learn — 教訓統一管理

跨對話累積的模式（pattern）、陷阱（pitfall）、架構決策（architecture）整合自三個來源：

| 來源 | 儲存位置 | 特性 |
|------|----------|------|
| **gstack learnings** | `~/.gstack/projects/<slug>/learnings.jsonl` | 結構化，有 type/confidence |
| **handover 教訓** | `~/.agents/handover/handover.db` | 交班記錄的 lessons_learned、attempted_approaches |
| **insight 洞察** | `~/.agents/insight/insights.jsonl` | Stop hook 自動收集的 ★ Insight 區塊 |

**HARD GATE**：本 skill 不實作程式碼變更，只管理 learnings。

---

## 偵測指令

根據使用者的輸入判斷要執行哪個動作：

- `/learn`（無參數）→ **統一顯示最近**（三個來源）
- `/learn search <query>` → **搜尋**（三個來源）
- `/learn handover` → **只看 handover 教訓**
- `/learn insights` → **只看 insight 洞察**
- `/learn prune` → **修剪**
- `/learn export` → **匯出**
- `/learn stats` → **統計**
- `/learn add` → **手動新增**

---

## 統一顯示最近（預設）

依序查詢三個來源，並以清楚標題區隔呈現。

### 1. gstack learnings（結構化教訓）

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --limit 20 2>/dev/null || echo ""
```

### 2. handover 交班教訓

```bash
PROJECT=$(basename "$(pwd)")
uv run python -m tasks.session_memory lessons show --project "$PROJECT" --last 10 2>/dev/null || echo ""
```

若無 `--project` 匹配，可改用無 project 過濾：

```bash
uv run python -m tasks.session_memory lessons show --last 10 2>/dev/null || echo ""
```

### 3. insight 洞察（可選）

若使用者明確要求包含 insights：

```bash
PROJECT=$(basename "$(pwd)")
uv run python -m tasks.session_memory insight list --project "$PROJECT" --last 5 2>/dev/null || echo ""
```

若三個來源都無資料，告知使用者：

> 本專案尚未累積 learnings。隨著使用 review、investigate、handover 等 skill，系統會自動記錄發現的模式與洞察。

---

## 只看 handover 教訓

```bash
PROJECT=$(basename "$(pwd)")
uv run python -m tasks.session_memory lessons show --project "$PROJECT" --last 20
```

---

## 只看 insight 洞察

```bash
PROJECT=$(basename "$(pwd)")
uv run python -m tasks.session_memory insight list --project "$PROJECT" --last 20
```

---

## 搜尋

同時搜尋三個來源，並以標題區隔呈現結果。

### 1. gstack learnings

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --query "USER_QUERY" --limit 20 2>/dev/null || echo ""
```

### 2. handover 教訓

```bash
PROJECT=$(basename "$(pwd)")
uv run python -m tasks.session_memory lessons search "USER_QUERY" --project "$PROJECT" --last 10 2>/dev/null || echo ""
```

### 3. insight 洞察（含 insights 旗標時）

```bash
PROJECT=$(basename "$(pwd)")
uv run python -m tasks.session_memory lessons search "USER_QUERY" --project "$PROJECT" --insights --last 10 2>/dev/null || echo ""
```

將 `USER_QUERY` 替換為使用者的搜尋詞。清晰呈現所有來源的搜尋結果，並標示來源。

---

## 修剪

檢查 learnings 是否過時或有矛盾。

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --limit 100 2>/dev/null
```

對每筆 learning：

1. **檔案存在性**：若有 `files` 欄位，用 Glob 確認檔案是否仍存在。不存在則標記：`STALE: [key] 參考了已刪除的檔案 [path]`
2. **矛盾偵測**：相同 `key` 但 `insight` 相反的項目，標記：`CONFLICT: [key] 有相互矛盾的記錄`

對每個標記項目用 `AskUserQuestion` 詢問：

- A) 刪除此 learning
- B) 保留
- C) 更新（我來告訴你改什麼）

刪除時直接修改 `learnings.jsonl`，移除對應行；更新時 append 新記錄（最新的優先）。

---

## 匯出

將 learnings 匯出為適合加入 CLAUDE.md 或專案文件的 Markdown。

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --limit 50 2>/dev/null
```

格式化輸出：

```markdown
## 專案 Learnings

### 模式（Pattern）
- **[key]**: [insight]（信心度：N/10）

### 陷阱（Pitfall）
- **[key]**: [insight]（信心度：N/10）

### 偏好（Preference）
- **[key]**: [insight]

### 架構（Architecture）
- **[key]**: [insight]（信心度：N/10）
```

呈現給使用者後，詢問是否要 append 到 CLAUDE.md 或另存新檔。

---

## 統計

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
GSTACK_HOME="${GSTACK_HOME:-$HOME/.gstack}"
LEARN_FILE="$GSTACK_HOME/projects/$SLUG/learnings.jsonl"
if [ -f "$LEARN_FILE" ]; then
  TOTAL=$(wc -l < "$LEARN_FILE" | tr -d ' ')
  echo "TOTAL: $TOTAL 筆"
  # 依 type 統計（去重後）
  cat "$LEARN_FILE" | python3 -c "
import sys, json
from collections import Counter
lines = [l.strip() for l in sys.stdin if l.strip()]
seen = {}
for line in lines:
    try:
        e = json.loads(line)
        dk = (e.get('key','')) + '|' + (e.get('type',''))
        seen[dk] = e
    except (json.JSONDecodeError, KeyError): pass
types = Counter(e.get('type','unknown') for e in seen.values())
print(f'UNIQUE: {len(seen)} (去重後)')
for t, c in types.items(): print(f'  {t}: {c}')
" 2>/dev/null
else
  echo "尚無 learnings 記錄。"
fi
```

以表格呈現統計數字。

---

## 手動新增

用 `AskUserQuestion` 收集以下欄位：

1. 類型（pattern / pitfall / preference / architecture / tool）
2. 短 key（2–5 個英文單字，kebab-case）
3. 洞察（一句話說明）
4. 信心度（1–10）
5. 相關檔案（可選）

然後記錄：

```bash
~/.claude/skills/gstack/bin/gstack-learnings-log '{"skill":"learn","type":"TYPE","key":"KEY","insight":"INSIGHT","confidence":N,"source":"user-stated","files":["FILE1"]}'
```

---

## 常見問題

| 問題 | 處理方式 |
|------|----------|
| `gstack-slug` 找不到 | 確認 gstack 已安裝：`ls ~/.claude/skills/gstack/bin/` |
| learnings.jsonl 不存在 | 正常，尚未累積 learnings；繼續使用其他 skill 即可 |
| 搜尋結果為空 | 換不同關鍵字；或用 `/learn` 看全部 |

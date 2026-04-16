---
name: learn
type: tool
description: 管理專案 learnings — 瀏覽、搜尋、修剪、匯出 gstack 跨對話累積的模式與洞察。關鍵字：learnings、學到、pattern、pitfall、之前遇過、記得嗎、remember
---

# Learn — 專案 Learnings 管理

跨對話累積的模式（pattern）、陷阱（pitfall）、架構決策（architecture）存放於 `~/.gstack/projects/<slug>/learnings.jsonl`。此 skill 提供瀏覽、搜尋、修剪、匯出等操作。

**HARD GATE**：本 skill 不實作程式碼變更，只管理 learnings。

---

## 偵測指令

根據使用者的輸入判斷要執行哪個動作：

- `/learn`（無參數）→ **顯示最近**
- `/learn search <query>` → **搜尋**
- `/learn prune` → **修剪**
- `/learn export` → **匯出**
- `/learn stats` → **統計**
- `/learn add` → **手動新增**

---

## 顯示最近（預設）

顯示最近 20 筆 learnings，依 type 分組。

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --limit 20 2>/dev/null || echo "尚無 learnings。"
```

若無任何 learnings，告知使用者：

> 本專案尚未累積 learnings。隨著使用 review、investigate 等 skill，gstack 會自動記錄發現的模式與洞察。

---

## 搜尋

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --query "USER_QUERY" --limit 20 2>/dev/null || echo "無符合結果。"
```

將 `USER_QUERY` 替換為使用者的搜尋詞。清晰呈現搜尋結果。

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

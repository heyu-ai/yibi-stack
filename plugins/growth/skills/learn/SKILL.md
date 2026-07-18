---
name: learn
type: tool
scope: global
description: >
  管理專案 learnings — 整合 handover 交班教訓、insight 洞察兩大來源，
  統一瀏覽、搜尋、修剪、匯出。gstack learnings 為選用（私有工具）。
  關鍵字：learnings、lesson learned、教訓、學到、pattern、pitfall、
  之前遇過、記得嗎、remember、avoid、prevent、預防、怎麼避免、
  what went wrong、retrospective、回顧、踩過的坑、經驗、陷阱
---

# Learn — 教訓統一管理

跨對話累積的模式（pattern）、陷阱（pitfall）、架構決策（architecture）整合自兩個來源：

| 來源 | 儲存位置 | 特性 |
|------|----------|------|
| **handover 教訓** | `~/.agents/handover/handover.db` | 交班記錄的 lessons_learned、attempted_approaches |
| **insight 洞察** | `~/.agents/insight/insights.jsonl` | Stop hook 自動收集的 ★ Insight 區塊 |
| **gstack learnings** *(optional)* | `~/.gstack/projects/<slug>/learnings.jsonl` | 私有工具，不屬於 yibi-stack；有則顯示，無則略過 |

**HARD GATE**：本 skill 不實作程式碼變更，只管理 learnings。

> **執行位置**：本 skill 可從任何 cwd 觸發，tasks-backed 操作一律呼叫 PATH 中
> installed `mycelium`。**skill 啟動時執行一次**（不要在每個 bash block 前重複執行）：
>
> ```bash
> _gcd=$(git rev-parse --git-common-dir 2>/dev/null)
> case "$_gcd" in
>     /*)
>       _dir=$(dirname "$_gcd")
>       ORIG_PROJECT=$(basename "$_dir")
>       unset _dir ;;
>     ?*)
>       _top=$(git rev-parse --show-toplevel)
>       ORIG_PROJECT=$(basename "$_top")
>       unset _top ;;
>     *)  ORIG_PROJECT=$(basename "$PWD") ;;
> esac
> unset _gcd
> PROJECT="$ORIG_PROJECT"
> if ! command -v mycelium >/dev/null 2>&1; then
>   echo '[FAIL] 缺少 mycelium，請執行：uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"' >&2
>   exit 1
> fi
> ```
>
> `ORIG_PROJECT` 必須在任何 CLI 呼叫前捕捉，且使用 `--git-common-dir` 而非 `--show-toplevel`，
> 以確保 worktree 環境下取得的是 repo 名稱而非 branch 目錄名稱。

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

依序查詢各來源，並以清楚標題區隔呈現。

### 1. handover 交班教訓

```bash
mycelium lessons show --project "$PROJECT" --last 10 2>/dev/null || echo ""
```

### 2. insight 洞察（可選）

若使用者明確要求包含 insights：

```bash
mycelium insight list --project "$PROJECT" --last 5 2>/dev/null || echo ""
```

### 3. gstack learnings（選用，需私有工具）

若偵測到 `~/.claude/skills/gstack/bin/gstack-slug` 存在，才執行：

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --limit 20 2>/dev/null || echo ""
```

若不存在則略過，不顯示任何 gstack 相關錯誤。

若各來源都無資料，告知使用者：

> 本專案尚未累積 learnings。隨著使用 review、investigate、handover 等 skill，系統會自動記錄發現的模式與洞察。

---

## 只看 handover 教訓

```bash
mycelium lessons show --project "$PROJECT" --last 20
```

---

## 只看 insight 洞察

```bash
mycelium insight list --project "$PROJECT" --last 20
```

---

## 搜尋

同時搜尋各來源，並以標題區隔呈現結果。

### 1. handover 教訓

```bash
mycelium lessons search "USER_QUERY" --project "$PROJECT" --last 10 2>/dev/null || echo ""
```

### 2. insight 洞察（含 insights 旗標時）

```bash
mycelium lessons search "USER_QUERY" --project "$PROJECT" --insights --last 10 2>/dev/null || echo ""
```

### 3. gstack learnings（選用，需私有工具）

若 `~/.claude/skills/gstack/bin/gstack-slug` 存在：

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
~/.claude/skills/gstack/bin/gstack-learnings-search --query "USER_QUERY" --limit 20 2>/dev/null || echo ""
```

將 `USER_QUERY` 替換為使用者的搜尋詞。清晰呈現所有可用來源的搜尋結果，並標示來源。

---

## 修剪

> **注意**：修剪功能目前僅適用於 gstack learnings（私有工具）。無 gstack 時此命令為 no-op。

先確認 `~/.claude/skills/gstack/bin/gstack-slug` 存在，再執行修剪。若不存在則告知使用者 gstack 未安裝，跳過此 section。

```bash
if [ ! -x ~/.claude/skills/gstack/bin/gstack-slug ]; then echo "gstack 未安裝，修剪功能不適用"; exit 0; fi
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

若偵測到 `~/.claude/skills/gstack/bin/gstack-slug` 存在，才執行：

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

呈現 handover 教訓數量：

```bash
mycelium lessons show --project "$PROJECT" --last 9999 --json 2>/dev/null | jq length
```

若 gstack 可用（私有工具），也顯示 gstack learnings 統計：

```bash
eval "$(~/.claude/skills/gstack/bin/gstack-slug 2>/dev/null)"
GSTACK_HOME="${GSTACK_HOME:-$HOME/.gstack}"
LEARN_FILE="$GSTACK_HOME/projects/$SLUG/learnings.jsonl"
if [ -f "$LEARN_FILE" ]; then
  TOTAL=$(wc -l < "$LEARN_FILE" | tr -d ' ')
  echo "gstack TOTAL: $TOTAL 筆"
else
  echo "gstack: 尚無 learnings 記錄。"
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

若偵測到 `~/.claude/skills/gstack/bin/gstack-learnings-log` 存在，才執行：

```bash
~/.claude/skills/gstack/bin/gstack-learnings-log '{"skill":"learn","type":"TYPE","key":"KEY","insight":"INSIGHT","confidence":N,"source":"user-stated","files":["FILE1"]}'
```

否則，在交班時透過 `/handover` skill 的 `lessons_learned` 欄位記錄，下次 `/learn` 就會顯示。

---

## 常見問題

| 問題 | 處理方式 |
|------|----------|
| `gstack-slug` 找不到 | gstack 是私有工具，非 yibi-stack 的一部分；略過 gstack 段落即可 |
| learnings.jsonl 不存在 | 正常，尚未累積 learnings；繼續使用其他 skill 即可 |
| 搜尋結果為空 | 換不同關鍵字；或用 `/learn` 看全部 |

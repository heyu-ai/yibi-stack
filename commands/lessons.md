---
name: lessons
description: 查詢、搜尋、寫入 typed lessons。取代 /recall。
---

# Lessons — 教訓查詢與寫入

查詢本 project 累積的 typed lessons、legacy handover 教訓，以及寫入新教訓。

**使用方式：**

- `/lessons` — 顯示最近 15 筆教訓（含 legacy）
- `/lessons <關鍵字>` — 隱式搜尋（等同 `/lessons find <關鍵字>`）
- `/lessons find <關鍵字>` — 明確搜尋，支援自然語意 filter 推斷
- `/lessons ask` — 互動式寫入新教訓

## Step 1 — 偵測 SKILL_REPO

```bash
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text(encoding="utf-8")).get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi
```

## Step 2 — 偵測 project

```bash
GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [ -n "$GIT_COMMON" ]; then
  GIT_ROOT=$(dirname "$GIT_COMMON")
  PROJECT=$(basename "$GIT_ROOT")
else
  PROJECT=$(basename "$(pwd)")
fi
```

## Step 3 — 分流 $ARGUMENTS

根據 `$ARGUMENTS` 決定模式：

### 無 arguments（`/lessons`）

執行 `lessons show --last 15 --include-legacy`：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium lessons show \
  --project "$PROJECT" --last 15 --include-legacy
```

呈現最近 15 筆教訓。

### `/lessons find <keyword>` 或 `/lessons <keyword>`（非 ask）

1. 從 arguments 推斷 filter（自然語意映射）：
   - 含「雷」「pitfall」「踩過」→ 加 `--type pitfall`
   - 含「確認過」「可信」「trusted」→ 加 `--trusted-only`
   - 含「跨專案」「cross-project」→ 加 `--cross-project`

2. 執行搜尋（去掉 filter 關鍵字後的純搜尋詞）：

依推斷的 filter，組合以下指令（`$KEYWORD` 替換為實際搜尋詞，可選 flag 視推斷結果加入）：

```text
uv run --directory "$SKILL_REPO" python -m tasks.mycelium lessons search \
  <KEYWORD> --project "$PROJECT" --last 10 --include-legacy \
  [可選：--type pitfall] [可選：--trusted-only] [可選：--cross-project]
```

此為 prose 指引，不可直接執行。實際呼叫時，agent 應用變數替換後生成真實的 bash call。

### `/lessons ask` 或 arguments 含「記下」「我要寫一條」

進入 ask 模式：使用 AskUserQuestion 依序收集欄位，再呼叫 `lessons add`。

需收集的必填欄位：

| 欄位 | 選項 / 說明 |
|------|------------|
| type | pattern / pitfall / preference / architecture / tool / operational / investigation |
| key | 短識別 key（英數字、底線、連字號，如 `dedup-grain`） |
| insight | 教訓內文（至少 10 字元） |
| confidence | 1-10 的整數 |
| source | observed / user-stated / inferred / cross-model |

選填欄位（可跳過）：`--skill`、`--files`（可重複）

收集完成後執行：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium lessons add \
  --type "$TYPE" --key "$KEY" --insight "$INSIGHT" \
  --confidence "$CONFIDENCE" --source "$SOURCE" \
  --project "$PROJECT"
```

確認輸出的 id 和 trusted bit 後回報使用者。

## Step 4 — 呈現結果

- 若無結果，告知所用的 project 名稱並建議改用 `/lessons ask` 寫入新教訓
- 若有結果，分群展示：**Typed lessons**（type 分類）和 **Legacy**（舊 handover 教訓）

## Skill integration contract（Phase B 以後實作）

以下 skills 將在對應時機自動呼叫 `lessons add`：

| Skill | 時機 | source | 額外參數 |
|-------|------|--------|---------|
| `/pr-retro` | AskUserQuestion 收集 type+confidence 後 | `user-stated` | `--skill pr-retro --retro-pr <N>` |
| `/handover` | session 結束時的 lessons_learned[] | `observed` | `--skill handover --handover-id <id>` |
| `/investigate` | DEBUG REPORT 後的 root-cause patterns | `observed` | `--skill investigate` |

這些整合點為 Phase B 工作範圍，`lessons add` CLI 介面在 Phase A 已穩定不變。

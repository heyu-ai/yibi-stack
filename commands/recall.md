# Recall — 查詢 session-memory 教訓與試過的方案

查詢本 project 累積的 lessons_learned、attempted_approaches 與 insights，
支援直接顯示最近記錄或關鍵字搜尋。

**使用方式：**

- `/recall` — 顯示目前 project 最近 15 筆教訓與試過的方案（含 insights）
- `/recall <關鍵字>` — 搜尋含指定關鍵字的教訓（`$ARGUMENTS` 即為關鍵字）

## Step 1 — 偵測 SKILL_REPO

```bash
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text(encoding="utf-8")).get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi
```

## Step 2 — 偵測 project

```bash
WORKDIR=$(pwd)
PROJECT=$(basename "$WORKDIR")
GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [ -n "$GIT_COMMON" ]; then
  GIT_ROOT=$(dirname "$GIT_COMMON")
  PROJECT=$(basename "$GIT_ROOT")
fi
```

（`--git-common-dir` 在 worktree 和主 repo 均回傳主 repo 的 `.git` 目錄，其 parent 為正確的主 repo 路徑。不在 git repo 內時 `GIT_COMMON` 為空，fallback 用 `pwd` basename。）

## Step 3 — 執行查詢

**若 `$ARGUMENTS` 為空**（`/recall` 無關鍵字），執行 `lessons show`：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory lessons show \
  --project "$PROJECT" --last 15 --insights
```

**若 `$ARGUMENTS` 非空**（`/recall <query>`），執行 `lessons search`：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory lessons search "$ARGUMENTS" \
  --project "$PROJECT" --last 10 --insights
```

## Step 4 — 呈現結果

根據輸出，整理並分群呈現：

1. **Lessons learned**（`lessons_learned` 來源）：從過去錯誤學到的規則
2. **Tried approaches**（`attempted_approaches` 來源）：試過的方案與結果
3. **Insights**（`insights` 來源，若有）：觀察與洞察

若查無記錄，告知使用者所用的 `project` 名稱，並建議：

> 「以 project='$PROJECT' 查無記錄。
> 可嘗試 `/recall` 搜尋其他關鍵字，或查看 session-memory 是否有記錄（`/handover` 後才有）。」

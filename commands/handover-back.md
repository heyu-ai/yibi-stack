# Handover Back — 讀取上次工作進度

回到上次工作時執行此命令，自動偵測當前專案並讀取對應的 handover 記錄。

## Step 1 — 偵測當前專案並讀取交班

使用當前工作目錄的 basename 作為 project name（與 `handover write` 寫入時的 `detect_project()` 行為一致）：

```bash
SKILL_REPO=$(python3 -c "import json,pathlib; print(json.load(open(str(pathlib.Path.home()/'.agents/config.json'))).get('skill_repo',''))" 2>/dev/null)
if [ -z "$SKILL_REPO" ]; then echo "⚠️  skill_repo 未設定，請在 ainization-skill 目錄執行 make install"; fi
PROJECT=$(basename "$(pwd)")
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory handover read --last 3 --project "$PROJECT"
```

若查無記錄，明確告知使用者所用的 project name，方便確認是否有誤：

> 「以 project='$PROJECT' 過濾，查無記錄。
> 若 project 名稱有誤，可改用不帶 --project 的指令查詢全部記錄。」

不帶 `--project` 顯示所有記錄（跨專案）：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory handover read --last 3
```

## Step 2 — 呈現重點

根據讀取結果，整理並呈現：

1. **上次工作主題**：`topic`
2. **完成了什麼**：`completed`
3. **卡住的事項**：`blocked`（若有）
4. **下一步優先事項**：`next_priorities`
5. **關鍵決策**：`decisions`

## Step 3 — 建議行動

根據 `next_priorities` 提示使用者：

> 「根據上次 {{project}} 的交班，建議從以下開始：...」

若有 `blocked` 項目，也一併提醒。

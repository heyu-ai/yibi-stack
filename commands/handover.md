# Handover — 寫入工作交班記錄

結束本次工作階段前，將目前進度、決策、下一步寫入 handover 記錄，供下次（或其他 Agent）接手。

## Step 1 — 環境確認

```bash
cd "$(git rev-parse --show-toplevel)"
ls ~/.agents/handover/handover.db 2>/dev/null || echo "⚠️  DB 不存在，請先跑 uv run python -m tasks.session_memory init"
SKILL_REPO=$(python3 -c "import json,pathlib; print(json.load(open(str(pathlib.Path.home()/'.agents/config.json'))).get('skill_repo',''))" 2>/dev/null)
if [ -z "$SKILL_REPO" ]; then echo "⚠️  skill_repo 未設定，請在 ainization-skill 目錄執行 make install"; fi
```

## Step 2 — 從對話萃取摘要

根據目前對話內容，自動整理：

- `topic`：本次工作的主題（一句話）
- `session_type`：`sdd` / `debug` / `discussion` / `admin`
- `summary`：對話重點摘要（2-4 句）
- `completed`：完成了什麼（JSON array）
- `decisions`：做了哪些決策（JSON array）
- `blocked`：卡住的事項（JSON array，若無則 `[]`）
- `next`：下一步優先事項（JSON array）
- `lessons`：學到什麼（JSON array，若無則 `[]`）
- `approaches`：試過的方案（JSON array，debug 時特別重要）
- `tags`：自由標籤（JSON array）

## Step 3 — 寫入交班

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory handover write \
  --session-type {{session_type}} \
  --topic "{{topic}}" \
  --summary "{{summary}}" \
  --completed '{{completed_json}}' \
  --decisions '{{decisions_json}}' \
  --blocked '{{blocked_json}}' \
  --next '{{next_json}}' \
  --lessons '{{lessons_json}}' \
  --approaches '{{approaches_json}}' \
  --tags '{{tags_json}}'
```

未提供的環境 metadata 會自動偵測（`device` / `branch` / `project` / `working_dir`）。

## Step 4 — 確認寫入

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory handover read --last 1
```

輸出最新一筆確認寫入成功。

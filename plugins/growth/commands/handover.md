---
model: sonnet
---
<!-- markdownlint-disable-file MD041 -->

# Handover — 寫入工作交班記錄

結束本次工作階段前，將目前進度、決策、下一步寫入 handover 記錄，供下次（或其他 Agent）接手。

## Step 1 — 環境確認

```bash
git rev-parse --show-toplevel
[ -f ~/.agents/handover/handover.db ] || echo '[WARN] DB 不存在，請先跑 uv run python -m tasks.mycelium init'
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
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
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
REAL_WORKDIR=$(pwd)
PROJECT=$(basename "$REAL_WORKDIR")
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium handover write \
  --workdir "$REAL_WORKDIR" \
  --project "$PROJECT" \
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
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium handover read --last 1
```

輸出最新一筆確認寫入成功。

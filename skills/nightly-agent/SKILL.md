---
name: nightly-agent
type: exec
scope: project
description: 夜間自我改善 Agent — 讀取 transcript/mycelium friction events、聚類後草擬 hookify rule 或 CLAUDE.md gotcha、驗證 failing→passing test、開 PR。每日 21:00 自動執行。
---

# Nightly Self-Improvement Agent

每晚自動掃描最近 24h 的 session transcripts 和 mycelium lessons，
找出反覆出現的 friction patterns（AP2 blocks、worktree conflicts 等），
草擬預防性 artifacts，並在通過 failing→passing test 後開 PR。

## 自動排程執行守則（零互動、預設唯讀）

本 skill 有兩條觸發路徑，零互動契約只套用其中一條：

- **`command` job（直接 CLI subprocess）**：本檔 Scheduler Config 範例註冊的就是這條——
  scheduler 直接跑 `python -m tasks.nightly_agent run`，**不是 agent turn**，刻意非互動 +
  failing→passing test gate 把關，full `run`（含 `git push` + `gh pr create`）是其設計行為，
  不受下列契約限制。
- **skill / agent-invoked path（ACP Gateway `skill:`/`claude:` job、webhook、auto mode）**：
  屬於 Claude Code v2.1.183 起的 **task notification** 情境——auto mode 下**無法 approve
  待確認動作、不能設 session 標題**（見 `.claude/rules/11-skill-authoring.md`「Scheduled Skills
  Must Be Zero-Interaction and Read-Only by Default」）。**以下四條契約套用此路徑**：

1. **預設唯讀**：task 未明確要求開 PR 時，只執行 read-only 路徑（Step 4 `analyze`，或 Step 3
   加 `--dry-run`），輸出報告/digest 後停止。
2. **write 為 opt-in**：完整 `run`（會 `git push` + `gh pr create`）只在 task 定義或呼叫
   prompt **明確要求**「draft + 開 PR」時才執行；以明確 flag/參數 gate，不得以互動確認作 gate。
3. **不使用互動確認**：排程路徑中不得出現 `AskUserQuestion` / `click.confirm` 等等待使用者
   回答的步驟（無人可回答）。
4. **報告為 fallback**：不確定時 emit 報告（log / digest / handover）後停止，而非在無人值守下
   執行不可逆動作。

> **safety net ≠ 唯讀預設**：Python CLI 內建的 failing→passing test gate 是正確性防線，
> 但**不等於**「唯讀預設」——唯讀預設由上述契約與呼叫方的明確 write 請求共同保證。

## Steps

### Step 1 — Environment Check

```bash
uv --version
gh --version
test -n "$ANTHROPIC_API_KEY" && echo "API key set" || echo "[WARN] ANTHROPIC_API_KEY not set"
```

確認 `ANTHROPIC_API_KEY` 已設定（draft 功能需要）；
若只做 `analyze` 則不需要。

### Step 2 — Setup（首次執行）

```bash
uv run python -m tasks.nightly_agent setup
```

在 `.runtime/nightly_agent.json` 建立預設設定。

### Step 3 — Full Run（Draft + PR）

```bash
uv run python -m tasks.nightly_agent run --hours 24
```

執行完整流程：

1. 讀取最近 24h transcript sessions
2. 讀取 mycelium pitfall/pattern lessons
3. 分類 friction events（AP2、worktree conflict、wrong approach、buggy code、language mismatch）
4. Jaccard 聚類（預設 threshold=0.25）
5. 對 count ≥ 2 的 cluster 呼叫 Claude API 草擬 artifact
6. 執行 failing→passing test 驗證（拒絕未通過的）
7. 建立 PR branch 並呼叫 `gh pr create`

加 `--dry-run` 只做分析，不草擬、不開 PR。

### Step 4 — Analyze Only

```bash
uv run python -m tasks.nightly_agent analyze --hours 24
```

輸出 JSON 報告到 stdout。

### Step 5 — View Digest

```bash
uv run python -m tasks.nightly_agent digest
```

顯示今日的 Markdown digest（位於 `.runtime/nightly-agent/digests/digest-YYYY-MM-DD.md`）。

## Scheduler Config（自動排程）

直接編輯 `.runtime/schedules.json`（`add-job` 指令不存在；請手動維護此檔）：

```json
{
  "version": "1.0",
  "jobs": [
    {
      "id": "nightly-self-improvement",
      "description": "Nightly friction clustering and PR creation",
      "schedule": "daily",
      "time": "03:00",
      "command": [
        "uv", "run", "--directory", "/path/to/yibi-stack",
        "python", "-m", "tasks.nightly_agent", "run"
      ],
      "enabled": true,
      "timeout_seconds": 600
    }
  ]
}
```

> **注意**：`command` 中的 `/path/to/yibi-stack` 請替換為你的本機 repo 根目錄絕對路徑。
> 可用 `git rev-parse --show-toplevel` 確認。

## Config Keys（`.runtime/nightly_agent.json`）

| Key | 預設 | 說明 |
|-----|------|------|
| `lookback_hours` | 24 | 掃描視窗（小時） |
| `min_cluster_size` | 2 | cluster 最少事件數 |
| `jaccard_threshold` | 0.25 | 相似度閾值 |
| `draft_model` | `claude-sonnet-4-6` | 草擬用 Claude 模型 |
| `github_repo` | auto-detect | GitHub owner/repo |
| `pr_branch_prefix` | `nightly-agent` | PR branch 前綴 |

## FAQ

| 問題 | 解法 |
|------|------|
| `ANTHROPIC_API_KEY 未設定` | 在 `.env` 加入 `ANTHROPIC_API_KEY=sk-...` |
| `gh pr create 失敗` | 執行 `gh auth login` 確認已登入 |
| Artifact 草擬後 test 未通過 | 查看 `.runtime/nightly-agent/digests/` 中的 digest，確認 `after_output` 錯誤訊息 |
| 沒有 eligible clusters | 過去 24h 沒有重複 friction（正常）；可用 `--hours 72` 擴大視窗 |
| mycelium DB 不存在 | 正常（首次使用）；agent 會 skip 並繼續 |

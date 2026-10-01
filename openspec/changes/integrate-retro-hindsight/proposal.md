## Why

Issue #425 的 retro 教訓目前只進 Mycelium；跨 session 語意查找、promotion 查重與 initiative outcome 沒有接到 Hindsight。需要可降級的衍生索引，保留 Mycelium 的唯一權威與既有 Evidence/Promotion Gate。

## What Changes

- A0：每次 invocation 一次 MCP capability / server-read preflight，失敗記錄 degraded 並繼續原流程。
- A1：search-first recurrence，排除自身 projection，僅有獨立事件指針或明確人類確認才作為 recurrence 證據。
- A2：在 Step 5 成功寫入並讀回 canonical lesson 後才投影；pitfall/pattern 多因子門檻、stable-title replacement、生命週期 tombstone。
- 使用者已同意依 MCP 現況調整 A2：title/content 是唯一 ingest 參數；source_system/source_id/content_hash 存在 content envelope，不冒充 native metadata。revision key 是內容層識別，不是伺服器 operation_id。不直接改寫合成主題頁，文件供原有頁面合成使用。
- A3：以 repo-qualified Epic/change ID 查找 initiative；既有者用 relates_to_page_id 更新，未知寫入結果不盲目重試建立。
- B1/B2：ainization-skill 的 lesson-promotion 在路由前查 canonical ADR/rules，再做 advisory duplicate/contradiction 判讀，交人裁決。
- 每個呼叫落 audit receipt；報告使用真實 invocation 計數，未累積 30 次 retro 時明示樣本不足。

## Capabilities

### New Capabilities

- `retro-hindsight-projection`: 可降級的語意讀取、canonical lesson 衍生投影、initiative 更新及觀測。
- `promotion-hindsight-advisory`: promotion 的查重、決策矛盾提示與 lifecycle 同步。

### Modified Capabilities

無；不變更 Mycelium 儲存／CLI 契約。

## Impact

- Modified: `plugins/growth/skills/pr-retrospective/SKILL.md`、`plugins/growth/README.md`、`CHANGELOG.md`。
- New: `plugins/growth/skills/pr-retrospective/HINDSIGHT.md`、`plugins/growth/skills/pr-retrospective/scripts/hindsight_projection.py`、`scripts/tests/test_hindsight_projection.py`。
- 外部 repo：ainization-skill 的 lesson-promotion skill，在該 repo 的 feat-retro-hindsight worktree 獨立變更，不複製進 yibi-stack。
- 不改 upstream Hindsight runtime、不改 Mycelium lifecycle、不新增 distill skill、不修改 learn skill。

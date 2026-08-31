## Why

`/pr-retro` 的 queue flow 在 Evidence Gate 通過後直接要求「目標檔案 + patch-surface + rule 草稿」，
把 ticket 當成知識容器——retro 的直接輸出就是半成品 rule。PR #1638 是反例：佇列原有 13 項，
實查後 10 項早已存在；大量 review 成本花在修正「過早合成的 rule」，不是解決原始 friction。

根本原因是三種「升級」被混在同一條管線：

| 軸 | 問題 | 現況 |
|---|---|---|
| 記憶溫度 | 多常被取用？ | `tier`（working/hot/cold/archival），由 access count 驅動 |
| 認知成熟度 | 這個主張有多可靠？ | **不存在**——`confidence` 是寫入時的單一純量，沒有 lifecycle |
| 政策狀態 | 是否應改變 harness？ | 由 queue flow 隱式承擔，沒有獨立狀態 |

`add-retro-conformance-eval` 已採取正確原則（shadow → 量測 → 再啟用 demotion），同一原則也應
套到 observation → rule promotion：先把 episode 寫進 Mycelium，讓證據在 distill 裡自然聚合成
observation，再由人類決定是否進入 policy candidate——而不是每次 retro 都產出 rule 草稿。

## What Changes

- **切斷 retro → queue 直通**：`/pr-retro` 一律寫 episode 到 Mycelium（已有路徑）；
  queue comment 降為 optional human action，不再由 agent 自動 `gh issue comment`。
  Emergency exception（bleeding mechanical gap）保留快速通道。
- **LessonRecord 加 `epistemic_status` 欄位**：`episode` / `observation` / `corroborated` /
  `contradicted`，與 `tier`（retrieval temperature）平行但語意獨立。新 lesson 預設為 `episode`。
- **LessonRecord 加 `superseded_by` 欄位**：指向修正版的 lesson ID，使 episode 保持
  append-only（事實記錄有誤時 append correction，不覆寫原文）。
- **distill 輸出格式降級**：從「candidate rule 草稿 + 建議落點」改為「observation summary +
  evidence ID list」——reflect 而不是 prescribe。distill 的聚合門檻（3 lessons、2 PRs、
  avg confidence ≥ 7）暫不調整，先當 shadow 初始值。
- **nightly agent 降為 dry-run**：`tasks/nightly_agent` 只產 digest 不開 PR，直到新的
  成熟度模型驗證完成。

## Non-Goals

- **不更換 memory backend**：不同時替換 Mycelium 的儲存層（如改為 Hindsight bank）。
  先把 lifecycle 和 promotion contract 做對，再評估 backend。
- **不修改 Evidence Gate / Promotion Gate 本身的邏輯**：`/pr-retro` 的 Evidence Gate
  三層分類（Probed / Incident-cited / Subjective）和 Promotion Gate（G1-G3）保持不變；
  改的是 gate 之後的 queue 寫入行為。
- **不調整 distill 聚合門檻**：`MIN_CLUSTER_SIZE`、`MIN_DISTINCT_PRS`、`MIN_AVG_CONFIDENCE`
  先維持，觀察 shadow 數據再決定。
- **不建全新的 maturity state machine**：利用現有 Mycelium schema + distill 基礎設施，
  加欄位而非加系統。
- **Policy candidate → adopted control 的完整 promotion workflow 不在本 change 範圍**：
  本 change 只做「把 episode 寫對、把自動 queue 拿掉、把 distill 降級為 observation」，
  promotion 的人類決策流程留給後續 change。

## Capabilities

### New Capabilities

- `retro-episode-retention`：Retro 產出只寫 episode 到 Mycelium；harness queue comment
  降為 optional human action，emergency exception 保留快速通道

### Modified Capabilities

- `mycelium-memory-tiers`：LessonRecord schema 加 `epistemic_status` 與 `superseded_by` 欄位，
  retrieval temperature 與認知成熟度分離

## Impact

- Affected specs:
  - New: `retro-episode-retention`（retro 寫入行為的 spec-level contract）
  - Modified: `mycelium-memory-tiers`（schema 擴充）
- Affected code:
  - Modified: `tasks/mycelium/models.py`（加 `epistemic_status`、`superseded_by` 欄位）
  - Modified: `tasks/mycelium/db.py`（DB migration 加新欄位）
  - Modified: `tasks/mycelium/distill_service.py`（輸出格式降級為 observation summary）
  - Modified: `tasks/mycelium/tier_service.py`（tier promotion 邏輯不變，但要確保不與 epistemic_status 耦合）
  - Modified: `plugins/growth/skills/pr-retrospective/SKILL.md`（queue flow 改為 optional）
  - Modified: `tasks/nightly_agent/cli.py`（降為 dry-run 模式）
  - New: `tasks/mycelium/tests/test_epistemic_status.py`（新欄位的單元測試）

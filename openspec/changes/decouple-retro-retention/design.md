## Context

Mycelium 是 yibi-stack 的 learning ledger，儲存 PR retro 產出的 typed lessons。目前的知識生命週期：

1. `/pr-retro` 執行 → Evidence Gate（三層分類）→ Promotion Gate（G1-G3）
2. 通過 gate 的 lesson 寫入 Mycelium（`lessons` DB table）
3. Queue flow 自動以 `gh issue comment` 把 rule 草稿寫入 harness queue issue
4. Distill service 定期聚合 lessons → 產出 candidate rule 草稿 + 建議落點
5. Nightly agent 讀 Mycelium → 開 PR 把 rule 落地

問題：步驟 3 把「這件事發生了」和「應該寫什麼 rule」綁在一起。LessonRecord 只有一個
`confidence` 純量和一個 `tier`（retrieval temperature），沒有獨立的認知成熟度軸。
一個 lesson 從 episode 成長為 corroborated observation 的過程無處記錄。

## Goals / Non-Goals

**Goals:**

- 把 retro 的 episode 寫入與 harness promotion 解耦：retro 只負責記錄事實，不負責提案改動
- 在 LessonRecord 上建立 `epistemic_status` 軸，與 `tier`（temperature）正交
- 讓 distill 產出 observation summary 而非 rule 草稿
- Nightly agent 在新模型驗證前降為 digest-only

**Non-Goals:**

- 不更換 Mycelium backend（不遷移到 Hindsight 或其他 store）
- 不修改 Evidence Gate / Promotion Gate 的判定邏輯
- 不調整 distill 的聚合門檻（MIN_CLUSTER_SIZE 等）
- 不建 observation → policy candidate → adopted control 的完整 promotion workflow（留給後續 change）
- 不改 `tier_service.py` 的 temperature promotion 規則

## Decisions

### D1：epistemic_status 用 string enum 而非獨立 table

**選擇**：在 `lessons` table 加 `epistemic_status TEXT DEFAULT 'episode'` 欄位，
值域為 `episode` / `observation` / `corroborated` / `contradicted`。

**替代方案**：獨立的 `epistemic_transitions` table 記錄狀態轉移歷史。
**否決理由**：目前只需要追蹤當前狀態，不需要完整 audit trail。如果後續需要
transition history，可以在不改 lessons table 的情況下加 journal table。

### D2：superseded_by 指向 lesson ID 而非覆寫原文

**選擇**：加 `superseded_by TEXT DEFAULT NULL` 欄位。當 episode 的事實記錄有誤時，
建立新 lesson 作為修正版，原 lesson 的 `superseded_by` 指向新 lesson 的 ID。
原文保留不動——這是 append-only ledger 的語意。

**替代方案**：直接更新原 lesson 的 `insight` / `context` 欄位。
**否決理由**：覆寫破壞 audit trail，且下游的 distill cluster 可能已引用原文。
指向修正版後，distill 可以在聚合時自動排除被 supersede 的 lesson。

### D3：queue flow 改為 optional human action 而非完全移除

**選擇**：`/pr-retro` 的 queue flow section 保留，但只在 agent 偵測到 emergency
exception（bleeding mechanical gap 或 correcting wrong content）時自動執行。
其餘情況下，agent 告知使用者「如需手動加入 queue，可執行以下指令」，不主動 comment。

**替代方案 A**：完全移除 queue flow code path。
**否決理由**：emergency fast track 仍然需要；完全移除會失去已驗證的 gate 邏輯。

**替代方案 B**：保留自動寫入但加 `auto_queue: false` config flag。
**否決理由**：config flag 容易被忘記或誤開；行為應由 SKILL.md 的 runbook 邏輯控制，
不應依賴外部 flag。

### D4：distill 輸出降級為 observation summary

**選擇**：`distill_service.py` 的 `_format_candidate()` 輸出改為：
- Observation statement（一句描述觀察到的模式）
- Supporting evidence IDs（lesson ID list）
- Distinct PR count 和 recurrence span
- 不再產出 target file、patch-surface、rule 草稿

**理由**：distill 的職責是「哪些 episode 形成了模式」，不是「應該寫什麼 rule」。
後者是人類決策，應在 spectra change proposal 或 promotion workflow 中處理。

### D5：nightly agent 降為 dry-run 模式

**選擇**：`tasks/nightly_agent/cli.py` 的 `run` command 加 `--dry-run` flag，
在 `.runtime/schedules.json` 中把 nightly-self-improvement job 的參數改為帶 `--dry-run`。
dry-run 模式下只產 digest markdown 到 `.runtime/logs/`，不執行 `gh pr create`。

**替代方案**：把 `enabled` 設為 `false`。
**否決理由**：完全關閉會失去 digest 產出，無法收集 shadow 數據供後續驗證。

## Implementation Contract

### Behavior

1. **Retro episode 寫入**：`/pr-retro` 執行後，所有 lesson 寫入 Mycelium 時
   `epistemic_status` 預設為 `episode`。queue 自動 comment 只在 emergency exception 時觸發。
   使用者可看到「如需手動加入 queue」的提示文字。

2. **epistemic_status 查詢**：`uv run python -m tasks.mycelium lessons list` 的輸出包含
   `epistemic_status` 欄位。`lessons list --status episode` 可過濾特定狀態。

3. **superseded_by 標記**：`uv run python -m tasks.mycelium lessons supersede <old-id> <new-id>`
   把 `old-id` 的 `superseded_by` 設為 `new-id`。被 supersede 的 lesson 在 distill 聚合時
   自動排除（不計入 cluster）。

4. **distill 輸出**：`uv run python -m tasks.mycelium distill` 的輸出不再包含 rule 草稿
   和目標檔案建議。每個 candidate 只有 observation statement、evidence ID list、recurrence
   metrics。

5. **nightly dry-run**：`uv run python -m tasks.nightly_agent run --dry-run` 產出 digest
   到 `.runtime/logs/` 但不呼叫 `gh pr create`。排程設定自動帶 `--dry-run`。

### Failure Modes

- 既有 lesson 的 `epistemic_status` 為 NULL（migration 前的資料）：讀取時視為 `episode`，
  不 crash。`_ensure_columns()` 加 `ALTER TABLE` 時用 `DEFAULT 'episode'`。
- `superseded_by` 指向不存在的 ID：寫入時不驗證（避免 foreign key constraint 複雜度），
  distill 聚合時遇到無效 ID 跳過並 log warning。
- Nightly agent `--dry-run` 仍然讀 Mycelium 和 GitHub；只是不寫 PR。如果讀取失敗，
  行為與現行相同（log error + exit non-zero）。

### Acceptance Criteria

- `test_epistemic_status.py`：驗證 CRUD、default 值、filter by status、supersede 行為
- `test_distill_service.py`：驗證輸出不含 rule 草稿和目標檔案
- `test_nightly_agent.py`：驗證 `--dry-run` 不呼叫 `gh pr create`
- 手動驗證：跑一次 `/pr-retro`，確認 lesson 寫入時 `epistemic_status = 'episode'`，
  且無自動 queue comment（除非 emergency）

### Scope Boundaries

- **In scope**：LessonRecord schema、retro queue flow、distill output format、nightly dry-run
- **Out of scope**：distill 聚合門檻調整、tier promotion 規則、Evidence Gate 邏輯、
  完整的 policy promotion workflow、CLI 的 epistemic_status 批次更新命令

## Risks / Trade-offs

- **[Risk] 切斷 queue 後知識不再流向 harness** → 這是 intentional。mitigation 是
  distill 的 observation summary 仍然可見，人類可以主動發起 promotion。
  emergency fast track 確保緊急修正不被阻斷。
- **[Risk] nightly dry-run 期間沒有自動化 rule PR** → mitigation 是 digest 仍在產出，
  且 `/lesson-promotion` skill 仍可手動觸發。
- **[Risk] 既有 lesson 的 epistemic_status 全部是 episode，distill cluster 可能
  把舊的 corroborated pattern 視為 raw episode** → mitigation 是短期不影響
  distill 的聚合門檻判斷（門檻用的是 confidence 和 PR count，不是 epistemic_status）。
  後續 change 可以做 backfill。
- **[Trade-off] superseded_by 不做 foreign key 驗證** → 簡化 migration，代價是
  dangling reference 可能存在。distill 遇到時 log warning 而非 crash。

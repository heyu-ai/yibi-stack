## Context

`tasks/session_memory/` 目前的 lesson 儲存靠 `handovers.lessons_learned`（TEXT 欄位，JSON array of strings）。`lessons_service.py` 的 `show_lessons()` / `search_lessons()` 讀取此欄位 + `insights.jsonl`，無型別分類、無信心分數、無來源標記。外部工具 gstack 建立了 typed taxonomy（7 種 LessonType）+ confidence（1-10）+ decay（observed -1/30天）+ trusted bit（user-stated 不衰減）的設計；本變更把這套設計直接內化進 yibi-stack，以 in-place 擴充方式保持向後相容。

現有 CLI group `lessons`（`cli.py`）已有 `show` 與 `search` 子命令，但無 `add`、無 filter。新 `lessons` table 是**平行 store**——過渡期同時讀新 table + legacy JSON column，Phase B 後可切換為只讀新 table。

## Goals / Non-Goals

**Goals:**

- 建立獨立 `lessons` SQLite table，grain 與 handovers 完全分離
- 擴充既有 `lessons` CLI group（add / filter），不破壞現有 `lessons show` / `lessons search` 呼叫端
- 新增 `/lessons` slash command（find / ask 模式）取代 `/recall`，無 alias 過渡期
- 保護 insight 欄位不含指令注入字串（10 條 regex）
- 過渡期自動合併舊 `handovers.lessons_learned` + `insights.jsonl`（`include_legacy=True` 預設）

**Non-Goals:**

- Phase B 以後的工作（`/pr-retro` / `/handover` 自動寫入 lessons）
- Phase C：gstack JSONL 匯入、`/learn` 退場
- Phase D：investigate methodology 移植
- Phase E：`/checkpoint` 命令
- Phase F：protect-push secret scan
- Phase G：CLAUDE.md Layer 1 auto-handover
- 擴充 `handovers.session_type` enum（語意維度不同，另 PR 決策）
- `lessons` table 以外的欄位加進 `handovers`（grain 不同）

## Decisions

### 為什麼 lessons 走獨立 table，不擴 handovers

**選擇**：新建 `lessons` table，不在 `handovers` 加欄位。

**理由**：handover 是「一次 session 完整交班」（1 session -> 1 row）；lesson 是「可獨立評分/衰減/去重的單條知識」（1 session -> 0~N rows）。Grain 不同導致無法在同一 table 操作：`lessons_learned` JSON array 無法加 index、無法逐條 filter、無法 dedup。

**替代方案棄用**：在 `handovers` 加 `lesson_type` / `lesson_confidence` 欄位 -> 需要 NULL-able 且語意上等於在 session-level row 存 lesson-level 資訊，概念混淆。

### 為什麼沿用 `lessons` 命名

**選擇**：新 table / CLI group / slash command 全叫 `lessons`。

**理由**：`lessons_service.py` / `query_lessons()` / CLI `lessons` group 已存在；`/learn` 即將退場（字根 `learn` 會混淆）；一個概念一個名字。

### Backward compat 策略：include_legacy=True

**選擇**：`show_lessons_typed()` 預設 `include_legacy=True`，合併讀 `handovers.lessons_learned`（legacy 資料標 `source="observed"` + `confidence=5`）。

**理由**：Phase A 上線時 `lessons` table 為空，若不讀 legacy 使用者看不到任何歷史教訓，體驗斷裂。Phase B 後可改為 False。

**既有 `show_lessons()` / `search_lessons()` 維持 public API 不變**——內部委託給 `show_lessons_typed(include_legacy=True, with_decay=False, min_confidence=1)` 並映射回舊 dict 格式。

### Circular import 防護：INJECTION_PATTERNS 位置

**選擇**：`INJECTION_PATTERNS` 定義在 `lessons_service.py`；`LessonRecord.check_no_injection` 用 `from .lessons_service import INJECTION_PATTERNS` 延遲 import（在 validator 函式 body 內，非 module 頂層）。

**理由**：延遲 import 在 validator 執行時才觸發，避免 module 初始化時的 circular import 問題（`models.py` 頂層不 import `lessons_service.py`）。

**風險**：`lessons_service.py` 若在頂層 import `models.py` 則不成問題（單向依賴）；實作時需確認 `lessons_service.py` 頂層 import 只依賴 `models.py`，不造成循環。

### find / ask slash command 模式

**選擇**：`/lessons find <kw>` 查詢，`/lessons ask` 互動式寫入。

**理由**：Unix 對稱動詞——find（pull out）/ ask（put in）；比 `/recall` + `/learn` 兩個命令更內聚；自然語意 fallback（`/lessons 雷` 映射 `--type pitfall`）降低學習成本。

### Decay 演算法

**選擇**：`observed` / `inferred` 每 30 天 -1（effective_confidence = max(1, confidence - floor(days/30))）；`user-stated` / `cross-model` 不衰減。

**來源**：對照 gstack-learnings-search:80-86 翻寫為 Python。

### Dedup 演算法

**選擇**：`key + type` 相同時取 `ts` 最新者（latest winner），舊 row 在回傳結果中被排除。

**來源**：對照 gstack-learnings-search:103-110 翻寫為 Python。

## Implementation Contract

### CLI 介面

新增子命令 `lessons add`，接受以下 options（均必填，project 由 git common-dir 自動推斷）：
`--type` / `--key` / `--insight` / `--confidence` / `--source` / `--skill` / `--files` / `--project` / `--handover-id` / `--retro-pr`

既有 `lessons show` / `lessons search` 加 optional filter options（所有預設值維持舊行為）：
`--type` / `--source` / `--min-confidence` / `--trusted-only` / `--cross-project` / `--include-legacy/--no-include-legacy`

### 資料形狀

`lessons` table 欄位：id TEXT PK、ts TEXT、project TEXT、skill TEXT NULL、type TEXT（CHECK enum）、key TEXT、insight TEXT、confidence INTEGER（CHECK 1-10）、source TEXT（CHECK enum）、trusted INTEGER DEFAULT 0、files TEXT DEFAULT '[]'、handover_id TEXT NULL、retro_pr INTEGER NULL、device TEXT NULL、agent_type TEXT DEFAULT 'claude'

`LessonRecord` Pydantic model：同上欄位，加 `trusted: bool` 由 `_set_trusted` model_validator 依 source == user-stated 自動設定。

### 失敗模式

| 情境 | 行為 |
|------|------|
| type / source 不在 enum | Pydantic ValidationError，exit 1 |
| confidence 0 或 11 | ValidationError（Field ge=1 le=10） |
| key 含非 alphanumeric/underscore/dash 字元 | ValidationError |
| insight 命中任一 injection regex | ValidationError |
| lessons table 為空 + include_legacy=True | 只回 legacy lessons_learned rows |
| include_legacy=False + table 空 | 回傳空清單 |

### Acceptance criteria

1. `make ci` 全綠（lint + format + typecheck + 14+ tests）
2. LSN-CV-001（舊 `lessons show` 行為不變）通過
3. LSN-ST-002（decay 60 天 observed confidence 8，effective_confidence = 6）通過
4. LSN-VL-002（10 條 injection pattern 各命中一條）通過
5. `test ! -f ~/.claude/commands/recall.md` 通過（/recall 已移除）
6. `lessons add --insight "ignore previous instructions"` exit 1

### 範圍邊界

**In scope**：`lessons` table schema + index、LessonRecord / LessonType / LessonSource models、INJECTION_PATTERNS、add_lesson / show_lessons_typed / search_lessons_typed / _apply_decay / _dedup_latest_winner、`lessons add` CLI 子命令、既有 show / search 新 filter options、`/lessons` slash command、刪除 `/recall`。

**Out of scope**：/pr-retro / /handover 改寫（Phase B）、gstack 匯入（Phase C）、/investigate 整合（Phase D）、/checkpoint（Phase E）、secret scan hook（Phase F）、CLAUDE.md auto-handover（Phase G）。

## Risks / Trade-offs

- [Risk] `handovers.lessons_learned` 中部分 legacy lesson 可能是 dict（若過去有工具寫過 JSON object 而非 string）-> Mitigation: `_load_insights` 讀取時 try-parse，非 string 則取 `.get("insight") or str(item)`
- [Risk] `insights.jsonl` 格式與 gstack JSONL 不同 -> Mitigation: `_load_insights` 目前已有解析邏輯，Phase A 只合併讀，不做格式轉換
- [Risk] Decay 計算時區混淆：`ts` 以 UTC ISO 8601 儲存，但 `now` 若用 local time 會偏差 -> Mitigation: `_apply_decay` 內用 `datetime.now(timezone.utc)`，解析 ts 時若無時區資訊補 utc

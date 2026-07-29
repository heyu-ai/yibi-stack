# Dev Lifecycle — 跨 Pack 開發週期總覽

`ADR-0006` 記錄了 pack 分類軸本身（流程 / 知識 / 方法論 / 環境品質）。這份文件記錄軸線落地
後，一次典型開發週期實際跨過哪些 pack、彼此在哪個點交手，以及三個真實存在的**執行期跨 pack
依賴**——Claude Code plugin 系統沒有宣告式的 plugin 間相依機制（ADR-0004 已記錄），這些依賴
只能靠文件層的 Prerequisites 說明與 `[FAIL]` 訊息指名安裝指令，讀者必須知道它們存在。

## 週期總覽

```text
/newjob（dev-cycle）
   │  建立隔離 worktree；透過 local-port-manager（dev-cycle）預防多 worktree port 衝突
   ▼
fix bug/issue（dev-cycle: investigate）
   或
/spectra-propose → amplifier → apply（sdd）
   │  spectra-amplifier 可能 dispatch methodology 的 problem-frames / event-storming /
   │  qa-test-design（見下方「跨 pack 依賴」）
   ▼
implement
   ▼
/pr-cycle-deep（dev-cycle）── create PR → mob review → fix → merge → archive
   ▼
ship
   ▼
/pr-retro（growth: pr-retrospective）
   │  讀取 PR context（title / body / AC / commits / diff）——這些內容由上一步 dev-cycle
   │  的 PR 生命週期產出，pr-retrospective 自己不建立 PR
   ▼
（回到 /newjob 開下一輪）

⟲ 週期中斷與續接（可在上述任一點插入）：
   /handover（dev-cycle）→ 寫入 growth 的 mycelium DB（見下方「跨 pack 依賴」）
   /handover-back（dev-cycle）→ 從 growth 的 mycelium DB 讀回
```

`harness`（`harness-eval` / `bash-anti-patterns` / hooks）不是週期上的一個步驟，是**貫穿整個
週期的橫切關注點**：每一次 Bash 呼叫都可能觸發 AP1/AP2 hook；`harness-eval` 可以在週期的任何
時間點被叫來量測 agent 執行環境本身的品質。`3rd-tools`（`codex-review` / `codex-consult` /
`agy-review` / `agy-consult`）同樣是橫切——`/pr-cycle-deep` 的 mob review 階段會用到它們，
但它們不專屬於這條週期的任何單一步驟。

## 三個真實的跨 Pack 執行期依賴

Claude Code 的 plugin 系統沒有「plugin A 依賴 plugin B」的宣告機制。以下三個依賴只存在於
**執行期**（某個 skill 跑到某一步才需要另一個 pack 已安裝），且只能靠 SKILL.md 的
Prerequisites 段落與 `[FAIL]` 訊息讓使用者知道要裝什麼：

### 1. `/handover` / `/handover-back`（dev-cycle）→ `mycelium`（growth）

`dev-cycle` 的 `/handover` 與 `/handover-back` 命令呼叫 `python -m tasks.mycelium`
（`plugins/dev-cycle/README.md` 的 Prerequisites 已載明）——但 mycelium DB 本身、以及讀寫它
的 CLI 實作，都在 `growth` pack。只裝 `dev-cycle@yibi-stack` 而未裝 `growth@yibi-stack`
（或未 `make install`）的使用者，`/handover` 會在呼叫 `tasks.mycelium` 時失敗。

### 2. `pr-retrospective`（growth）讀取 `dev-cycle` 產出的 PR context

`/pr-retro` 從 PR 的 title / body / AC / commits / diff 推論五題回顧草稿——這些內容由
`dev-cycle` 的 PR 生命週期 skill（`pr-cycle-deep` / `pr-cycle-fast` / `pr-review-cycle`）建立
的 PR 產生。這不是一個會讓 `/pr-retro` 執行期失敗的硬依賴（`gh pr view` 對任何存在的 PR 都能
讀），但語意上 `/pr-retro` 是週期的收尾步驟，前提是週期的前段（開 PR、review、merge）已經
發生。

### 3. `spectra-amplifier`（sdd）→ `problem-frames` / `event-storming` / `qa-test-design`（methodology）

`spectra-amplifier` 留在 `sdd`（`scope: project`，需要本 repo `openspec/` 目錄與 `spectra`
CLI），但 Step 0 / Step 0.5 / Step 2a 會以**skill 名稱**動態 dispatch `event-storming`、
`problem-frames`、`qa-test-design`——三者都已搬進 `methodology` pack（`ADR-0006`）。只裝
`sdd@yibi-stack` 而未裝 `methodology@yibi-stack` 的使用者，跑到 Step 0.5 會在
`problem-frames` 方法論檔案讀不到時得到明確的 `[FAIL]` 訊息（`spectra-amplifier/SKILL.md`
Step 0.5 決策表已載明安裝指令），不會靜默降級。

`scripts/lint_plugin_layout.py` 的 `CACHE_KEY_EXCEPTIONS` 精確登記了這第三個依賴
（`("plugins/sdd/skills/spectra-amplifier/SKILL.md", "methodology")`），讓「這是刻意的跨
pack 依賴」與「這是搬錯 pack 忘記改路徑」在 CI 上可以被機器分辨。前兩個依賴（`/handover` →
mycelium、`pr-retrospective` 讀 PR context）目前只在文件層說明，未被機檢——它們不涉及
`<pack>@yibi-stack` cache-key 字面引用，落在 `lint_plugin_layout.py` 的斷言範圍之外。

## Pack 對照表

| Pack | 分類 | 週期位置 |
|------|------|---------|
| `dev-cycle` | 流程 | `/newjob` 起始、`/pr-cycle-deep` 等 PR 生命週期、`/handover` 中斷續接 |
| `growth` | 知識 | `/pr-retro` 收尾、`mycelium` 跨 session 記憶 |
| `sdd` | SDD 實作工具（不動） | `/spectra-propose` → amplifier → apply，插在 `/newjob` 之後 |
| `methodology` | 方法論 | 依需要在任何步驟被引用（TDD、event-storming、problem-frames、qa-test-design） |
| `harness` | 環境品質 | 貫穿全程的橫切關注點（量測 / 強制 / 稽核） |
| `3rd-tools` | 第三方工具整合 | `/pr-cycle-deep` mob review 階段等處被呼叫，不專屬單一步驟 |

完整成員清單見各 pack 自己的 `README.md`；本文件只記錄跨 pack 的交手點與依賴，不重複列出
單一 pack 內部的完整組成，避免與各 README 的內容漂移。

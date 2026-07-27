---
id: "0006"
title: "Plugin Pack 分類軸 — 流程 / 知識 / 方法論 / 環境品質"
status: proposed
date: 2026-07-27
deciders: []
related:
  issue: TBD
  prs:
    - number: 344
      note: "PR-0：分類前置護欄（lint_plugin_layout.py + bootstrap 執行期測試）"
---

## Context

### 觸發事件

使用者問「`/newjob` 應該屬於 `dev-cycle`（原 `pr-flow`）而不是 `growth`，為什麼當初被分到
`growth`？」追查後發現不是單一誤放，是**分類軸選錯，且用一句假描述正當化了它**：

- 分類發生在 commit `f307e93`（2026-05-16，PR #3「reorganize skills into 7 plugin packs」）。
  commit message 直接寫「`growth`: handover, handover-back, newjob」——三個一起搬，不是逐個評估。
- `plugins/growth/README.md`（PR #3 當時）寫 `/newjob` 會「啟動新工作 session，**初始化
  mycelium**」。但 `commands/newjob.md` 自最早版本（PR #43）至今**從未呼叫任何 mycelium /
  session-memory**——它唯一呼叫的是 `local_port_manager`（當時在 `util` pack，現在
  `dev-cycle`）。
- 這不是「文件寫舊了」：文件是**為了正當化結構決策而寫**，從未描述過真實行為。

### 舊分類軸為何不可靠

當時的分類軸是「session 生命週期」——這條軸**對 repo 裡幾乎每個工具都成立**，因為每個工具都
發生在某次 session 裡。一條軸如果無法排除任何東西，它就不是判準，是事後合理化的空間。這正是
它需要一句假 README 來撐的原因：軸本身不會告訴你 `/newjob` 該不該在 `growth`，於是有人寫了一
句聽起來合理的話來填補這個空白。

### 換軸後現行分類的破口（換軸前的診斷）

| 現況（換軸前）| 問題 |
|------|------|
| `/newjob`（建 worktree）在 `growth`，`/clean-wt`（拆 worktree）在 `pr-flow` | 同一資源的 create/destroy 切在兩個 pack；`newjob.md` 自己就指向 `/clean-wt` |
| `/handover` / `/handover-back` 在 `growth` | 是週期**中斷與續接**的流程機制，不是知識累積 |
| `pr-retrospective` / `pr-control-log` / `claude-md-prune` 在 `pr-flow` | 是**從做完的事萃取知識**，與 `learn` / `mycelium` 屬同一管線 |
| `local-port-manager` 在獨立的 `util` pack | 是 `/newjob` 的直接依賴，卻與呼叫它的命令分屬兩個 pack |
| `event-storming` / `problem-frames` / `qa-test-design` 在 `sdd` | 三者皆為可攜方法論（`type: know`, `scope: global`），不讀 `openspec/`、不呼叫 `tasks/*`，留在 `sdd` 只因 `spectra-amplifier` 會 dispatch 它們，不是因為內容綁定 SDD |
| `ci-triage` 在 `tdd` | 是操作性的 CI 失敗診斷漏斗，不是測試方法論，與 `tdd-kentbeck` / `flutter-tdd` 放在一起純屬歷史巧合 |

## Decision

### 主判準：產出的是狀態變更，還是可重用記錄？

新分類軸放棄「這個工具做什麼類型的事」（功能分類，永遠有例外），改用一個**可檢驗的問句**：

> 這個 skill / command 執行完後，它改變的是 **repo / PR / worktree 的狀態**，還是留下一份
> **可以在下次獨立於這次執行被讀取、複用的記錄**（rule、lesson、DB row）？

依此把 pack 分成四類：

| 類別 | 判準 | Pack |
|------|------|------|
| **流程（process）** | 產出狀態變更：branch、PR、worktree、commit | `dev-cycle` |
| **知識（knowledge）** | 產出可重用記錄：rule、typed lesson、mycelium DB row、control log | `growth` |
| **方法論（methodology）** | 純參考讀物：不改任何專案狀態，跨專案可攜，讀了照做 | `methodology` |
| **環境品質（harness）** | 量測 / 強制 / 稽核 agent 自身執行環境的品質，是前三類的橫切關注點 | `harness` |
| （不動）SDD 實作工具 | 需要本 repo `openspec/` 目錄與 `spectra` CLI 才能跑 | `sdd` |
| （不動）第三方工具整合 | 與外部 AI 服務（Codex / Gemini）的介接層，自成一類 | `3rd-tools` |

這條軸與舊軸的差別在於：**它會排除東西**。`spectra-amplifier` 讀了 `openspec/`、呼叫
`spectra` CLI，兩者都不成立方法論的「跨專案可攜」判準，所以它不進 `methodology`——即使它
`type: know`。`bash-anti-patterns` 是知識型 skill，但它服務的是「agent 執行環境本身的
品質」，不是某次開發週期的流程或知識產出，所以它進 `harness` 而非 `growth`。

### 次判準：`methodology` 與 `sdd` 的分界用 `scope`，不用 `type`

`methodology` 家族全部是 `type: know`，但 `spectra-amplifier`（同樣 `type: know`）必須留在
`sdd`——若把 `type` 當主判準，這條規則第一天就對不上實際內容，重蹈舊軸的覆轍。

實際分界是 frontmatter 既有的 `scope` 欄位（`.claude/rules/11-skill-authoring.md` 定義：
`scope: project` = 需要本 repo 的資源才能跑）：

| skill | type | scope | 去向 |
|---|---|---|---|
| `tdd-kentbeck` | know | global | `methodology` |
| `flutter-tdd` | know | global | `methodology` |
| `event-storming` | know | global | `methodology` |
| `problem-frames` | know | global | `methodology` |
| `qa-test-design` | know | global | `methodology` |
| `spectra-amplifier` | know | **project** | 留 `sdd` |
| `figma-design-sync` | tool | **project** | 留 `sdd` |

**`scope` 只在方法論家族內部使用，不是整個分類軸的主判準**——`dev-cycle` 裡有 6 個
`know` + `global` 的 skill（`bump-version`、`issue-triage`、`mob-code-review-only`、
`pr-cycle-deep`、`pr-review-cycle`、`verify-done`），單用 `scope` 會把它們也拉進
`methodology`，不合意圖。主判準永遠是上面的四分軸；`scope` 只回答「這個 methodology 候選是
可攜參考，還是綁定本 repo 的 SDD 工具」這一個更窄的問題。

### 被否決的替代方案

**維持「session 生命週期」軸，只修正個別誤放。** 被否決，理由見上文「舊分類軸為何不可靠」：
軸本身無法證偽，修正誤放只是把同一個問題往後延——下次新增 skill 時，分類者依然沒有可檢驗的
判準可用，只能靠當次的直覺，而直覺會再度需要一句合理化的文字來填補判斷依據的空白。

**按 `type` frontmatter 分類。** 被否決：`spectra-amplifier` 是本 repo 最強的反例——
`type: know` 卻必須留在 `sdd`，因為它讀 `openspec/`、呼叫 CLI，不具備方法論的可攜性。若寫進
ADR 當規則，規則與內容當場矛盾。

**跨 pack 相依（例：`dev-cycle` 宣告依賴 `growth` 的 mycelium）。** Claude Code plugin
系統沒有 plugin 間相依機制（ADR-0004 已記錄同一事實）。跨 pack 的執行期依賴（如
`/handover` 寫 `growth` 的 mycelium DB、`spectra-amplifier` dispatch `methodology` 的
`problem-frames`）改用文件層的 Prerequisites 說明 + `[FAIL]` 訊息指名安裝指令解決，而非假裝
可以宣告相依。

## Consequences

### 正面

- 分類軸現在可以回答「這個新 skill 該進哪個 pack」，而不需要事後合理化：問「它變更狀態還是
  留下記錄」「它是否跨專案可攜」，答案直接對應到 pack。
- 消除了促成本次重整的假描述（`growth/README.md` 的「`/newjob` 初始化 mycelium」），以及後續
  在委外執行 PR-2 時同一份任務包草稿中**再次意外重寫出的同一句話**（於獨立驗證階段抓到並修
  正）——後者本身印證了這條分類軸解決的問題有多容易在無意間復發。
- `harness` pack 把「量測（`harness-eval`）/ 強制（AP1/AP2 hooks）/ 稽核（
  `bash-hygiene-audit`）」三個原本分散在空殼 pack、獨立 pack、與 repo-root 孤兒之間的資產收攏
  成一個語意成立的整體。

### 負面 / 風險

- **`scope` 次判準若被誤讀為主判準，會產生錯誤分類**——已在上文明確排除 `dev-cycle` 的 6 個
  `know`+`global` 反例，但下一位分類者仍可能忽略這個排除條件。緩解：本 ADR 與
  `.claude/rules/11-skill-authoring.md` 皆需保留完整的判準說明，不能只留結論表格。
- **`dev-cycle` 成為全 repo 最大的 pack**（9 commands + 10 skills）——這是「一個 pack 走完整
  開發週期」的直接後果，不是意外，但若持續累積可能需要在流程軸內部再切子群（例如
  `pr-cycle-*` / `mob-code-review-only` review 家族）。本 ADR 不預先決定是否拆分，留給
  未來視累積情況再議。
- **`CACHE_KEY_EXCEPTIONS`（`scripts/lint_plugin_layout.py`）成為分類軸妥協的具體出口**——
  `spectra-amplifier` 留在 `sdd` 但 dispatch `methodology` 的 `problem-frames`，產生一筆
  精確 `(檔案, pack)` 例外。每新增一筆例外都代表「流程/知識/方法論/環境品質」四分軸與「哪個
  pack 物理上放哪些檔案」出現了一次分歧，需要在 code review 時個別檢視是否合理，而非累積成
  慣例。

## Verification

分類軸落地的機檢護欄見 `scripts/lint_plugin_layout.py`（PR #344 / PR-0）：pack 自我引用
一致性、marketplace.json 雙向對應、版本 lockstep。分類軸本身（「這個 skill 該進哪個 pack」）
無法機檢，是設計判斷——本 ADR 存在的目的正是把該判斷的依據寫下來，供未來新增 skill 時對照。

跨 pack 執行期依賴（`spectra-amplifier` → `methodology`、`/handover` → `growth` 的
mycelium DB）見 [docs/dev-lifecycle.md](../dev-lifecycle.md)。

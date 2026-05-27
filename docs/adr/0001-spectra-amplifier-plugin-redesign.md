---
id: "0001"
title: "Spectra Amplifier Plugin 重設計 — 對齊 yibi-mvp ADR-0006/0008 (Wave D)"
status: accepted
date: 2026-05-27
deciders: [howie]
related:
  upstream_adr:
    - repo: heyu-ai/yibi-mvp
      id: "0006"
      title: "Spectra 五尺度約束升級與 Upstream Drift 防護"
      status: accepted
      date: 2026-05-17
    - repo: heyu-ai/yibi-mvp
      id: "0008"
      title: "BDD Spec-Test Traceability -- docstring trace 機制"
      status: accepted
      date: 2026-05-19
  pr: TBD
---

## Context

### 背景

`yibi-stack/plugins/sdd/` 的 `spectra-amplifier` skill 存在四個結構性問題：

1. **qa-test-design 從未真呼叫**：skill 的 Layer 2 與 Layer 5 都只「文字提及」
   `qa-test-design` Skill，沒有實際 `Skill` tool dispatch。
2. **FS 散文層與 Gherkin scenarios 同時存在**：兩者描述同一 behavior，要維護兩份，
   易 drift。
3. **Plugin 不 self-contained**：amplifier 使用的 TC-ID 命名規則依賴 host project 的
   `.claude/rules/09-test-conventions.md`，plugin 安裝到其他 project 後規則不存在。
4. **缺乏 ADR + Event Storming 完全缺席**：plugin 沒有記錄為何選 5 層設計；
   領域發現是 amplifier 前置階段，但 skill 內無說明。

### Wave D 願景（引自 yibi-mvp ADR-0006 Postscript）

> Wave D（A/B/C 完成後）：將整套方法論（五尺度 + drift 防護 + agent boundary +
> BDD trace）抽出為 `.claude/skills/spectra-scale-constraints/` 可重用 skill

本次 yibi-stack 端的落地目標即是 Wave D：將 yibi-mvp ADR-0006/0008 已驗證的方法論
移入 `plugins/sdd/`，讓任何 host project 安裝 plugin 即可直接套用。

### 引用 ADR-0006：五尺度（Teddy Chen 五層粒度語言）

以下引自 yibi-mvp ADR-0006 § 一、Teddy 五尺度約束疊加在 spectra-amplifier：

> | 尺度 | 對應概念 | 在 Spectra 中的對應位置 |
> |------|---------|----------------------|
> | 需求（Requirement） | 業務目標、使用者痛點 | `proposal.md` ## Why 段落 |
> | 大（Epic/Feature） | 可交付的完整功能群 | `proposal.md` ## What Changes 段落 |
> | 中（User Story） | 單一 Actor 一個 Goal，3-5 天可完成 | `specs/<cap>/spec.md` User Stories（L1）|
> | 小（Scenario） | BDD 可執行情境，1 個 Story 含 3-7 個 Scenario | `specs/<cap>/spec.md` Scenarios（GIVEN/WHEN/THEN）|
> | 微（Micro Task） | 最小實作單元，不超過 4 小時 | `tasks.md` 單一 task 行 |

### 引用 ADR-0008：docstring trace 模式

以下引自 yibi-mvp ADR-0008 § Decision — Option A Docstring Trace（採用）：

> 在 spec 的 `#### Scenario:` heading 加顯式 slug，在 pytest 測試函式 docstring 加
> `spec: <cap>#<slug>` 引用：
>
> ```markdown
> #### Scenario: require-current-password -- 必須提供當前密碼
> ```
>
> ```python
> def test_password_change_requires_current_password():
>     """
>     spec: account-settings-page#require-current-password
>     """
> ```
>
> 為何選 Option A：
>
> - 零新 dependency（pytest-bdd 需要 3 個 pip package + .feature 語法學習成本）
> - 不改現有測試風格（pytest 函式保持 Pythonic）
> - 漸進採用：現有 Scenario 可逐批補，不需一次全改

---

## Decision

**結論**：分兩個 phase 重設計 `plugins/sdd/` 的 spectra-amplifier skill。

### Phase 1 — 方法論層（本次 PR）

1. **amplifier 重構為 Step 0-5 結構**（取代原 Layer 1-5）：
   - Step 0：Domain Discovery 前置檢查
   - Step 1：行為規格層（US + AC + Gherkin scenarios，移除 FS 散文層）
   - Step 2：測試設計層（**真實 `Skill` tool dispatch qa-test-design**）
   - Step 3：設計輔助層（Data Model + API）
   - Step 4：範圍與假設
   - Step 5：完工標準（SMK-NNN smoke tests + Traceability matrix）
2. **Plugin self-contained**：新增 `test-convention.md` + `bdd-trace-convention.md`
3. **testplan.md** 作為 amplifier ↔ qa-test-design 的 handoff artifact
4. **event-storming skill 雛形**（接口 + handoff artifact）
5. **vendor check_spec_coverage.py scanner**（參數化路徑）
6. **docs/adr/0001** 本文件

### Phase 2 — 工具鏈層（後續 PR，見 Phase 2 Backlog）

- Marker Block 規範（ADR-0006 Layer 1）
- Vendored Baseline（ADR-0006 Layer 2）
- 三時機偵測（ADR-0006 Layer 3A/B/C）
- spectra-drift skill 移植
- spectra-strict.sh 完成（yibi-mvp 端是 0 bytes stub）

---

## Specific Decisions and Trade-offs

### FS 移除 vs. 保留

**決定**：移除 FS-NNN 散文規格層，Gherkin scenarios 為唯一行為規格記錄。

**理由**：FS 與 Gherkin 描述同一 behavior，維護兩份必然 drift。
yibi-mvp ADR-0008 選擇 Gherkin scenarios（`#### Scenario:`）作為 spec 端主表達，
plugin 對齊此決策。

### Smoke Test 重命名 SMK

**決定**：amplifier Step 5 的 `ST-NNN`（Smoke Test）改為 `SMK-NNN`。

**理由**：`ST` 在 qa-test-design 的 technique list 中代表 State Transition（ISTQB 標準術語）。
更動 qa-test-design 的 API 代價更高；改 amplifier 端影響最小。
既有 `ST-NNN` 視為 legacy，新 spec 才套用 `SMK`。

### Plugin self-contained vs. 引用 host rules

**決定**：plugin 自帶 `test-convention.md`；detect host convention，有則優先，沒有則用預設。

**理由**：plugin 安裝到沒有 yibi-stack `.claude/rules/` 的 host 時，TC-ID 規則不存在。
自帶 convention 讓 plugin 無外部依賴即可正常運作。

### docstring trace vs. pytest-bdd

**決定**：採用 ADR-0008 已決策的 Option A（docstring trace），不引入 pytest-bdd。

**理由**：直接引自 ADR-0008（見上方引用）：零新 dependency、不改測試風格、漸進採用。

---

## Alternatives Considered

- **保留 FS + Gherkin 並行**：兩處同步必 drift；使用者明確要求 Gherkin 為主。
- **不 vendor scanner**：plugin 失去 self-contained；host 沒有 yibi-mvp 結構就無法用。
- **TC-ID 雙層系統（Design + Execution）**：ADR-0008 已決策 docstring trace，
  重新發明違反「跨 repo ADR 為決策來源」原則。
- **amplifier 內 inline Event Storming**：amplifier 已 21k bytes；
  領域發現是獨立階段，職責分離較清晰。

---

## Consequences

**好**：

- Plugin 安裝後即 self-contained，不依賴 host project 的私有規則
- amplifier Step 2 真實觸發 qa-test-design，test coverage 有系統性輸入
- Gherkin scenarios 成為唯一行為規格表達，消除 FS/Gherkin drift
- testplan.md 是 spec ↔ test 追蹤的單一來源
- check_spec_coverage.py scanner 讓 test trace rate 可量化

**壞 / 代償**：

- 既有 changes 目錄（原 Layer 1-5 格式）與新 Step 0-5 不同，但 amplifier 是
  forward-only，舊 change 繼續有效，不需 migrate
- ST-NNN → SMK-NNN rename 讓既有 specs 的舊 ST-NNN 成為 legacy 格式
- Phase 2（Drift 防護工具鏈）仍未到位；Phase 1 先補方法論層

**中性**：

- yibi-mvp 自家 amplifier 可逐步對齊 plugin 版本（後續獨立決策）

---

## Addendum — Step 1c Parallel Subagent（2026-05）

**設計演進**：本次（Phase A）為 Step 1c 引入 `sdd:gherkin-scenario-writer` Task subagent，
實現多 capability feature 的 Gherkin scenarios 平行展開。

**決策依據**：三軸 rubric（state sharing / side effects / parallelizability）對 Step 1c 的評估結果：

- State sharing：各 capability 的 Gherkin 展開只需自身 AC + 四元素結果，不需跨 capability 狀態 — 偏 Subagent
- Side effects：每個 capability 寫入獨立的 `specs/<cap>/spec.md` — 偏 Subagent
- Parallelizability：N 個 capability 完全獨立，無跨 capability 依賴 — 強烈偏 Subagent

三軸全偏 Subagent → 升級。

**Architecture**：

- N == 1：spectra-amplifier inline 展開（避免 single-invocation overhead）
- 2 ≤ N ≤ 5：同一 message 發 N 個 Task tool，平行 dispatch
- N > 5：降回 inline sequential 並警告使用者

**新增檔案**：`plugins/sdd/agents/gherkin-scenario-writer.md`

- `model: sonnet`（重複結構化生成，中等認知負擔）
- `tools: [Read, Write]`（讀既有 spec 防衝突，寫入 spec.md）

**harness-eval D9 影響**：

- Phase A 後：D9 從 0/2 升到 1/2（subagent 職責清楚）
- Phase B（qa-test-designer subagent）後：D9 達 2/2（exploration vs editing 拆開）

**後續 Phase**：Phase B 為 qa-test-design 加入雙軌設計（SKILL.md 人類入口 + subagent 程式介面）；
Phase C/D 為 Step 0/Step 3 引入獨立 subagent。

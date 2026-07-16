# Rules English & Recall Audit：Token 效率優化的系統性研究

**日期**：2026-05-24
**背景**：yibi-stack agent-facing surface 以中文撰寫，always-loaded 部分每 session 產生顯著 token 過耗
**結論**：4-PR 路線圖，PR-A/B 已交付（基礎設施層），PR-C/D 待執行（語言層翻譯）

> **2026-07-16 更正（PR #250）**：本文以下所有「`globs:` frontmatter → 按需載入」的敘述都是**錯的**，
> 不影響本文的翻譯策略結論，但影響 §1.1 的載入分類與 §2 的 token 基線數字。`globs:` 從來不是
> Claude Code 認得的 key（正確的是 `paths:`，值為 YAML list），會被靜默忽略，因此撰寫本文時
> rules **04-11 其實全部都是 always-loaded**，而非本文所述的 on-demand。實測（`claude -p` 探針
> 兩次，僅 cwd 不同）：修正前載入 14 個 rule，修正後 6 個。本文原文保留不改動，僅加註此更正。

---

## 1. Problem Statement

### 1.1 Surface Area 量化

| Layer | 目錄 | 說明 |
|-------|------|------|
| Rules（always-loaded） | `.claude/rules/01,02,03,13,15,16` | 無 globs，每 session 全量載入 |
| Rules（on-demand） | `.claude/rules/04-11` | 有 `globs:` frontmatter，按路徑觸發 |
| Plugins SKILL.md | `plugins/**/SKILL.md` | Skill invoke 時載入 |
| CLAUDE.md | `.claude/` 根目錄 | 每 session 全量載入 |

**PR-B（#50）後 always-loaded rules 數量**：6 條（rule 12 移至 docs/，rule 14 合併入 rule 13）

**6 條 always-loaded rule 字元數（origin/main，2026-05-24 量測）**：

| Rule | 行數 | 字元數 |
|------|------|--------|
| 01-language-and-tone.md | 41 | 1,062 |
| 02-error-and-import.md | 88 | 2,469 |
| 03-security.md | 72 | 2,047 |
| 13-bash-anti-patterns.md | 751 | 30,332 |
| 15-irreversible-operations.md | 184 | 8,839 |
| 16-allowlist-hygiene.md | 225 | 11,170 |
| **合計** | **1,361** | **55,919** |

### 1.2 Token 成本模型

Claude tokenizer 對不同語言的 token 密度差異顯著：

- **CJK（中文）**：約 1.0–2.5 tokens/char（cl100k_base 近似值）
- **English prose**：約 0.25–0.33 tokens/char
- **Code/bash/paths**：約 0.25 tokens/char（英文程式碼密度）

rules 的中文 prose 比例約 50–70%，code block 佔其餘部分。

**Token 量化（2026-05-24 baseline 實測，tiktoken cl100k_base）**：

| Rule file | Chars | Tokens (pre-PR-C) | t/char |
|-----------|-------|-------------------|--------|
| `01-language-and-tone.md` | 684 | 408 | 0.596 |
| `02-error-and-import.md` | 1,887 | 883 | 0.468 |
| `03-security.md` | 1,495 | 735 | 0.492 |
| `13-bash-anti-patterns.md` | 21,657 | 11,810 | 0.545 |
| `15-irreversible-operations.md` | 5,777 | 3,398 | 0.588 |
| `16-allowlist-hygiene.md` | 8,218 | 4,118 | 0.501 |
| **TOTAL** | **39,718** | **21,352** | **0.538** |

| Metric | 值 |
|--------|-----|
| 翻譯前 always-loaded rules token 總計 | **21,352** tokens |
| 翻譯後 always-loaded rules token 總計 | TBD（PR-C 完成後重跑 baseline script）|
| 預計節省比例 | ~35-45%（t/char 從 0.538 → 約 0.25-0.33 English prose）|
| 預計每 session 節省 | ~7,000-9,500 tokens |
| PR-C 通過門檻 | <= 14,946 tokens（降幅 >= 30%）|

詳細基線數據：`openspec/changes/rules-english-recall-audit/tokens-baseline.md`

### 1.3 Always-loaded vs On-demand 機制

Claude Code 的 `.claude/rules/` 讀取機制：

- **無 `globs:` frontmatter**：每次 session 啟動時全量載入（always-loaded）
- **有 `globs:` frontmatter**：只在匹配路徑的工具呼叫（Read/Edit/Write）時載入

Rules 01/02/03/13/15/16 均無 `globs:`，屬於 always-loaded 集合。
Rules 04/05/06/07/08/09/10/11 均有 `globs:`，按需載入，**不在本次翻譯範圍**。

---

## 2. Prior Art（為何先前考量的方案被否決）

| 方案 | 否決理由 |
|------|---------|
| 全 16 條 rule 翻譯 | Rules 04-11 有 `globs:` path-based 觸發，翻譯後失去中文 description 觸發詞，pre-commit/skill-authoring 自動載入率下降 |
| 純 tiktoken 量測 | OpenAI tokenizer，對 Claude tokenizer 不精準；`anthropic.messages.count_tokens` 才是正確工具 |
| 新建 `tasks/token_audit/` task module | 量測邏輯只需一次性 script（$CLAUDE_JOB_DIR），不值得建立持久 task module |
| Rule 中英雙份維護 | 維護成本 2x；人類學習走 `/recall` 召回 session-memory retro 原文（PR-A 已建立此基礎設施）|
| 只動 description，不翻 body | Agent 在工作中讀取的是 body prose，節省效果不顯著 |

---

## 3. Decision Framework

| 決策軸 | 評估選項 | 採用 | 理由 |
|--------|---------|------|------|
| 翻譯範圍 | 全 16 條 / 無 globs 6 條 / 只 description | **無 globs 6 條** | 精準命中 always-loaded，不影響 path-based 觸發 |
| 量測工具 | tiktoken / anthropic count_tokens / 月帳單 | **anthropic count_tokens** | 唯一對 Claude tokenizer 精準的工具 |
| 量測基礎設施 | 新 task module / one-shot script | **one-shot script（$CLAUDE_JOB_DIR）**| 量測邏輯只跑幾次，不值得 module overhead |
| 人類學習路徑 | Rule 中英並存 / /recall 召回原文 | **/recall 召回** | PR-A #48 已建立 audit log + recall 基礎設施 |
| Description 語言 | 純英文 / 純中文 / 雙語 | **雙語（英文主體 + 中文 trigger keywords）** | 英文主體減少 token，中文 trigger 保留中文喚起能力 |
| CLAUDE.md | 翻譯 / 不翻 | **不翻（PR-E 候補）** | 不在 6 條 always-loaded rule 集合內；PR-C/D 完成後再評估 |

---

## 4. Methodology — 4-PR 路線圖

### PR-A（#48）— 基礎設施層 ✅ MERGED 2026-05-23

**目標**：建立量測與學習基礎設施，讓「翻譯前後效果可量化」。

| Deliverable | 說明 |
|-------------|------|
| Audit log v2 | `rule_id / outcome / cmd_snippet` 三元組，追蹤 hook 攔截歷史 |
| `/recall` command | 召回 session-memory retro，取代 always-loaded rule 的學習路徑 |
| Pre-commit gate | markdownlint + ruff 防止規則退步 |

### PR-B（#50）— 結構優化層 ✅ MERGED 2026-05-23

**目標**：減少 always-loaded rule 數量，降低翻譯工作量。

| Deliverable | 說明 |
|-------------|------|
| Promotion gate | 從 `/pr-retro` → lesson → rule 的升級路徑標準化 |
| Rule 14 → 13 合併 | Shell quoting hygiene 併入 bash anti-patterns（同主題，減少載入成本）|
| Rule 12 → docs/ 移動 | Auto-handover 規範移至非 always-loaded 位置 |

結果：always-loaded rules 從 **8 條** 降為 **6 條**（PR-B 前：01/02/03/12/13/14/15/16；PR-B 後：01/02/03/13/15/16）。

### PR-C — 語言轉換層（未啟動）

**目標**：6 條 always-loaded rule 英文化，直接降低每 session token 使用。

**執行順序（由小到大，方便 review）**：

| # | Rule | 字元數 | 翻譯重點 |
|---|------|--------|---------|
| C1 | 01-language-and-tone.md | 1,062 | self-referential：rule 本身改寫成「分層語言策略」（agent prompt 英、user-facing 中）|
| C2 | 03-security.md | 2,047 | 純技術規範，翻譯風險低 |
| C3 | 02-error-and-import.md | 2,469 | 含 code 範例（保留），prose 部分翻英 |
| C4 | 15-irreversible-operations.md | 8,839 | 含 decision table，table cell 翻英 |
| C5 | 16-allowlist-hygiene.md | 11,170 | 含官方文件 quote 段（保留 quote 原文 + 英文 commentary）|
| C6 | 13-bash-anti-patterns.md | 30,332 | 最大檔案，含 30+ case study；分批 commit |

**通用翻譯約束**：

- 全形標點 → 半形（依新 rule 01 分層規則：English prose 用半形）
- Emoji-free（依 rule 13 AP2）
- 保留 code identifiers、file paths、bash commands、`globs:` frontmatter 值
- 保留每個 rule 末尾的歷史引用（PR 編號、retro 日期）

### PR-D — Plugin 語言轉換層（未啟動）

**目標**：23 個 `plugins/**/SKILL.md` body 英文化。

**範圍**：frontmatter `description` 改雙語，body prose 翻英。

**執行順序（依預期 invoke 頻率）**：

| # | Plugin | 優先理由 |
|---|--------|---------|
| D1 | bash-hygiene | Always-on agent guidance（bash-anti-patterns, protect-push）|
| D2 | pr-flow | 高頻 invoke + 大檔（pr-review-cycle*, review, pr-retrospective）|
| D3 | growth | 高頻 invoke（session-memory, handover, newjob, learn）|
| D4 | sdd | 中頻（spectra-amplifier, qa-test-design）|
| D5 | harness / tdd / util / 3rd-tools | 低頻，最後處理 |

---

## 5. Verification Design — 五層觀測

### V1 — Token 量化（每 PR 必跑）

每個 PR description 必含 before/after token 表格（量測工具：`anthropic.messages.count_tokens`）：

```markdown
| File | Before | After | Saved |
|------|--------|-------|-------|
| 01-language-and-tone.md | TBD | TBD | TBD |
| ...  | ...    | ...   | ...   |
| TOTAL | TBD  | TBD   | TBD   |
```

**通過門檻**：PR 範圍內 token 總數下降 ≥ 30%。

### V2 — Trigger 行為 smoke test（每 PR 必跑）

新開 session（不繼承 context），測試以下中文 trigger 能否正確喚起對應 skill：

| 中文 trigger | 應喚起 skill |
|-------------|-------------|
| 「跑 PR cycle」 | pr-review-cycle |
| 「整理交班」 | handover |
| 「review 這個 PR」 | review-pr / pr-review-cycle |
| 「跑 TDD」 | tdd-kentbeck |
| 「掃 secrets」 | security-scanner |
| 「召回過去 lesson」 | /recall |

**通過門檻**：6/6 命中。任何 miss 代表 description 中文 trigger keywords 不足，需補充後重跑。

### V3 — Agent 行為 smoke test（PR-D 必跑，PR-C 抽樣）

對 3 個高頻 skill 跑 happy path：

1. `/pr-review-cycle` 對小 PR 跑完整流程
2. `/handover` 寫一筆交班
3. `/security-scanner` 掃一個 diff

**通過門檻**：output 結構（必填欄位、決策表 row 數、判斷流程順序）與翻譯前相當。

### V4 — Audit log v2 觀測（lagging indicator）

PR-C/D merge 後 7–14 天：

```bash
uv run python -m tasks.bash_hygiene_audit recent --since 14d
uv run python -m tasks.bash_hygiene_audit stats --by rule_id
```

確認：bash AP 攔截頻率不上升（rule 翻英不影響 hook 行為）；`/recall` 使用次數上升。

### V5 — `/recall` end-to-end

```bash
/recall rules-english-recall-audit
/recall audit log v2
/recall promotion gate
```

確認召回 handover dd7351ad / b24eda47 / a772efc7 / b188dd3d / eb33cf47。

---

## 6. Risk Analysis

| Risk | 可能性 | 緩解措施 |
|------|--------|---------|
| R1: Chinese trigger miss（中文 keyword 不足導致 skill 無法喚起）| 中 | V2 smoke test；description 雙語格式保留中文 trigger keywords |
| R2: 翻譯誤義（技術細節語意偏移）| 低-中 | V3 agent smoke test；mob review + Gemini 第二眼 review |
| R3: Rule 01 self-referential 翻譯混亂（rule 本身規範「何時用中文」，改寫成英文後 rule 與自身矛盾）| 中 | C1 是第一個翻譯，先確立分層語言策略框架 |
| R4: PR-B main 落地狀態未確認（Step 0.1 發現本地 main 落後 origin/main 3 commits）| 已發現 | Step 0.1 第一動作（git pull + ls rules）|
| R5: OpenSpec proposal.md 空白導致規劃再次遺忘 | 已發生一次 | Step P1 建立 GitHub issue + pre-commit gate；Step 0.2 填內容 |
| R6: Token 量測工具選錯（tiktoken ≠ Claude tokenizer）| 低（已確認）| 使用 anthropic.messages.count_tokens |

---

## 7. Progress Snapshot（2026-05-24）

| PR | 範圍 | 狀態 | 日期 | Evidence |
|----|------|------|------|----------|
| PR-A #48 | audit log v2 + /recall + pre-commit gate | ✅ MERGED | 2026-05-23 | handover b24eda47, a772efc7, b188dd3d |
| PR-B #50 | promotion gate + rule consolidation（14→13, 12→docs/）| ✅ MERGED | 2026-05-23 | handover eb33cf47；gh pr view 50 確認 |
| PR-C | 6 條 always-loaded rule 英文化 | ⏳ NOT STARTED | — | 本研究完成後啟動 |
| PR-D | plugins SKILL.md body 英文化（23 個）| ⏳ NOT STARTED | — | PR-C 完成後啟動 |

**已驗證事實（2026-05-24 git 操作確認）**：

- `origin/main` 上 `.claude/rules/` 有 14 個 `.md` 檔案（PR-B 已落地）
- 本地 main 落後 origin/main 3 commits（#48, #49, #50），需 `git pull` 後才對齊
- OpenSpec change `openspec/changes/rules-english-recall-audit/` 存在但 `proposal.md` 仍是空模板（待 Step 0.2）

---

## 8. References

### Handover 脈絡鏈（按時間序）

| Handover ID | 類型 | 主題 |
|-------------|------|------|
| dd7351ad | discussion | 4-PR 路線圖原始來源（2026-05-23）|
| b24eda47 | implementation | PR-A 實作 |
| a772efc7 | review | PR-A mob review |
| b188dd3d | retro | PR-A retro |
| eb33cf47 | retro | PR-B retro |
| 2ebde7db（本次）| discussion | 發現本地 main 落後，plan v3 批准 |

### GitHub

- PR #48：`feat(pr-a): audit log v2 + /recall command + pre-commit gate`
- PR #50：`feat(pr-b): promotion gate + rule consolidation`

### 規格文件

- OpenSpec change：`openspec/changes/rules-english-recall-audit/`（proposal.md 待填）
- Plan v3：`~/.claude/plans/prompt-token-typed-candy.md`
- 風格參考：`docs/research/2026-05-05-gbrain-vs-session-memory.md`

---

## 9. Open Questions

| Question | 優先度 | 釐清時機 |
|----------|--------|---------|
| Q1：PR-B main 落地的 always-loaded rule 實際 token count（TBD baseline）| 高 | Step 0.3 baseline script 執行後 |
| Q2：CLAUDE.md 是否納入 PR-E（always-loaded，但不在 6 條 rule 範圍）| 中 | PR-C/D 完成後再評估 |
| Q3：plugins SKILL.md 雙語 description 是否需要自動化 lint（如 pre-commit 檢查 description 包含中文 trigger keywords）| 低 | PR-D 開始時評估 |
| Q4：翻譯後 rule 12/14 的 docs/ 副本是否也需英文化（PR-B 已移動但仍中文）| 低 | PR-C/D 完成後評估 |

---

*本文件在 Step P0 建立，token measurement section（1.2 TBD 欄位）待 Step 0.3 baseline script 執行後填入。*
*更新歷史：v1.0（2026-05-24）— 初始版本，9 sections，含 4-PR 路線圖完整脈絡。*

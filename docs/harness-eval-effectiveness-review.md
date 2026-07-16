# harness-eval 有效性檢驗報告

> 評估對象：`harness-eval` skill（`skills/harness-eval/SKILL.md` + `tasks/harness_eval/`）
> 目標 repo：yibi-stack 自身（dogfood）
> 日期：2026-05-30
> 方法：先方法論評論（C）→ 再實證跑一次（A）→ 最後擴充建議（B）
>
> **2026-07-16 更正（PR #250）**：本文把「14 個 rule 每回合全載入」歸因於 **glob 自動載入**
> ——機制講錯了。`globs:` 從來不是 Claude Code 認得的 key（正確的是 `paths:`），它被靜默忽略，
> 所以那 14 個檔案是**因為 frontmatter 失效而無條件載入**，不是因為 glob 觸發。
>
> 有意思的是：**本文的觀察是對的，而且正是這個 bug 的最早證據**——「always-on ≈ 3007 行、
> 14 個 rules 全載入」如實記錄了誤載狀態，只是當時把它讀成設計而非缺陷，因此沒有追下去。
> §3「活證據」的行數與 D7 的 6/7 評分都是修正前的數字；修正後 always-loaded 集合為
> 01/02/03/13/15/16 共 6 個檔案。本文原文一字未改，僅加註此更正。

## TL;DR

1. **能有效評「結構齊不齊」**：D1–D10 hybrid（機械 69 + 語意 46 = 115）對「有沒有 hook /
   deny list 完不完整 / 測試有沒有意義」鑑別力堪用，且對本 repo 仍會抓出真缺口（D1 行數超標、
   D3 deny 不全），不是純橡皮圖章。
2. **不能評「效能 / token 平衡」**：完全沒有 context/token economy 維度。最關鍵的
   agentic 效能變數——always-loaded context 預算——量不到。
3. **活證據**：yibi-stack 自身 always-on context ≈ **3007 行**（CLAUDE.md 216 + 14 個
   glob 自動載入 rules，rule 13 占 819 行、rule 11 占 587 行）。harness-eval 把這 2800 行
   rules 在 D7 當成**品質加分**（6/7），對其 token 成本**零偵測**；D1 只盯 CLAUDE.md 那 216 行。
4. **計分哲學偏差**：加總式 /115 獎勵「東西多」而非「剛好」。本 repo 是「越加越高分」的
   範例，沒有 over-engineering 懲罰。

---

## Part C — 方法論評論

### C-0 設計優點（先肯定）

- **Hybrid 機械 + 語意**：機械分確定（`tasks/harness_eval/scanners/*.py`，10 個 scanner），
  語意分補品質判斷（SKILL.md Step 3 rubric）。方向正確：純機械會獎勵「填表」，純語意不穩定。
- **D5 已內建「presence ≠ effectiveness」自覺**：zero-gate（只有 `result is not None` 類存在性
  assertion → 語意分強制歸 0，SKILL.md:90）、mutmut TODO（D5<4 觸發，SKILL.md:162）。
  這恰是使用者在「整個工具層級」追問的同一個問題，只是目前只落實在 D5。
- 維度覆蓋對齊 Anthropic「Large Codebases Best Practices」（D9 subagents、D10 navigation）。

### C-1 加總式計分獎勵「多」而非「剛好」

總分 /115 是 additive：repo 靠「多加 hook / rule / skill / subagent」就能堆高分，
沒有 over-engineering 懲罰或邊際遞減。`scan_rules()` 對 14 個 rule 檔給 D7=6/7
（`scanners/rules.py:42-60`，rule 越多越接近滿分上限），但「14 個 rule、合計 2800 行、
每回合 glob 全載入」對 agentic 效能其實是**成本**，不是純效益。
「harness 工程程度」應獎勵 *right-sized*，現行 rubric 會把 *maximal* 誤判為 *better*。

### C-2 不區分 always-loaded vs progressively-disclosed context（→ token 缺口根因）

- D7 的 rules 由 glob 每回合自動載入、吃掉 context 預算；harness-eval 只數「幾個檔、
  有無編號、有無 prune」（`scanners/rules.py`），不衡量 always-on token budget。
- D1 只檢查 `CLAUDE.md ≤ 200 行`（`scanners/claude_md.py:106`），完全不看 rules、
  memory、skill description 這些同樣 always-on 的部分。
- 三者（CLAUDE.md + 自動載入 rules + skill descriptions）共同競爭 context 視窗，
  harness-eval 沒有任何維度衡量「always-on 占用」與「按需載入比例」。

### C-3 `effort:` 偵測只看「有沒有」不看「對不對」

D4 語意（SKILL.md:86）檢查 skill 是否「有設」`effort:` frontmatter，但不檢查 effort 等級
是否與 skill 實際 token / 工作量相稱，也沒有回饋閉環。這是「presence 偵測」而非「平衡衡量」
的典型例子。

### C-4 百分比等級與絕對分脫鉤

`等級依百分比`（SKILL.md:173）：小 repo 三個維度滿分即可評 Excellent，
缺乏「依 repo 型態決定哪些維度適用 / 加權」的概念。一個只有 CLAUDE.md + 1 個 hook 的
迷你 repo 可能比一個維度齊全但每項略缺的大 repo 拿到更高百分比。

### C-5 作者—評估對象同源的循環風險

rubric 與 yibi-stack 慣例同一作者（例如 D5 factory helper 偵測寫死 `def make_` 前綴，
正是 rule 09 的本地慣例）。工具可能被調成「剛好讓本 repo 通過」。需在 A 段以實測檢視
construct validity——見 A-3。

### C-6 為什麼 token 平衡「難以」機械化（誠實邊界）

- token 成本是 **runtime/動態**（依每次 session 實際載入什麼而定），harness-eval 是
  **static scan**——本質落差，無法精準。
- 「平衡」需要 baseline（任務是什麼、品質門檻多高），static scan 無 ground truth。
- **但可用靜態 proxy 近似**（串接 B）：always-loaded token 估計（CLAUDE.md + glob 命中
  rules + skill description 字數 × 係數）、progressive-disclosure 比例、CLAUDE.md↔rules
  冗餘偵測。這些是可機械化的，只是目前完全沒做。

---

## Part A — 實證驗證（對 yibi-stack 跑一次）

執行：`uv run --directory "$PWD" python -m tasks.harness_eval scan --target-dir "$PWD" --format json`

### A-1 機械分實測（total 51 / 69 ≈ 74%）

| 維度 | 機械分 | 關鍵 finding |
|---|---|---|
| D1 CLAUDE.md | 4/8 | WARN 行數 216 > 200；WARN 無 subdir CLAUDE.md；新鮮度 OK |
| D2 Hooks | 11/13 | PreToolUse/PostToolUse/SessionStart/PreCompact + reflection hook 已配置；WARN Stop 未設定 |
| D3 Settings & 權限 | 3/6 | deny 覆蓋 3/5（rm、force push、reset --hard）；**WARN allow list 未設定** |
| D4 Skills & Commands | 5/8 | 25 skills frontmatter 完整、8 plugin packs；**WARN 無 scoping 欄位**；**WARN `.claude/commands/` 不存在** |
| D5 Testing & CI | 5/7 | 45 測試檔、CI 存在；WARN hook 未連結測試；factory_helper_files 17 個 |
| D6 Git | 3/6 | branch 保護 hook 有效；WARN 無 `.claude/worktrees/` |
| D7 Rules | 6/7 | 14 規則檔、全編號；WARN 無 prune 機制 |
| D8 Security | 7/7 | .gitignore 含 .env/credentials；hook 無危險指令 |
| D9 Subagents | 4/4 | 4 個 subagent、全限制工具集、1 個 read-only explorer |
| D10 Navigation | 3/3 | ARCHITECTURE.md + @-mention + 目錄樹 |

語意分（agent 自評估，依 SKILL.md Step 3 rubric）約 40/46（D8 語意僅 ~2/5：CLAUDE.md
無 prompt injection 防護語句，scanner 與語意一致確認）。**grand total ≈ 91/115 ≈ 79% →
「Good」**。

### A-2 鑑別力評估：堪用，但有兩個 false-negative bug

工具**沒有**把本 repo 全部蓋章為滿分，仍抓出真缺口（D1 行數超標、D3 deny 不全、
D2 Stop hook 缺、D6 無 worktree）——代表它對結構面有實際鑑別力，不是純橡皮圖章（部分反駁 C-5）。

但實測暴露兩個 **false-negative**（低估本 repo 實際設置）：

1. **D4 誤報「`.claude/commands/` 不存在」**：本 repo 有 **top-level `commands/`（11 個 slash
   command）** symlink 到 `~/.claude/commands/`（CLAUDE.md 架構說明），scanner 只看
   `.claude/commands/` → 漏判，D4 少給分。
2. **D3「allow list 未設定」**：allow-list 在 `settings.local.json`（gitignored），不在
   committed `settings.json`，scanner 看不到 → WARN 其實是工具的視野盲點，非 repo 缺失。

→ 結論：**結構鑑別力堪用，但 path 慣例（symlink / local settings）會造成系統性低估**，
評分需人工複核 findings，不能直接採信總分。

### A-3 token 盲點實證（核心鐵證）

掃描結果**完全沒有**對 3007 行 always-on context 提出任何 token / context 預算警告：

- D1 對 CLAUDE.md 216 行給 WARN，**但對 2800 行 always-loaded rules 隻字未提**。
- D7 把這 14 個 rule 檔（含 819 行的 rule 13、587 行的 rule 11）評為 **6/7 高品質**。
- 沒有任何維度回答「這個 repo 每回合 always-on 吃掉多少 context？按需載入比例多少？」

這就是「**harness-eval 無法評估 token 平衡**」的具體、可重現證明：它把 yibi-stack 最值得
討論的 token-economy 特徵，當成品質優點計分。

---

## Part B — 擴充建議（提案，不在本次實作）

> 決策留給使用者：是否值得新增 token 維度、要做到什麼程度。以下為提案骨架。

### B-1 建議：新增 D11「Context / Token Economy」（或併入 D1 擴充）

可機械化的 static proxy 指標（皆可在現有 scanner 框架實作）：

| 指標 | 量法（proxy） | 訊號 |
|---|---|---|
| always-loaded token 估計 | CLAUDE.md + glob 自動載入 rules + memory 檔的字元數 × 係數 | 過高 → context 預算被擠壓 |
| progressive-disclosure 比例 | 按需載入（skill body / 非 always-on doc）vs always-on 的占比 | 比例過低 → 過度前載 |
| CLAUDE.md ↔ rules 冗餘 | 兩者重疊內容偵測（已部分被 D7 語意「不重複」涵蓋，可量化） | 冗餘 → 雙重維護 + token 浪費 |
| effort 相稱性 | 重型 skill 的 `effort:` 等級 vs description / body 長度 | 不相稱 → C-3 的回饋閉環 |

設計要點：此維度應能對「越加越多」產生**邊際遞減 / 上限懲罰**（修正 C-1），
而非沿用 additive 加分。

### B-2 落地路徑（依本 repo SDD 流程）

產 openspec change proposal：`openspec/changes/add-token-economy-harness/`
（proposal.md / design.md / tasks.md / specs/.../spec.md），格式對齊既有
`enhance-d5-behavior-harness`。

### B-3 風險

- static proxy **無法等同 runtime 成本**（C-6）——必須在 spec 與 SKILL.md 明確標示為
  「近似指標，非實際 token 計量」，避免使用者誤信為精準成本。
- 係數（字元→token）依模型 tokenizer 而異，需標示為粗估。

---

## 結論

`harness-eval` 能有效評估一個專案 harness engineering 的**結構設置程度**（覆蓋面廣、
hybrid 設計合理、對本 repo 仍抓得出真缺口），但需注意 symlink / local-settings 造成的
系統性低估。它**目前無法評估「效能 / token 平衡」**——缺整個 context economy 維度，
且加總式計分本質上獎勵「東西多」而非「剛好」。本 repo 自身 3000 行 always-on context
被當品質加分、零 token 警告，即為最直接的反例。若要補上，B-1 的 static proxy 維度
（含邊際遞減懲罰）是可行方向，但須誠實標示其為近似而非精準計量。

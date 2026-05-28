# Spec Kit ↔ OpenSpec ↔ Spectra：以 Teddy 五層約束為框架的三方比較研究

**撰寫日期**：2026-05-28
**比較框架**：Teddy（陳建村）〈馴服 AI 寫出可維護的系統〉工作坊之「五層約束理論」

---

## Part 1：Teddy 五層約束理論（基礎框架）

Teddy 在《馴服 AI 寫出可維護的系統》工作坊中主張：以**多層次模式語言**約束 AI，逐層縮小幻覺解題空間。核心哲學是「**以限制取代放縱**」——為 AI 設定智慧護欄，而非任其自由生成。理論來源為建築師 Christopher Alexander 的模式語言理論。

| 層級 | 名稱 | 主張方法 | 預期產出 |
|---|---|---|---|
| L1 | **需求約束** | Event Storming 分析系統規格 | BDD (ezSpec) 驗收測試 |
| L2 | **大尺度約束** | Clean Architecture + DDD + CQRS | 整體系統架構藍圖 |
| L3 | **中尺度約束** | Sub-agent 職責劃分（基於 Bounded Context） | AI 活在合適 Context 中 |
| L4 | **小尺度約束** | Coding Standards、模式介面規範與實作限制 | 一致的實作標準 |
| L5 | **微尺度約束** | Design by Contract（pre/post-conditions、invariants） | 邏輯層級的正確性保障 |

關鍵理論引用：「每個層次的約束都在縮小 AI 產生幻覺的解題空間」、「活的模式語言迴圈」（從 AI 錯誤迭代精煉規範）。

---

## Part 2：三方工具定位與哲學

| 維度 | **Spec Kit**（GitHub） | **OpenSpec**（Fission AI） | **Spectra**（spectra-app + yibi-stack 改良） |
|---|---|---|---|
| 哲學 | 規格至上、消除歧義 | 流動輕量、agree-first | 精簡 + 護欄密集 + RAG 索引 |
| 安裝 | `specify init`（~30 min） | `npm i -g @fission-ai/openspec`（< 5 min） | `brew install --cask spectra-app` + plugin install |
| 命令數 | 7 核心 + checklist（前置） + analyze（後置） | 5 核心 + 3 擴展 | 12 skill / 10 slash command |
| 單 change 體量 | 2000+ 行 / 18000+ token | proposal + specs/ + design + tasks（輕） | proposal + delta specs + design + tasks + testplan + touched.json |
| 治理層 | `constitution.md`（顯式） | 無 | `.claude/rules/`（有但未顯式引用 ← 介面缺口） |
| RAG | 無 | 無 | `spectra search --json`（向量搜尋） |
| 子流程護欄 | analyze + checklist | verify | drift + verify + audit + analyze（四套 fork-context） |
| Subagent | 無 | 無 | `sdd:gherkin-scenario-writer` + `sdd:qa-test-designer` 平行 dispatch |

---

## Part 3：五層約束 × 三方工具 對應矩陣

| Teddy 層級 | Spec Kit | OpenSpec | Spectra | 評語 |
|---|---|---|---|---|
| **L1 需求** | `/constitution` + `/specify` + `/clarify`；流程：tasks → **checklist（前置 QG）** → implement → analyze；無 Event Storming，BDD 弱 | `/opsx:propose` 寫 proposal.md + specs/ | `spectra-amplifier` 五層厚度（US/AC → Gherkin → TC）+ `sdd:gherkin-scenario-writer` subagent 平行生成 BDD-like scenario | Spectra 用 subagent 把 Gherkin 移到 Critical Path；缺 post-propose 歧義排除（G2） |
| **L2 大尺度** | `/plan` 自由填寫；無預設架構 | `design.md` 自由填寫 | `design.md` 自由填寫；`.spectra.yaml` flags 注入紀律 | 三方都沒預設 Clean Architecture + DDD + CQRS；架構顯性化是三方共同空缺 |
| **L3 中尺度** | 無 sub-agent 機制（30+ 整合限外部客戶端，非 multi-agent 架構） | 無 sub-agent 機制 | 12 個 fork-context skills（disallowedTools: [Edit, Write] 強制 read-only sub-thread）+ Task subagent 並行 dispatch | **Spectra 在 context 工具隔離上三方唯一**；但 Teddy L3 核心是 Bounded Context 業務分工——G9 落地前，sub-agent 缺乏域邊界，L3 尚未完整實作 |
| **L4 小尺度** | 無預設 coding standards | 無預設 coding standards | `.claude/rules/` 16 條 + rule 11 SKILL.md authoring | Spectra 既有資產豐厚，但 `/spectra-propose` 與 `/spectra-apply` 沒有顯式引用 rules ← G1 落地點 |
| **L5 微尺度** | 無 DbC | 無 DbC | 部分有：`##### Example:` → parameterized test traceability；缺 pre/post/invariants 框架 | 三方共同最弱點 |

**矩陣結論**：

- Spectra 在 **L3（中尺度）context 工具隔離領先**（fork-context skills 三方唯一），但 Bounded Context 業務分工（G9）落地前，L3 尚未完整
- Spectra 在 **L4（小尺度）資產豐厚但未顯式接口**（G1 quick win 落地點）
- Spectra 在 **L1（需求）有 amplifier 五層但缺 Event Storming 步驟與 post-propose clarify**
- 三方在 **L2（大尺度架構）與 L5（微尺度 DbC）共同缺席**

---

## Part 4：維度補強

### 4.1 Cost（成本）

| 工具 | Token / change | 學習曲線 | 維運成本 |
|---|---|---|---|
| Spec Kit | 18,000+ token loading（單功能 2000+ 行 markdown） | 高（7+ 命令 + constitution + checklist + analyze 概念） | 高（artifact 易 stale） |
| OpenSpec | 中（proposal + specs + design + tasks） | 低（3 核心命令） | 中（有 verify/sync，但無時序 drift anchor → 仍需人工觸發） |
| Spectra | 低-中（增量 delta + `.spectra/touched` per-task 追蹤） | 中（12 skill 概念多，但 fork-context 隔離降低 cognitive load） | 低（drift / verify / audit 自動偵測腐化） |

洞察：Spec Kit 的「規格至上」哲學造成 token 爆炸，正是 Spectra 用 delta-based spec + per-task touched 規避的。Spectra 設計上對應 Teddy 主張的「活的模式語言迴圈」——增量演化而非一次寫完。

### 4.2 Security（安全）

| 工具 | Prompt Injection Defense | Sharp-edge Audit | Sensitive Data Handling |
|---|---|---|---|
| Spec Kit | 無顯式機制 | 無 | 無 |
| OpenSpec | 無顯式機制 | 無 | 無 |
| Spectra | `/spectra-ask` 有完整 prompt injection 防禦（identity hardening、scope boundary、PII/credential redaction） | `/spectra-audit` 三 adversary lens（Scoundrel / Lazy Dev / Confused Dev）+ 六大 trap categories | rule 03 security + audit skill 強制執行 |

洞察：Spectra 在 security 維度大幅領先，這是把 `.claude/rules/03-security.md` + sharp-edge audit 經驗內化進 SDD workflow 的成果。

### 4.3 Extensibility（可擴充性）

| 工具 | Plugin 模型 | Reference Template | Subagent / Skill 擴充 |
|---|---|---|---|
| Spec Kit | Template 優先級堆疊（Project > Preset > Extension > Core） | 有，但需 fork | 30+ AI agent 整合，但限官方支援 |
| OpenSpec | 無顯式 plugin | 無 | 25+ AI 助手相容 |
| Spectra | plugin marketplace（yibi-stack 即 marketplace）+ skills-lock.json 追蹤外來 skill | `plugins/sdd/references/` 7 個（平面結構） | 12 個 fork-context skills + 2 個 Task subagent，自定義門檻低 |

洞察：Spectra 的 plugin 模型優於 Spec Kit 與 OpenSpec，但 reference template 是平面結構——缺 Spec Kit 的三層優先級堆疊（G4 可學習點）。

---

## Part 5：Spectra 既有的領先點（按 Teddy 五層分類）

### L1（需求）

- `spectra-amplifier` Wave D 五層厚度：US/AC → Gherkin → TC → Design → DoD
- `sdd:gherkin-scenario-writer` Task subagent（平行 dispatch，N≤5 capabilities）
- `sdd:qa-test-designer` Task subagent（Scenario Slug 表 + Coverage Analysis）

### L2（大尺度）

- 弱（與 Spec Kit / OpenSpec 同樣空缺）

### L3（中尺度）— context 工具隔離三方唯一（Bounded Context 分工待 G9）

- 12 個 fork-context skills（drift / audit / ask / verify / analyze / discuss 等全標 `disallowedTools: [Edit, Write]`，`context: fork`）
- Task subagent 平行 dispatch（amplifier Step 1c / Step 2a）
- Three required failure gates（rule 11:523-553）：subagent 不存在 / 回 `[FAIL]` / Task tool 本身錯誤

### L4（小尺度）

- `.claude/rules/` 16 條
- SKILL.md authoring rule（rule 11，400+ 行）含 Spec/SKILL.md sync、MCP failure gates、Dual-source ownership 等紀律

### L5（微尺度）

- 部分：`##### Example:` → parameterized test traceability
- 缺：pre/post/invariants 框架

### 額外領先（不在 Teddy 五層內）

- Parked changes（`.spectra/changes/*.started`）
- Drift detection（time + anchor + commit collision）
- Per-task touched tracking + selective staging（禁 `git add .`）
- RAG 索引（`spectra search` 向量搜尋）
- Ingest（plan-mode → artifacts，保留 `[x]` 與 `[P]`）

---

## Part 6：Spectra 的缺口與可學習點

### 6.1 從 Spec Kit 學

| 編號 | 學習點 | 對應 Teddy 層 | 落地方向 | 風險 |
|---|---|---|---|---|
| **G1** | Constitution 顯式引用 | L4 | 改造 `/spectra-propose` 與 `/spectra-apply` self-review 明示引用 `.claude/rules/` + `CLAUDE.md` | 低 |
| **G2** | Clarify 命令 | L1 | 新增 `/spectra-clarify <change>`：post-propose 歧義排除；與 discuss（pre-propose）邊界劃清 | 低 |
| **G3** | Checklist artifact | L1 | propose 產出 `checklist.md`，verify 比對 spec 與 checklist 一致 | 中 |
| **G4** | Template 優先級堆疊 | (extensibility) | `plugins/sdd/references/` 升級為 `core/` / `preset/` / `override/` 三層 | 中 |
| **G5** | Module Contracts 子目錄 | L4 / L5 | `openspec/changes/<n>/specs/<cap>/contracts/` 明示 API 邊界 | 中 |
| **G6** | TasksToIssues | (workflow) | `/spectra-issues`：tasks.md → GitHub issues（plugin:github MCP） | 中 |

### 6.2 從 Teddy 學

| 編號 | 學習點 | 對應 Teddy 層 | 落地方向 | 風險 |
|---|---|---|---|---|
| **G7** | Event Storming 步驟 | L1 | `spectra-amplifier` Step 0.5：產出 Domain Events + Commands + Aggregates（`plugins/sdd/skills/event-storming/` 已存在，管道就緒） | 中 |
| **G8** | Architecture 模板（Clean Architecture + DDD + CQRS） | L2 | `plugins/sdd/references/` 加 `architecture-clean-ddd-cqrs.md`；`.spectra.yaml` 加 `architecture: clean-ddd-cqrs` flag | 中 |
| **G9** | Bounded Context 明示 | L3 | propose 強制標注 Bounded Context；apply dispatch subagent 時帶入 constraint（G9 是 L3 完整落地的必要前提） | 中 |
| **G10** | Design by Contract 框架 | L5 | spec.md 加 `##### Contract:` 區塊；verify 檢查實作測試覆蓋 pre/post/invariants | 高 |

### 6.3 反向教材（不學）

- Spec Kit 的 2000+ 行 markdown 規格 → Spectra delta + touched 已解決
- Spec Kit 的 constitution.md 另成一套規範來源 → 與 `.claude/rules/` 衝突，改用 G1 顯式引用
- Teddy 工作坊以 Java 為主 → Python 轉譯需注意（DbC 可用 `icontract` 或 `deal`）

---

## Part 7：落地行動優先級

| 優先 | 行動 | ROI | 改動 | 層 |
|---|---|---|---|---|
| ⭐⭐⭐ | G1 Constitution 引用 | 高（quick win，低摩擦高合規回報） | 2 SKILL.md | L4 |
| ⭐⭐⭐ | G2 /spectra-clarify | 高 | 1 skill + 1 command | L1 |
| ⭐⭐⭐ | G9 Bounded Context 明示 | 高（L3 完整落地的必要前提） | propose + apply skill | L3 |
| ⭐⭐ | G7 Event Storming | 中（底層管道已就緒） | amplifier Step 0.5 | L1 |
| ⭐⭐ | G3 Checklist artifact | 中 | propose + verify | L1 |
| ⭐⭐ | G8 Architecture preset | 中 | 1 template + amplifier | L2 |
| ⭐ | G4 Template 三層化 | 中 | references/ 重組 | (ext) |
| ⭐ | G6 TasksToIssues | 中 | 1 skill + MCP 整合 | (workflow) |
| 觀察 | G10 Design by Contract | 中-低（高風險；語言 framework 差異大；勿作為預設） | spec.md schema 改 | L5 |
| 觀察 | G5 Module Contracts | 低-中 | spec 子目錄 | L4/L5 |

---

## Part 8：關鍵 file_path 索引

### Spectra 既有資產

- `plugins/sdd/skills/spectra-amplifier/SKILL.md` — 五層厚度與 subagent dispatch
- `plugins/sdd/agents/gherkin-scenario-writer.md` — L1 子代理（BDD-like）
- `plugins/sdd/agents/qa-test-designer.md` — L1 / L4 子代理（test coverage）
- `plugins/sdd/references/` — 7 個 reference templates（G4 三層化目標）
- `.claude/skills/spectra-*/SKILL.md` — 12 個 fork-context skills（L3 領先點）
- `.claude/commands/spectra/*.md` — 10 個 slash commands
- `.claude/rules/01-16` — G1 Constitution 引用的目標資產（L4）

### 外部參考

- Spec Kit repo：https://github.com/github/spec-kit
- OpenSpec repo：https://github.com/Fission-AI/OpenSpec
- Teddy 課程：https://teddysoft.tw/courses/ai-coding-pl/
- Tim Chao 三方比較：https://www.timchao.site/en/articles/sdd-tools-comparison-speckit-openspec-superpowers

---

## Appendix：第三方 Review 摘要（2026-05-28）

本研究在發布前交由兩個獨立外部 reviewer 進行盲審：**Codex**（GPT-5.5, read-only sandbox, web search enabled）與 **agy**（Gemini, sandbox）。以下為兩方合併意見，以標記嚴重程度排列。

### A.1 高優先收斂點（兩方均指出）

**[P1 × 2] L3「Spectra 三方唯一實作」論點過度主張**

Codex：fork-context read-only skills 是工具隔離（tool isolation），Teddy L3 是基於 Bounded Context 的業務領域分工。Gherkin/QA subagent 屬 L1 角色，不是 L3 bounded-context agent。建議修正為「Spectra 在本地 context 隔離上領先，但 Bounded Context 尚未第一公民化（G9 仍是未來項目），L3 尚未完整落地」。

agy（標 **[P0]**）：明確指出 `spectra.analyze`、`spectra.implement` 等 fork-context skill 是技術工作流階段分工，而非業務領域分工。既然 G9（Bounded Context 明示）是「待落地缺口」，sub-agent 就沒有依據活在正確的 Bounded Context 中，「Spectra 已在 L3 領先」的論點不成立。

→ **修正方向**：Part 3 L3 評語改為「Spectra 在 context 工具隔離領先，但尚未完整實作 Teddy L3（Bounded Context 分工）；G9 落地後才算完整」。

---

**[P1 × 2] 遺漏維度足以影響落地決策**

兩方均指出以下盲點：
- Spec Rot 自動偵測（hotfix 繞過 SDD 後如何發現代碼與 Spec 飄移）
- CI/CD pipeline 整合（verify / audit 若只能本地跑則形同虛設）
- Onboarding 認知負載（12 skill + 400 行規範對新工程師的壓力）
- Multi-branch spec 衝突解決與 archive consolidation 流程

Codex 額外補充：spec diff / versioning 工具、multi-repo workspace、editor/IDE 整合、社群健康與更新速度。

---

**[P1 × 2] 內部矛盾：L3 領先主張 vs G9 缺口**

Part 3 宣稱 L3 領先，Part 6/7 承認缺 Bounded Context（G9）。兩位 reviewer 均標記此矛盾。

---

### A.2 Codex 特定發現

**[P1] OpenSpec 描述不足**

Codex web 搜尋確認 OpenSpec 目前 core profile 含 `propose / explore / apply / sync / archive`，擴展包含 `verify / bulk-archive / onboard`。文件中「無 drift 偵測」（Part 4.1 / 表格第 34 行）的說法因 `/opsx:verify` 可檢查 artifact 一致性而被削弱；`/opsx:sync` 也具備 delta spec 合併能力。

→ **修正方向**：OpenSpec 維運成本欄改為「中（有 verify + sync，但無時序 drift anchor）」；命令數改為「5 核心 + 3 擴展」。

**[P1] G1 ROI 排名未充分論證**

文件僅說「低風險、改動 2 SKILL.md」，未呈現「缺少顯式引用是主要失敗模式」的實證。Codex 認為 G2（clarify）、G9（Bounded Context）更能降低高成本的下游錯誤。

→ **修正方向**：G1 保持高優先但定位為「quick win」而非「最高 ROI」；補充說明 ROI 依據（減少 self-review 遺漏）。

**[P2] Spec Kit 命令語法待驗證**

Codex 指出 Spec Kit 命令應為 `/speckit.constitution`、`/speckit.specify` 等點號格式，而非 `/constitution`。文件中使用裸斜線格式可能反映 slash command 呼叫方式，但正式名稱需與官方 README 對齊。

**[P2] Spec Kit 「無 sub-agent」與 30+ 整合矛盾**

若 30+ 整合計為 extensibility 優勢，應同樣在 L3 比較中說明其生態系能力，避免選擇性計算。

---

### A.3 agy 特定發現

**[P1] Spec Kit Checklist 位置錯誤**

agy 指出標準 Spec Kit 流程中 `/speckit.checklist` 是**前置質量護欄**（在 implement 之前驗證 spec 完整性），不是事後分析步驟。正確流程為 `tasks → (taskstoissues) → checklist → implement → analyze`。

→ **修正方向**：Part 2 命令數列與 Part 3 L1 評語中 Spec Kit 的 checklist 位置需修正。

**[P1] G9 Bounded Context 優先級被低估**

agy 認為 G9 應升為 ⭐⭐⭐（必做），理由是沒有 Bounded Context 約束，`gherkin-scenario-writer` 與 `qa-test-designer` 等多 agent 並行 dispatch 缺乏業務邊界，易引發領域修改衝突。G9 是 L3 真正落地的基礎設施。

**[P1] G7 Event Storming 風險被高估**

agy 指出 `plugins/sdd/skills/event-storming/` 在代碼庫中**已存在**，`spectra-amplifier` Step 0 也預留了讀取 `event-storming.md` 的接口。基礎管道已就緒，補齊難度低，應升為 ⭐⭐ 而非「高風險觀察」。

> **編輯注**：agy 另提及「Spectra SDD skill 實際為 9 個、使用點號命名（spectra.tasks 等）」，此判斷與本 repo 實際架構不符——`.claude/skills/` 下的 12 個 spectra-* skill 使用連字號命名，與 Spec Kit `/speckit.*` 命令體系是不同的系統。推測 agy 將 Spec Kit 命令對應表的 9 項混入了判斷，屬 reviewer 資訊邊界限制，不採納此點。

---

### A.4 Review 後修正優先列表

| 優先 | 問題 | 修正動作 |
|---|---|---|
| [P0] | L3 Spectra「唯一」論點過強 | Part 3 L3 評語加「context 隔離領先但 Bounded Context 未完整落地」補語 |
| [P1] | Checklist 位置錯誤 | Spec Kit 流程改為 `tasks → checklist → implement → analyze` |
| [P1] | OpenSpec drift 能力描述 | 「無 drift 偵測」改為「有 verify/sync，但無時序 drift anchor」 |
| [P1] | G9 優先級低估 | 升為 ⭐⭐⭐，並說明是 L3 落地的前提 |
| [P1] | G7 風險高估 | 升為 ⭐⭐，補充 `event-storming/` 已存在 |
| [P1] | 遺漏維度 | 加入 Spec Rot / CI/CD / Onboarding 三節（待後續版本） |
| [P2] | Spec Kit 命令語法 | 確認與官方 README 命令格式一致 |
| [P2] | G1 ROI 論證補強 | 加入「quick win」定位說明 |

## Context

`/pr-retro`（`plugins/pr-flow/skills/pr-retrospective/SKILL.md`）是本 repo 單一 PR / session 收尾的回顧 skill：agent 從 PR context 推論 5 題草稿，使用者校準後寫入 typed lessons，並在 Step 5 依 Lesson Classifier 把教訓路由成 rule / hook / CLAUDE.md 的 action item。此處只補充實作必須知道的現況約束：

- **retro 寫入路徑目前無驗證關卡**。Step 5 的三道 gate（Promotion Gate G1/G2/G3、Lesson Classifier、Patch-Surface Ladder）只回答「該不該寫、寫哪、寫多大」。信心度差異化（Step 4b）靠 `--source` 打分，是來源信任度而非實測。
- **姊妹 change 已上線並界定了本 change**。`bound-review-loop-with-evidence-gate`（2026-07-18 archived）在 `/pr-cycle-deep` review 迴圈導入證據閘門，其 Non-Goals 明確 defer「rules corpus 治理（`/pr-retro` 路由表出口、hot/cold tier）」，理由是「不同子系統，回饋源是 `/pr-retro` 而非 review 迴圈」，且判斷先做 review-loop gate 會「減少該子系統的流入量，先做這個可能讓後者變小」。本 change 即該續作。
- **兩閘門互補**。review-loop gate 把「精確度／可能誤導／建議補充」類 finding 恆降級為非 blocking，因此 reviewer 結構上擋不住「看似合理但沒驗證」的新 rule。該缺口只能靠 write-time + commit-time 對 rule 自身的證據 tier 分級補。
- **pr-retrospective 是 symlink skill**。`skills/pr-retrospective` symlink 進 `plugins/pr-flow/skills/pr-retrospective`；SKILL.md body 只跟本地 main checkout 一樣新（見 CLAUDE.md「installed skills go stale」）。

Stakeholder：本 repo 維護者（單人），既是 skill 作者也是使用者——「skill 自己的 PR 用 skill 自己 review」使規則通膨會自我放大，與姊妹 change 同一結構性風險。

#### Goals

1. 讓 retro 產出的「加 rule/hook」action item 在寫入 always-loaded 面前，其技術宣稱**可證偽**——能被一次 probe 示範，或能被一條 PR 原文 quote 佐證。
2. 讓無法驗證的主觀／單次教訓**結構性地無法**進入 always-loaded 面，而非靠 agent 自律或 reviewer 疲勞。
3. 讓 Tier 3 教訓有明確去處（park）且不製造新的無出口累積器；recurrence 使真且重現者可被重新評估，但不繞過證據要求。
4. 本 change 必須示範自己的主張：治臃腫的 change 不得讓 always-loaded rule 面淨增。

#### Non-Goals

- **不做 rules hot/cold tier 自動汰除**。本 change 只管「新內容寫入前」的證據把關，不回頭治理既有 corpus 的冷熱分層與淘汰。若寫入端把關上線後仍見 always-loaded 面失控，另開 change。
- **不改 review-loop gate（`pr-review-convergence`）**。不相交子系統，各自獨立 SKILL.md。本 change 複用其詞彙與模式，但不修改其 requirements。
- **不建 golden-transcript eval harness**。Tier 分級與 probe 是否誠實執行屬 LLM 執行期行為，pytest 不可驗證；本 change 只讓契約落地並誠實標示殘餘（同姊妹 change 的做法）。
- **不修 harness-eval D7 scanner 的 `glob:`/`paths:` 計分 bug（issue #252）**與 **skill-trigger-eval baseline 未進版控（issue #220）**。兩者為既有獨立缺陷，與本閘門正交。
- **不做 doc/code 分流 rubric**。姊妹 change 已論證其效果大部分被證據閘門吸收；此處同理，不引入第二套待維護 rubric。

## Decisions

### Evidence Gate 置於既有三道 gate 之上游

分級與驗證 MUST 發生在 Promotion Gate 之前。語意：Evidence Gate 問「這宣稱是真的嗎」，既有三道 gate 問「該不該寫、寫哪、寫多大」。先驗真偽，再談去留。

**為何選此**：把驗證放在下游（例如寫完再由 lint 補救）會讓 agent 已投入寫作成本後才被擋，且 Tier 3 的主觀教訓仍會先污染 classifier 的判斷。放上游則主觀教訓在最便宜的點（尚未分類）就被 park。

**替代方案**：只靠 commit-time lint 把關——否決，lint 只能檢查「有無證據標記」這個結構事實，無法在寫入前引導 agent 抽出可證偽宣稱；且新 section warn-only 起步期會放行大量無標記內容。doc gate 與 lint 必須並存（見下）。

### 複用姊妹 change 的證據模式，不重新發明

證據形式**封閉列舉、無 catch-all**、三種執行結果（重現／未重現／無效）、「無效 ≠ 不成立、降級不丟」、驗證成本分層、純函式檢查器——這五個模式 MUST 直接沿用 `pr-review-convergence` 已上線的形狀，只替換領域對象（finding → rule/hook action item；blocking → 寫入 always-loaded 面）。

**為何選此**：這些模式在姊妹 change 已被 21 個 scenario 的 testplan 與 mob review 打磨過，且維護者已熟悉其語彙。重造一套平行詞彙會製造「兩種 evidence gate 語意」的混淆，正是 rule 11 Cross-doc 一致性要避免的。

**替代方案**：另設一套 retro 專用的分級詞彙——否決，增加認知負擔且無收益。

### 證據形式表以 lesson 類型封閉列舉（見 spec SBE Example）

最後一列「精確度／可能誤導／建議補充／品味 → 無可接受形式，恆 park」是設計核心：它讓「這條規則措辭可以更精確」這類無限可生成的教訓**結構性地無法**進入 always-loaded 面。表中 MUST NOT 有 catch-all 列，否則逃生門重開。

**bash/hook 類收「正/負樣本」、`paths:`/CLI 類收「探針或 failing→passing 輸出」、事件類收「PR quote」**——這對映 repo 既有實測慣例（CLAUDE.md `paths:` 段的 `claude -p` 探針、rule 13 agy `-p` 段的版本標注、rule 15 的 probe 表）。

### 成本分層：便宜當場跑、昂貴派 subagent 或降級

零成本結構檢查（有無分級、Tier 1/2 有無證據欄位）擋掉多數；秒級 probe（正/負樣本、failing→passing）互動當場跑；昂貴 probe（`claude -p` 拋棄式 repo）派 subagent 或降 Tier 2 要求 PR 階段已產生的證據。

**為何選此**：一個因為太貴而被繞過的閘門等於不存在（姊妹 change 的原話）。互動式 retro 若被單一 `claude -p` 探針同步阻塞數十秒，使用者會停用整道 gate。派 subagent 讓昂貴 probe 離開主流程。

**替代方案**：所有 Tier 1 都當場跑——否決，成本不可持續；所有 Tier 1 都只要求附證據不當場跑——否決，退化成「只看有沒有填」，秒級可驗的宣稱不驗白不驗。

### Tier 3 park 複用 typed-lessons，recurrence 升級但不繞過證據

Tier 3 存入既有 mycelium typed-lessons（`confidence ≤ 4` + `parked`），不新增檔案面。recurrence ≥ 2 解除 park 重新受評，但仍須通過 Tier 1/2 證據才寫入。

**為何選此**：recurrence 證明的是「問題真且會重現」，不是「此修法有效」——兩者是不同宣稱。若 recurrence 直接觸發寫入，等於用「重現三次」跳過對 fix 的驗證，正是本 change 要防的 over-fit。複用 typed-lessons 而非新建 `retro-candidates.md`，避免新增一個只進不出的累積器（姊妹 change 最該避免的失敗模式）。

**替代方案**：Tier 3 直接丟棄——否決，失去 recurrence 追蹤，重現型 friction 每次從零開始；新建獨立候選檔——否決，多一個檔案面且與既有 mycelium 回顧流程割裂。

### lint 分層強制 + 純函式檢查器

`scripts/lint_rule_evidence.py` 暴露純函式 `check_rule_evidence(diff_text) -> list[str]`。分層：新 rule 檔／新 hook 缺標記 → error 擋 commit；既有檔新增 section 缺標記 → warn-only（`verbose: true`）。

**為何純函式**：只對真實檔案斷言的測試無法測自己的失敗路徑——「錨點消失必須變紅」「空輸入不得空洞通過」這些負向案例需要純函式入口以合成 fixture 呼叫。這是姊妹 change 的 `check_convergence_contract` 已證明的模式，也是 repo 反覆記錄的「guard 的 PASS 在你證明它會對已知壞輸入失敗前沒有資訊量」。

**為何 warn-only 起步**：`.claude/rules/` 既有檔（rule 13/15 等）已累積數十個無結構化標記的 section。新 section 一上線就 error 會逼使第一個 commit 補一堆歷史標記或關掉 hook。warn-only 讓新內容被看見、不阻斷，穩定後（既有 corpus 補標或政策確立）再升 error。

**替代方案**：一律 error——否決，見上；一律 warn——否決，新 rule 檔／新 hook 是最高風險的整批新增，必須硬擋。

### 規範內容寫入 rule 11 而非新增 always-loaded rule 檔

Evidence Gate 的作者面規範 MUST 寫入 `.claude/rules/11-skill-authoring.md`（`paths: skills/**` 觸發載入），而非新開一個無 `paths:` key 的全量載入 rule 檔。

**為何選此**：本 change 治的正是 always-loaded 面通膨。新開全量載入檔會讓每個 session 都付這道規範的 token 成本，即使該 session 不碰 skill/rule 撰寫。寫入 rule 11 則只在編輯 `skills/**` 時載入——與規範的適用時機一致。這是本 change 對自己主張的 dogfood。

## 資料模型與 API

**大致不適用。** 本 change 產物為 SKILL.md runbook、rule 11 段落、一支 lint script 與其測試——**無新 Entity、無新 DB schema、無 API endpoint、無新 Pydantic model**。

唯一的資料面接觸：Tier 3 park 使用既有 mycelium typed-lessons store 的 `parked` 狀態值與 recurrence 計數。實作時 MUST 先確認 mycelium schema 是否已有 `parked` 狀態與 recurrence 欄位；若無，加欄 MUST 向後相容（既有讀取者不認得新狀態時不得崩潰，見 rule 02 「Type Guard at External Data Boundaries」）。此為既有 schema 的相容擴充，非新資料模型。

## Implementation Contract

**In scope**：`pr-retrospective` SKILL.md 的 Step 5.0 Evidence Gate 段與 Q5→action 映射的證據前置條件、rule 11 的三層證據標準段、`scripts/lint_rule_evidence.py` 純函式檢查器與其合成 fixture 測試、`.pre-commit-config.yaml` 的 hook 註冊、以及本 change 自我約束的 always-loaded 淨增檢查。

**Out of scope**：既有 rules corpus 內容、hot/cold tier、review-loop gate、golden-transcript harness、mycelium 回顧流程本身、issue #252 / #220。

#### 可觀察行為

1. **Step 5.0 存在且在 Promotion Gate 上游**：SKILL.md Step 5 在 Q5→action 映射前含 Evidence Gate 段，明列三層與封閉證據形式表。
2. **Tier 3 不進 always-loaded 面**：主觀教訓被 park 到 typed-lessons，`.claude/rules/*` 與 `CLAUDE.md` 無新增。
3. **三分法可觀察**：Tier 1 probe 的結果被記為重現／未重現／無效之一；無效者 park 且不記為「未重現」。
4. **lint 純函式對壞輸入必紅**：`check_rule_evidence` 對錨點缺失、空輸入回傳非空清單。
5. **lint 分層**：新 rule 檔／新 hook 缺標記非零 exit；既有檔新 section 缺標記 `[WARN]`。
6. **自我約束**：本 change 完成後全量載入 rule 檔總行數淨增為 0，且該數字被印出。

#### 驗收條件

以 `scripts/tests/test_lint_rule_evidence.py` 機械驗證，每項須可獨立失敗；SKILL.md 與 rule 11 的段落以字串內容為錨點驗證，錨點找不到 MUST `[FAIL]` 而非略過，比對以 UTF-8 讀原始位元組。TC 表與覆蓋分析見 `tasks.md`。

#### 失敗模式

- 若 lint「新 section」偵測誤判既有 section 的行內編輯為新增 → 對既有內容誤 `[WARN]`。緩解：以 diff hunk 中的新 `##`/`###` heading 為錨點，非以行變更計數；實作時以合成 diff fixture 覆蓋「編輯既有 section」不觸發的案例。
- 若 mycelium 無 `parked` 狀態且加欄破壞既有讀取 → typed-lessons 讀取崩潰。緩解：加欄向後相容 + rule 02 type guard；實作時實測既有讀取路徑。
- 若規範誤寫進全量載入 rule 檔 → 違反自我約束。緩解：自我約束檢查會 `[FAIL]`。

## Risks / Trade-offs

- **[Tier 分級靠 LLM 判斷，非機械強制]** → lint 只能抓「有無證據標記」，抓不到「標記是否誠實」（agent 大可對主觀教訓貼一個假的 `<!-- verified: probe -->`）。這是本 change 最大假設風險，與姊妹 change 的 W4（lead 是否遵守「Critical 證據必驗」）同構。緩解：封閉列舉降低誤判空間、mob review 抽查證據標記真偽、Tier 1 probe 的三分法讓「無效證據」難以偽裝成重現。殘餘：誠實性由 golden-transcript harness 收斂，不在本 change 範圍。
- **[park 到 typed-lessons 若無人回顧則成墳場]** → 與姊妹 change 的 `deferred-from-review` issue 墳場風險同構。緩解：recurrence 機制使重現者主動浮出、複用既有 mycelium 回顧流程而非新建無人看的清單。殘餘：純主觀且不再現者確實會沉底——這是刻意的（它本就不該進 harness）。
- **[warn-only 起步期新 section 缺證據被放行]** → 過渡期真有無證據 section 進入既有 rule 檔。接受：漸進優於一次性擋死；warn 可見（`verbose: true`）使其不被靜默略過。
- **[昂貴 probe 派 subagent 增加 token 成本]** → 只在 Tier 1 昂貴類觸發，且替代方案（降 Tier 2 要 PR 證據）常可避免。接受。
- **[本 change 的 PR 被改動前的舊 retro 流程回顧]** → 舊流程無 Evidence Gate，可能讓它重現它要治的問題（無證據就寫 rule）。緩解：知悉即可，必要時對本 PR 手動採用新規則。

## Migration Plan

SKILL.md 與 rule 11 的行為改動於合併後即對新的 `/pr-retro` 呼叫生效；lint 於 `.pre-commit-config.yaml` 註冊後對新 commit 生效。既有 rules corpus **不回溯**補標記（warn-only 起步正是為此）。

需注意本 repo 安裝機制陷阱：`pr-retrospective` 透過 symlink 散布，SKILL.md body 只跟本地 main checkout 一樣新。合併後應在**主 repo**（非 worktree）`git pull`，再驗證 `/pr-retro` 載入的是新版 body（CLAUDE.md 已記載「合併後 `/pr-retro` 載到舊版 skill body」前例）。

Rollback：`git revert` 該 commit 即回復舊行為；lint 移除註冊即停用。無殘留狀態（typed-lessons 的 parked 記錄向後相容，不 rollback 亦無害）。

## Open Questions

- lint「新 section」偵測的精確 heuristic：以 diff hunk 新增行中出現的 `^#{2,3} ` heading 為準，或需解析整檔 section 邊界？傾向前者（純 diff 錨點，零檔案 I/O），實作時以「編輯既有 section 不誤觸發」的 fixture 定案。
- 便宜／昂貴 probe 的界線如何在 runbook 表達為可操作判準：以「是否需要建立拋棄式 repo 或跨 process 呼叫 `claude -p`」為分界，或以預估秒數？傾向前者（結構判準比時間判準可複驗）。
- mycelium typed-lessons 是否已有 `parked` 狀態與 recurrence 欄位，或需加欄——實作第一步先讀 schema 確認。

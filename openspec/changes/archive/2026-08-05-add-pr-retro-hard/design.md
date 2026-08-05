## Context

`/pr-retro` 的四道 gate（Evidence Gate → Promotion Gate → Lesson Classifier → Patch-Surface Ladder）都回答「該不該寫、寫哪、寫多大」與「有沒有證據標記」，但沒有一道回答**標記所指的宣稱是否成立**。這正是 `add-retro-evidence-gate` 假設表 W1 記載的最大殘餘風險，其列出的減災手段之一是「mob review 抽查」。

**`retro-evidence-gate` 的狀態**：實作已落地（`scripts/lint_rule_evidence.py`、`scripts/check_always_loaded_growth.py` 存在，SKILL.md 內有 Step 5.0，rule 11 內有三層證據標準段），但其 spec 尚未 archive 進 `openspec/specs/`。因此本 change 無法對它作 delta，設計上改以「產出建議、不改其 tier 語意」的邊界避免碰觸其 requirements。

**既有可複用資產**：`plugins/dev-cycle/skills/mob-code-review-only/SKILL.md` 是「委派引擎、只加外殼」的既有範式（自身零腳本，明寫引擎所有者）。`plugins/3rd-tools/skills/codex-consult` 與 `plugins/3rd-tools/skills/agy-consult` 各自擁有偵測、auth gate、packet 機制與 exit-code 閘門。`tasks/gate_eval` 是「決策矩陣 + fixture + mutation binding」的完整實作範式，其 `tasks/gate_eval/sunset.py` 的每個函式已泛用於突變描述子而不涉及 disposition 語意。

**本設計已經過外部審查**：以 `/codex-consult` 對初版設計與測試策略作獨立審查，據其發現修正三處（見 Decisions 中對應段落），並補入原本缺失的狀態機與整合契約層。

## Goals / Non-Goals

**Goals:**

- 讓 retro 草稿與規則草稿在交付人類判斷前，先受到至少一個獨立視角的挑戰。
- 讓「一致」與「異議」在彙整時具有不對稱效力：異議可降級，一致不得抬升。
- 讓彙整規則可回歸測試，而非僅存在於散文中依賴 agent 自律。
- 保留人類對 retro 結論的最終裁決權；mob 不得刪改呈現給人的項目。
- 讓本 change 可在無任何外部 CLI 的環境下仍能執行並誠實回報退化。

**Non-Goals:**

- **不建 conformance eval 模組**（oracle、fixture、mutation binding、shadow pilot）。屬後續 change，理由見 Decisions「conformance eval 分拆為後續 change」。
- **不做 trigger accuracy fixture**。`tasks/skill_eval` 的 fixture 發現只掃 repo 根層 `skills/` 第一層，而本 skill 依 sibling 慣例不建根層 symlink；補上等於變更散布方式，屬獨立決策。本 change 的觸發精準度僅靠 description 的反向轉向句與既有 overlap lint 保護。
- **不改 `pr-retrospective` SKILL.md 的任何既有步驟**，包含不改四道 gate 行為、不改 typed-lessons schema、不新增 park 路徑。
- **不改 `tasks/gate_eval` 或 `tasks/skill_eval`**。把 `sunset.py` 提升為共用模組屬後續 change 的一部分。
- **不 archive `add-retro-evidence-gate`**。它是獨立的收尾工作。
- **不做以歷史失效案例為量化 gate 的回歸語料**。理由見 Risks 的「歷史語料的事後洩漏」。

## Decisions

### 委派 pr-retrospective 為流程引擎而非複製其 runbook

`pr-retrospective` SKILL.md 有 688 行且承載四道 gate。複製會產生 rule 11 明文警告的雙份維護，且 overlap lint 會告警。改採 `mob-code-review-only` 的既有範式：本 skill 只擁有新增的審查輪，其餘明寫「照 `pr-retrospective` SKILL.md 原樣執行，不要在此重新推導」並點名其為所有者。

**否決方案**：在 `pr-retrospective` 加一個模式旗標。否決理由是把兩種模式的條件分支混進同一份 688 行 runbook，agent 逐行執行時容易走錯分支，且每個既有步驟都要標注模式差異。

### 彙整規則抽成可執行核心並作為唯一決策所有者

彙整規則若只寫成散文，`test_convergence_contract.py` 已誠實記錄其上限——測試只能證明 SKILL.md 還包含那些句子，不能證明未來的 agent 真的遵守。故彙整改為純函式，且**它就是 production path**，SKILL.md 不得自行重新實作。

防 drift 的所有權切分（rule 11 Dual-Source Document Ownership）：純函式與 schema 是唯一決策所有者；SKILL.md 只寫呼叫哪個腳本、哪些回傳必須停止、哪些欄位交給人。腳本提供 policy 說明輸出，用於產生與驗證 SKILL.md 內的摘要決策表，並以雙向交叉檢查斷言——程式的每個 outcome 都有文件說明，文件提到的 outcome 也真的存在。

**否決方案**：散文規則配一份 Python 複本。否決理由正是 rule 11 記載的靜默 drift。

### 共識僅由獨立首輪建立

初版設計以「附和率近 100% 且零新增 finding」剔除該 voice 票數。外部審查指出三個判準皆無可測定義。改為結構性規則：**共識只由獨立首輪建立**；交叉輪只能反證、降級、撤回或補 settling check，**不得新增獨立票**；首輪零 finding 的 voice 在交叉輪沒有共識資格。

這同時更忠於首輪互盲的原意。交叉輪本身也改為條件啟動——僅當外部 voice 之間對同一標的出現相反處置時才跑，而非只要有人反對草稿就跑。

### tier 降級以已執行證據為前提

初版讓「證據不支持」這個分類標籤本身即可觸發機械降級。這與本設計的核心論點自我矛盾：整套規則主張「一致不是證據」，卻讓一個**未經執行的標籤**觸發機械動作。改為：降級建議額外要求該 finding 的 settling check **已執行且結果為 confirmed**。

settling check 因此不是二元而是五種狀態：未執行、無法執行、無定論、確認、反證。「無法執行」不等於「反證」——這沿用既有 Evidence Gate 已建立的「證據無效不等於宣稱不成立」同一區分。

同時消除初版的契約矛盾：共用輸出格式允許 settling check 欄位為「無」，而對抗規則說沒有 check 就丟棄，兩者衝突。改為「無」是合法解析值，效力分 voice——對抗 voice 降為非作用性註解（仍呈現給人，不影響評分與草稿），外部 voice 最多列為未決，永不自動降級。

### 透過既有 consult skill 呼叫外部模型並以檔案指標傳遞審查包

不重寫外部模型偵測，也不讀 `/pr-cycle-deep` 的偵測快取檔（該檔是 dev-cycle 的私有狀態）。改為直接呼叫 `/codex-consult` 與 `/agy-consult`，其偵測、auth gate 與失敗停止條件由該兩 skill 自有。

審查包寫成檔案後，以短句參數指向其絕對路徑，而非把內容內嵌進參數。理由：草稿含 PR 原文引號，多 KB 內容經參數傳遞會踩 quoting；而兩個 consult skill 的底層呼叫都已具備讀取 repo 內檔案的能力。指標**不得**寫成 at 前綴形式——該形式在嵌套 worktree 會使 antigravity CLI 轉為代理模式而非輸出審查。

### 對抗 reviewer 使用內建 general-purpose subagent

不新增自有 agent 定義檔：`scripts/lint_skill_scope.py` 禁止 `scope: global` 的 skill 派送本 repo 自有 plugin 的 agent。內建 agent 不受此限。

`general-purpose` 具備寫入能力，故以三重約束替代結構性保證：prompt 內含唯讀約束（沿用 `agy-r1-stage1.sh` 既有措辭）、派工前後各取一次工作樹狀態比對、發現變動即警示。殘餘風險明記於 SKILL.md。

**否決方案**：改用工具集不含寫入能力的 `Explore` agent。否決理由是其設計用途為搜尋定位而非審查，靠它執行審查是超出設計用途的脆弱依賴。

### 審查產物目錄與併發隔離

產物寫入 `.runtime/retro-review/` 下以 PR 號區分的目錄，並把 `.runtime/` 加入 git 的 exclude 檔以免污染工作樹狀態。exclude 路徑必須經 git 自身查詢取得，不可手拼——連結式 worktree 下手拼會靜默寫錯檔。

exclude 檔是 git 的共用中介資料而非單一 worktree 私有，故寫入必須查重、且不得覆寫既有內容。同 PR 重跑或多 worktree 併發時，產物不得互相覆蓋，且陳舊產物不得被後續 PR 誤用。

### M2 審查的是建議文字，不改變寫檔權限

`/pr-retro` 現行契約是寫檔動作只給建議、由使用者決定，且可能先進批次佇列。故 M2 審查的標的明確界定為 Step 5 產出的**建議文字**，不審「使用者已批准的最終修補」，也不改變既有的變更權限歸屬。

### conformance eval 分拆為後續 change

`tasks/gate_eval` 提供完整範式：oracle 由 SKILL.md 決策矩陣轉寫、fixture 帶預期結果、突變描述子強制單一錨點、核心不含任何 LLM 相依而以判官介面為接縫、判定經由外部產生的判斷結果回放、並以錨點存在性判官在單元測試內決定性地證明突變致死。`tasks/gate_eval/sunset.py` 可被 import 而非複製，正確做法是把它提升為共用模組讓兩邊共用。

但這是另一個模組加上一套 fixture 與汰除規則，與本 change 的 skill 與彙整核心是不同子系統。合併會使本 change 超出可實作規模。故本 change 只做決定性測試層（腳本單元測試、彙整核心的性質測試、SKILL.md 契約 lint），eval 層另開——**追蹤於 issue #375**，其中已記明範圍（把 `sunset.py` 提升為共用 `tasks/_eval_mutation.py`、新建 `tasks/retro_review_eval/`、corpus-derived mutation 與 clean twin、10 次 shadow pilot、成本 paired A/B），以及明確排除以歷史失效案例作量化 gate 的理由（hindsight leakage 加 survivorship bias）。

值得沿用的兩個既有設計約束記於此以免後續遺漏：判官接縫使核心可單元測試；而 eval 套件**刻意不註冊任何提交前掛鉤或合併阻擋**——其存活不靠強制執行而靠讓廢除成本維持在「刪一個目錄加一個排程項目」。

### Shadow 出貨：降級建議預設不生效

彙整核心一律輸出降級建議，但引擎是否據此行動由旗標控制且預設關閉。本 change 出貨時 mob 只產生標注。啟用條件需要 false positive 與成本資料，屬後續 change。

## Implementation Contract

**Behavior**：使用者執行新命令並帶 PR 號時，流程與 `/pr-retro` 相同，但在草稿呈現前會多出一段標注了異議的審查結果，且在規則草稿建議產生前會多一段對該草稿文字的審查結果。草稿本身逐字保留。若外部 CLI 全數不可用，流程仍完成，並明確告知只有一個 voice、因而一致無訊號。

**Interface / data shape**：

- 目錄建立腳本：接受 PR 號參數，標準輸出印出產物目錄絕對路徑的鍵值行，診斷訊息一律送標準錯誤。缺參數或缺參數值皆以明確失敗訊息與非零退出結束，不得產生未捕捉的解譯器堆疊。
- 彙整核心：接受結構化 finding 清單（含 voice 身分與輪次）、settling check 執行結果、原始 confidence 與 source、草稿與審查包的雜湊；回傳保留的 finding、每個被排除者的排除原因、confidence 與 source 的最終值、tier 降級建議、以及是否允許變更。另提供 policy 說明輸出模式供文件交叉檢查。
- finding 結構：以 JSON schema 定義，分類欄位為封閉列舉，settling check 狀態為五值列舉。未知分類或缺標的欄位必須明確失敗，不得靜默略過。

**Failure modes**：

- 單一 voice 輸出缺少必要區段標題、長度過短、或含代理模式敘述 → 重跑一次；連續兩次失敗 → 標記該 voice 不可用並警示，**不阻擋流程**。
- 外部 consult skill 自身失敗 → 由該 skill 的既有閘門停止並回報，本 skill 不把失敗輸出當成審查結果。
- 草稿語意變更後餵入舊 finding → 明確標記為陳舊或拒絕，不得沿用。
- exclude 檔不可寫 → 明確失敗，不靜默繼續。
- 刻意靜默的部分：無 Q4 lesson 時不啟動 M2，此為預期行為而非錯誤。

**Acceptance criteria**：

- 彙整核心的性質測試涵蓋：voice 順序不影響結果、同輸入重跑不重複計票、增加附和不得提高 confidence 或改寫 source、settling check 為「無」時不產生處置、五種狀態分開處置、草稿項目不可刪除只可加註、降級建議僅在 check 為確認時成立、原本來源為使用者陳述者不可被降格覆寫、首輪零 finding 的 voice 在交叉輪無共識資格。
- 每個閘門都有正向對照：先證明它會對已知壞輸入失敗，再信任其通過。刻意包含「刪掉文件內一個 outcome 說明會使交叉檢查失敗」這一項。
- 目錄腳本測試涵蓋：exclude 逐行精確附加、重跑不重複、連結式 worktree 下路徑正確、既有內容保留、不可寫時明確失敗、缺參數與缺值分別失敗。
- 端到端乾跑：對一個已合併的 PR 執行並在寫入資料庫前中止，確認產物齊全、資料庫未被寫入、工作樹未被污染。
- 全量 CI 通過，且其後工作樹無殘留改動（提交前掛鉤中的格式化工具會就地改檔後宣告通過，本地綠不代表提交出來的樹會綠）。

**Scope boundaries**：

- 範圍內：新 skill 與其命令、彙整核心與 schema、目錄建立腳本、上述三類決定性測試、索引與 keywords 更新、版本 lockstep bump。
- 範圍外：conformance eval 模組、突變共用模組的提升、trigger fixture、shadow pilot 與啟用降級、對 `pr-retrospective` 與 `tasks/` 既有模組的任何修改。

## Risks / Trade-offs

- **[假共識：共同 prompt 汙染]** → 審查包只放實際蒐集到的原文、草稿逐字與**開放式**問題，禁止帶結論的是非題。本 repo 已記錄引導問句使多家模型各自附和同一個不存在的問題。
- **[假共識：交叉輪錨定]** → 共識僅由獨立首輪建立，交叉輪不得新增獨立票；報告須明講「一致」指的是哪幾家。
- **[評分通膨]** → mob 一致不得抬升 confidence、不得改寫 source 為跨模型。此為單向約束並以性質測試鎖定。若無此約束，每條 retro lesson 的信心度會被系統性抬高，污染下游蒸餾聚類。
- **[對抗 voice 製造修辭而非缺陷]** → 每條異議須附能定案的具體檢查；無者降為非作用性註解；會改動草稿者由主導者實跑該檢查後才採信。
- **[嵌入的 PR 原文構成注入面]** → PR 內容為使用者可控文字，正被送進三個模型。所有引述原文以明確分隔標記為不可信資料而非指令。
- **[私有 PR 內容外送]** → SKILL.md 明記會送往外部 CLI，並說明可用的遮蔽選項與退出方式。
- **[成本與延遲]** → M2 條件啟動；無 Q4 lesson 不跑。量測方法與可接受閾值屬後續 change；本 change 不訂數值門檻，僅確保任一 voice 失敗不會產生靜默成功。
- **[general-purpose subagent 具寫入能力]** → 唯讀 prompt 約束加上派工前後工作樹狀態比對；殘餘風險明記。
- **[`lint_skill_scope.py` 不涵蓋本 skill——實測]** → 原本把該 lint 當成「未派送自有 plugin agent」的驗證標的，**實測為假綠燈**：把本 skill 的兩處 dispatch 都改成 `subagent_type="growth:…"` 後該 lint 仍回報 `[OK] 27 個 skill 無違規`。原因是它只掃 repo-root `skills/*/SKILL.md`（原始碼 `SKILLS_DIR = REPO_ROOT / "skills"`），而本 skill 依 sibling 慣例是 plugin-only、無根層 symlink。**這個非涵蓋是設計正確而非缺口**：該 lint 守的不變量是「`make install` 只帶 SKILL.md 不帶 agents」，而 plugin-only skill 走 `claude plugin install`、與 agents 同管道分發，該失效模式結構上不會發生。**修法**：把檢查移到會實際讀本檔的 `test_skill_contract.py` SKC-DT-050，並斷言「完全不出現 namespaced dispatch」而非只斷言「有 general-purpose」——後者在未來若有人加了根層 symlink 就不足。已以隔離突變證明該測試會對同一壞輸入變紅。
- **[plugin 安裝路徑無法納入許可清單]** → 以變數定址的腳本呼叫無法用前綴樣式匹配，每次執行會出現確認框。此為 plugin-only skill 的既有既存成本（sibling 亦如此），不在本 change 解決。
- **[歷史語料的事後洩漏]** → 曾考慮以本 repo 自承的「retro 宣稱後來被證偽」案例作量化回歸語料。**否決**：那些案例的反證敘述就寫在 rule 檔內，而外部 voice 具備 repo 讀取權，因此量到的是「會不會查資料」而非「會不會推理」。加上生存者偏差在數學上無法補償（未被發現的錯誤不在語料內），此類語料只能作定性警示，不可作為發布閘門。
- **[本 change 只有決定性測試、沒有行為層 eval]** → 明確記為殘餘：彙整核心的正確性可被鎖定，但「voice 是否真的抓得到瑕疵」需要 fixture 與突變驗證，屬後續 change。此殘餘與 `add-retro-evidence-gate` 對其 W1 的處理方式一致——先上結構約束，行為層另開。

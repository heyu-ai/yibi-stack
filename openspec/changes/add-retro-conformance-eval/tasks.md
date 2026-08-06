## 1. 共用突變模組

- [ ] 1.1 `Shared mutation primitives are a single implementation` — 依 design 的「提升 sunset 突變核心為共用模組」把突變原語搬到 `tasks/_eval_mutation.py`，`gate_eval` 改為 import。
      **可觀察行為**：`gate_eval` 的離線 suite 對同一組 fixture 輸出與搬移前相同的 stability
      分類，且 `tasks/gate_eval/sunset.py` 不再保留本地實作副本。
      **驗證**：搬移前先記錄 `gate_eval` 離線 suite 的分類輸出，搬移後重跑並逐項比對相同；
      本 commit 為純搬移加 import 調整，任何行為修正另開 commit。
- [ ] 1.2 `A mutation whose anchor is absent or ambiguous fails loudly` — 讓套用突變在 anchor 缺失或不唯一時硬失敗。
      **可觀察行為**：anchor 在來源中出現 0 次或 2 次以上時，操作以非零結束並指名該突變（不唯一
      時同時印出匹配數），且該突變不得被計為 killed。
      **驗證**：`tasks/_eval_mutation_tests/test_eval_mutation.py` 對 0 次、1 次、2 次三種
      anchor 出現次數各有一個實際觸發的案例；並以隔離突變確認拿掉這個守衛後測試轉紅。
- [ ] 1.3 `Restoration invalidates stale derived artifacts` — 讓還原後使衍生產物失效。
      **可觀察行為**：突變期間產生的快取或衍生產物在還原後失效，後續評估讀到的是還原後的來源
      而非突變版。
      **驗證**：一個先套用突變、產生衍生產物、還原、再評估的測試，斷言第二次評估觀察到還原後
      的內容；並以隔離突變確認移除失效邏輯後該測試轉紅。

## 2. 新模組骨架與 judge 接縫

- [ ] 2.1 `The evaluation core never calls a language model` — 依 design 的「保留 judge 接縫讓核心不 import LLM」建立 `tasks/retro_review_eval/` 骨架。
      **可觀察行為**：emit-manifest → 供入 dispositions → score 的完整迴圈在不呼叫任何模型的
      情況下跑完並輸出指標；缺 dispositions 時輸出 manifest、以非零結束並說明還缺什麼，不輸出
      一份全零的指標報告。
      **驗證**：`tasks/retro_review_eval/tests/test_judges.py` 涵蓋兩條路徑（完整迴圈、缺
      dispositions），並以靜態斷言確認核心模組未 import 任何 LLM 客戶端。
- [ ] 2.2 `Manifest and dispositions are bound by signature` — 以 signature 綁定 manifest 與 dispositions。
      **可觀察行為**：signature 不匹配時 run 失敗，且訊息同時印出 manifest 與 dispositions 兩
      個 signature。
      **驗證**：一個供入不匹配 dispositions 的測試，斷言非零結束且輸出同時含兩個 signature；
      以隔離突變確認拿掉綁定後測試轉紅。
- [ ] 2.3 `Fixture models are specific to the retro decision surface` — 依 design 的「替換 models 而非重用 gate_eval 的 ConformanceFixture」撰寫本模組自己的 fixture model。
      **可觀察行為**：fixture 的 factor 是 claim–evidence 對的形狀、defect family、settling
      check 是否可執行；供入綁定其他評估決策面的 fixture 時被拒絕而非被評分。
      **驗證**：`tasks/retro_review_eval/tests/test_models.py` 各有一個合法 fixture 與一個
      外來 fixture 的案例；並在 `tasks/retro_review_eval/skill.md` 寫明 models 是必須替換的
      那一個檔案，避免下一個人嘗試 drop-in 重用。

## 3. Fixture 與突變運算子

- [ ] 3.1 `Every mutant has a clean twin` — 依 design 的「Corpus-derived mutation 與必須保留的 clean twin」實作 clean twin 檢查。
      **可觀察行為**：fixture set 中任一 mutant 缺少同形狀的未突變對照時，run 以非零結束並指名
      該 fixture；這是硬失敗而非警告。
      **驗證**：一個缺 clean twin 的 fixture set 案例斷言非零結束並含該 fixture 名；以隔離突變
      確認把硬失敗降級為警告後測試轉紅。
- [ ] 3.2 `Mutation operators are derived from observed failures` — 定義四個突變運算子與其不變量。
      **可觀察行為**：evidence replacement / scope expansion / actor inversion / causal
      substitution 各自只改一個最小片段，且字數、格式、引用密度保持不變；改動超過一個片段的
      fixture 被拒絕。
      **驗證**：每個運算子各一個 fixture 案例，加上一個「改了兩個片段」的拒絕案例；
      `tasks/retro_review_eval/fixtures/README.md` 記錄各運算子的來源失敗形狀。
- [ ] 3.3 `A deterministic judge proves fixture binding without an agent session` — 依 design 的「加入 anchor-presence judge 等價物」提供決定性 judge。
      **可觀察行為**：在沒有 agent session 的環境下，測試套件仍能證明每個 fixture 的突變會被
      受測邏輯 killed。
      **驗證**：在無網路、無模型可用的環境跑 `tasks/retro_review_eval/tests/` 全綠，且該測試
      實際斷言 mutation-kill 而非僅斷言 judge 可被呼叫。

## 4. 指標與範圍邊界

- [ ] 4.1 `Six metrics are reported, with sample counts` — 依 design 的「六項量測指標而非單一命中率」實作指標輸出。
      **可觀察行為**：報表含 detection recall、class accuracy、target localization、
      settling-check validity、clean-twin false-positive rate、false park rate 六項，每項附
      樣本數；零樣本的類別輸出「無樣本」而非 0。
      **驗證**：`tasks/retro_review_eval/tests/test_metrics.py` 含一個零樣本類別的案例，斷言
      輸出不是 0；以隔離突變確認把零樣本改回輸出 0 後測試轉紅。
- [ ] 4.2 `Historical falsified claims are excluded as a quantitative gate` 與 `The evaluation registers no commit-time or merge-time blocker` — 依 design 的「排除以歷史失效案例作量化 gate」與「不註冊 pre-commit hook 或 merge 阻擋」落定兩條範圍邊界。
      **可觀察行為**：以歷史失效案例組成的語料被當作 release gate 供入時遭拒（仍可作定性警示）；
      本模組不出現在任何 pre-commit hook 或 merge 阻擋設定中，只有秒級決定性測試進 CI。
      **驗證**：一個把該類語料當 gate 供入的拒絕案例；加上一個掃描 `.pre-commit-config.yaml`
      與 CI workflow、斷言不含本模組任何阻擋項的測試。理由（hindsight leakage 與 survivorship
      bias）寫進 `tasks/retro_review_eval/skill.md`。

## 5. Pilot 協定與成本量測

- [ ] 5.1 `The pilot records the baseline calibration before revealing mob results` 與 `Presentation order is randomised across cases` — 實作 pilot 案例的記錄順序與隨機化。
      **可觀察行為**：每個案例先記下使用者的 baseline 校準、再記揭露後的決定，兩者為分開的
      紀錄；跨案例隨機指派 baseline-first 或 mob-first，且指派結果隨案例一併存下。
      **驗證**：`tasks/retro_review_eval/tests/test_pilot.py` 斷言揭露前必須已有 baseline
      紀錄（缺少時拒絕），以及一組案例的順序指派兩種都出現且被記錄。
- [ ] 5.2 `Alignment is judged by an adjudicator blind to order` 與 `The pilot collects the six harm-and-benefit rates` — 實作不知順序的 adjudicator 與六項比率的收集。
      **可觀察行為**：送進 adjudicator 的兩份紀錄不帶「哪一份先產生」的資訊；每個完成的案例
      紀錄對六項比率各帶一個值或一個明確的不適用標記。
      **驗證**：一個斷言 adjudicator 輸入不含順序欄位的測試，加上一個斷言案例紀錄六項欄位齊備
      （含不適用標記路徑）的測試。
- [ ] 5.3 `Cost is measured per reviewer call, not from the session total` — 依 design 的「成本量測不得使用引擎現有的 session token 欄位」在每個 reviewer call 邊界計量。
      **可觀察行為**：報表含各插入點的 wall-clock p50/p95、critical-path latency（取最長的單一
      voice 而非三者相加）、每 voice 的 input/output/cache tokens、timeout / invalid / retry
      率、使用者額外互動次數、每個確認為真的 finding 之增量成本；以 session 層 token 欄位產生
      的報表被拒絕。
      **驗證**：一個三 voice 並行（40s/55s/35s）的案例斷言 critical-path 為 55s 而非 130s；
      一個以 session 層欄位產生的報表被拒絕的案例。
- [ ] 5.4 `Enabling demotion requires a checkable verdict` 與 `This capability defines the protocol and does not execute the pilot` — 依 design 的「Shadow pilot 協定與啟用降級的條件」輸出可檢查的 verdict。
      **可觀察行為**：harness 依相對 budget（p95 增量等待不超過 baseline 兩倍、每個確認有效
      finding 的成本不超過一次完整 baseline retro）輸出 verdict；資料不足時 verdict 是「資料
      不足」而非負面結果；budget 超標時 verdict 指名是哪一項超標。本項**不執行 pilot**、
      **不變更降級旗標的預設值**，預設維持 shadow。
      **驗證**：以 design 的 verdict 對照表為案例（3 案例→資料不足、10 案例達標→正面、
      p95 超標→指名該項、成本超標→指名該項）；另一個測試斷言降級旗標的預設值未被本 change
      改動。

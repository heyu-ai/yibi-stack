## 1. 資料模型與 fixture 驗證

- [ ] 1.1 實作 Conformance fixture schema 與 Disposition oracle transcribed from the runbook matrix 的載入模型：缺欄位、disposition 不在封閉列舉、或 fixture 因子組合在 oracle 中找不到對應項時，載入以驗證錯誤中止並指名該筆，不回退預設值、不靜默略過。驗證：tasks/gate_eval/tests/test_models.py 對每個失敗形狀各一個案例，且空 fixture 集合以失敗狀態退出。
- [ ] 1.2 實作集合層驗證，涵蓋 Fixture set covers both blocking and non-blocking expectations 與 Every fixture binds a single-edit mutation，並落實 design 決策「每個 fixture 只變動一個因子，並涵蓋放行方向」：全部期望為 deferred 的集合、或 mutation descriptor 指定超過一個 anchor 的 fixture，皆在任何 judge 呼叫前被拒。驗證：test_models.py 斷言退化集合被拒且 judge 呼叫次數為零。

## 2. Oracle 轉錄

- [ ] 2.1 將 pr-cycle-deep SKILL.md 的 disposition 矩陣逐格轉錄為 tasks/gate_eval/fixtures/oracle.yaml，四因子對應單一期望 disposition；任何一格無法在不做詮釋的情況下轉錄者，記入 change 的發現清單而非自行補值。驗證：內容複查確認矩陣每一格皆有對應 oracle 條目，且每個 oracle 條目至少被一個 fixture 引用。

## 3. Eval 執行與判定

- [ ] 3.1 實作 Three-valued stability verdict，落實 design 決策「穩定度以三值判定，且門檻先於執行定義」：n 次判定後依四次多數規則產出 CONFORMANT / NONCONFORMANT / UNSTABLE，UNSTABLE 不併入 NONCONFORMANT。驗證：tasks/gate_eval/tests/test_service.py 以 spec 中的 verdict boundaries 表格驅動測試，五種分佈各一案例。
- [ ] 3.2 實作 Boundary verdicts are re-run at higher n：五次執行未達四次多數者自動以 n 等於 15 重跑，報告標記該 verdict 來自重跑。驗證：test_service.py 斷言三比二分佈觸發重跑且 verdict 取自 15 次分佈。
- [ ] 3.3 實作 judge backend 介面與 Judge execution failure is distinguished from a deferred verdict，落實 design 決策「受測系統定義為 agent 加 SKILL.md，而非可單元測試的函式」：backend 回傳錯誤時記為執行失敗，不計入任何 disposition 統計。驗證：test_service.py 以 stub backend 注入錯誤，斷言 disposition 統計數不變。
- [ ] 3.4 實作 Conservation of findings across aggregation，落實 design 決策「守恆檢查的優先序高於一致性檢查」：比對每筆輸入 finding 在輸出中出現恰好一次且標題描述逐字保留，守恆結果排在 disposition verdict 之前。驗證：test_service.py 含刻意漏一筆與刻意改寫描述兩組對照，皆須回報守恆失敗並指名該筆。
- [ ] 3.5 實作 Report states the limit of what the result proves：報告首行固定聲明本結果只證明對既有規則的符合度、不證明規則正確，全綠與有紅皆然。驗證：test_service.py 對兩種結果各斷言首行內容。

## 4. Mutation 驗證

- [ ] 4.1 實作 Mutation whose anchor is absent halts the run 與 Mutation restoration invalidates stale cached bytecode：anchor 找不到即中止並指名 fixture 與 anchor，不記錄存活或被殺；還原後清除受影響模組樹的快取位元碼並更新來源檔時間戳。驗證：tasks/gate_eval/tests/test_sunset.py 以過時 anchor 斷言中止，並斷言還原後快取檔不存在且時間戳已更新。
- [ ] 4.2 實作 Fixture effectiveness is defined by mutation kill，落實 design 決策「fixture 的有效性定義為 mutation 存活與否」：僅當套用 mutation 使 verdict 由 CONFORMANT 轉為 NONCONFORMANT 時判定為有效，不以 suite 整體 pass rate 作為有效性訊號。驗證：test_sunset.py 對存活與被殺兩種情形各一案例。

## 5. Prune 與 sunset

- [ ] 5.1 實作 Quarterly fixture prune classification 與 Red results are classified and unclassified defaults to false alarm：依有效性與窗口內警報歷史，為每個 fixture 產出保留、降頻、移除三選一的建議；未分類的紅燈計為假警報。驗證：test_sunset.py 以 spec 中的 prune recommendation 表格驅動測試，五列各一案例。
- [ ] 5.2 實作 Suite sunset triggers，落實 design 決策「sunset 的觸發條件與檢視排程於本 change 內先行承諾」：窗口結束時求值三個觸發條件，任一成立即回報 suite 進入移除評估並指名該條件，被程式取代者額外註明屬取代而非失敗。驗證：test_sunset.py 對三個觸發條件各一案例，並含三者皆不成立的反向案例。
- [ ] 5.3 提供 Removal is deletion rather than refactoring 所要求的結構，落實 design 決策「移除成本必須維持在刪除等級」：實作集中於單一模組目錄，執行入口為 tasks/gate_eval/cli.py 的三個子命令（跑 eval、跑 mutation 驗證、產生 prune 與 sunset 報告），不註冊任何 pre-commit hook 或 merge 阻擋設定。驗證：test_sunset.py 斷言 .pre-commit-config.yaml 未出現本模組路徑，且三個子命令皆可由 uv run python -m tasks.gate_eval 觸發。

## 6. 驗收與交付

- [ ] 6.1 建立 Review is scheduled rather than remembered 所要求的季檢視 GitHub issue，內含到期日、prune 報告與 sunset 求值的記錄欄位，並註明未記錄的窗口視為未發生。驗證：issue 建立後貼出 issue 編號，並確認 tasks 與 design 中的 sunset 條件在 issue 內以可勾選項目呈現。同時在 openspec/changes/add-pr-review-contract/testplan.md 的 Missing Coverage 段落補上指向本 change 的一行，使該處未實作的 golden-eval harness 建議可被追溯到承接它的 change。驗證：於該 testplan 中確認新增行存在且指名本 change 名稱。
- [ ] 6.2 執行驗收對照組並記錄輸出：其一，餵入刻意標錯期望 disposition 的 fixture，eval 須變紅並指名該筆；其二，對結構層退件、evidence 形式錯配、封閉列舉排除三個不同 tier 的 fixture 各套用一次獨立 mutation，三者皆須由 CONFORMANT 轉為 NONCONFORMANT。驗證：兩組對照的實際輸出貼入 PR 描述，未出現紅燈者不得宣告本 change 完成。

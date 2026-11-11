# Proposal: gate-deferred-review-issues

## Summary

收緊 `/pr-cycle-deep` 對非阻擋 Important 項目的延後處置契約：將未重現與架構不可達項目留在 PR 留言、單檔小修當場結清、進行中 Spectra change 待辦寫入 `tasks.md`、真正獨立的已實證問題延至 PR 合併成功後才以具體問題標題建票，根除 `deferred-from-review` 無出口堆積。

## Motivation

`bound-review-loop-with-evidence-gate`（commit `116bc42c`）原假設 W3（`/issue-triage` 能消化 `deferred-from-review` 批次票）。在 `yibi-mvp` 四個月實測下，累計建立 112 張 `deferred-from-review`，其中 80 張未關閉（未消化率 71.4%，佔全儲存庫 open issues 24.5%）。抽樣最近 50 張發現：

1. `SKILL.md` 把證據閘門淘汰的「缺證據、未重現、0 命中、現行架構不可達」項目全放進 `## Deferred for lack of evidence`，Step 5c 又機械式把該段所有 Important 建成 GitHub issue（28% 內文明寫無法觸發仍開票）。
2. Step 5c 在合併前執行，導致 PR 尚未合併或 13 分鐘內同 PR 修掉時仍搶先建票。
3. 進行中 Spectra change 的實作前／archive 前待辦（22%）被開成外部 issue，繞過 `spectra archive` 把關並形成雙軌孤兒。
4. Round 2 對單檔數行可修的小問題直接外推建票，後續另開 PR 重跑全套審查的成本遠高於當場修補。
5. `"Deferred from review: PR #<N>"` 制式無語意標題掩蓋真產品缺陷，且打包微末雜項導致真問題修完後整張票仍無法關閉。

## Goals

- 拆開「缺證據／未重現／架構不可達（僅留 PR 留言，禁止建票）」與「已實證可觸發之延後 Important」。
- 允許並優先將 Round 2 單檔 15 行以內、無介面變動的已確認問題在進 Step 8 前當場修完過 CI，不啟動 Round 3 也不建票。
- 強制隸屬進行中 Spectra change 的延後待辦寫入該 change 的 `tasks.md`，禁止另建外部 issue。
- 將外部建票時機從合併前（Step 5c）移至 Step 10 確認 PR 已 `MERGED` 後（Step 10b）。
- 廢除 `"Deferred from review: PR #<N>"` 制式標題，強制使用具體模組與問題症狀作為標題並附領域標籤，由 `test_convergence_contract.py` 正反雙向鎖定。

## Non-goals

- 不修改 `/pr-cycle-fast`、`/pr-review-cycle` 或 `mob-code-review-only`。
- 不放寬 Round 1／Round 2 的最多兩輪重審上限，也不引入 Round 3。
- 不修改 `check_review_counts.py` 或 `review_markdown.py` 的來源計數解析器（新區段沿用同一 `- Code-review source: CR-<n>` 格式）。

# Design: gate-deferred-review-issues

## Context

`pr-cycle-deep` 現行的 Step 5 與 Step 5c 存在結構性耦合：Evidence gate 將無證據、格式不符、未重現、單一 voice `grep` 0 命中與精確度挑剔一律移入 `## Deferred for lack of evidence`，但 Step 5c 規定對 `## Deferred for lack of evidence` 中所有 Important 建立一張標題為 `"Deferred from review: PR #{{pr_number}}"` 的 GitHub issue。這使證據閘門淘汰掉的雜訊在 Step 5c 全部復活為永久工單。

同時，`check_review_counts.py` 與 `review_markdown.py` 會掃描 `final.md` 正文內所有 `- Code-review source: CR-<n>` 行（不限定段落標題），核對與 `code-review-filtered.json` 一一對應。因此新增或調整 `final.md` 區段時，只要維持相同的 `- Code-review source: CR-<n>` 列表項目格式，計數閘門即完全相容。

## Decisions

### D1：在 `final.md` 分離「未實證紀錄區」與「已實證延後區」

- `## Deferred for lack of evidence` 收錄缺證據、證據格式不符、精確度類、`evidence did not reproduce`、證據本身損壞而修補一次仍無法執行之 `Invalid`（標記為 `broken evidence` 而非 `not reproduced`）、單一 voice `grep` 0 命中與現行架構不可達項目，保留原文與理由供 Step 5b PR 留言備查，並明定此區段**禁止建立 GitHub issue**。其中 `Invalid` 壞證據項必須在 Step 8 `human-summary.md` 單獨列出交由人類明確裁決，未獲人類確認前絕不進入 `$REVIEW_DIR/deferred-issue.md`。
- 新增 `## Verified Deferred Important` 區段，僅收錄經 lead 驗證在現行架構真實可觸發、但因 Round 2 僅阻擋 Critical 而未阻擋合併者（Round 2 中每筆具良構 `Evidence:` 的 `Important` 均須由 lead 實測驗證後再分類；未重現或不可達者歸入 `## Deferred for lack of evidence`）。同時保留處置矩陣原字面列，將區段分流規則寫於矩陣下方散文，維持 `tasks/gate_eval` 錨點相容。
- 超出本 PR `Non-goals` 的既有產品缺陷維持列於 `## Outside contract`（或 `Outside Round 2 contract`），僅在經 lead 驗證於 `main` 可重現時才可進入 Step 5c 第 3／4 路；未經實證的 `Non-goals` 建議只留 PR 留言。

### D2：Step 5c 改為四路過濾閘門，串接完整狀態機且合併前禁止建票

將 `Step 5 → 5a → 5b → 5c` 一致接入 `--resume`、`state.md` `next:`、Step 5b（含貼留言失敗 fallback 與 Round 2 新增非阻擋項時重貼 `final.md`）、Step 7 兩輪退場決策表與 circuit breaker `False positive`（`→ Step 5c → Step 8`）。對非阻擋項目依序執行四路分流：

1. 未實證、未重現、未經人類確認的 `Invalid`、未實證 `Non-goals`、現行架構不可達與 Actionable NIT：留在 Step 5b 的 PR 留言，禁止建立 GitHub issue。
2. Round 2 單檔小修當場結清：已確認可觸發的真問題若修改範圍在單一檔案、15 行以內且不改變公開介面或 Review Contract，在進入 Step 8 前直接修完並通過本地與遠端 CI（套用 Step 6 的 `preflight-pr-push.sh` 守衛推送並立即同步 `state.md` `head:`），不啟動 Round 3 重審，也不建票。
3. 進行中且合併後仍維持 active 的 Spectra change 優先承接：若項目隸屬當前未封存且**不在本 PR Step 11a 立即封存**的 Spectra change，寫入該 change 的 `tasks.md`，通過本地 CI 後以 `preflight-pr-push.sh` 推送並同步 `state.md` `head:`（及 Round 1 `baseline`）；同時在 Step 11a `spectra archive` 前增設 `tasks.md` 未勾選 `- [ ]` 攔截檢查，禁止另建 GitHub issue。
4. 獨立跨範圍問題延至合併後建票：僅通過上述三道過濾後仍需獨立追蹤的已實證問題（及 Step 8 人類確認升格的 `Invalid` 項），寫入 `$REVIEW_DIR/deferred-issue.md` 候選檔（Round 2 合併保留未解的 Round 1 第 4 路項目；初始 Step 2 與剩餘 0 筆時 `rm -f "$REVIEW_DIR/deferred-issue.md"` 清檔），留待 Step 10 確認 PR 已 `MERGED` 後建立。PR 尚未合併時絕不執行 `gh issue create`。

### D3：Step 10b 合併後具名建票、帶外合併路由與區段級契約測試

- Step 10（及 Step 6／Step 10 帶外 `MERGED` 分支）以 `gh pr view ... --json state,mergeCommit -q 'select(.state == "MERGED") | .mergeCommit.oid // empty'` 確認非空 merge commit SHA 後，再進入 Step 10b → Step 11。
- Step 10b 先將 `來源：PR #{{pr_number}}（merge commit {{merge_commit_sha}}）` 寫入 `$REVIEW_DIR/deferred-issue.md` 首段，並在 bash 區塊明確定義 `WT_ROOT` 與 `REVIEW_DIR` 後建立每個 PR 至多一張 GitHub issue。
- 標題必須寫明具體模組與問題症狀，禁止使用 `'Deferred from review: PR #'` 任何引號或旗標變體之制式標題；標籤優先貼上目標儲存庫既有領域標籤（如 `bug`、`spec-gap`、`harness`、`infra`），可搭配已存在的 `deferred-from-review`。
- `test_convergence_contract.py` 除全域錨點與收緊的 `'Deferred from review: PR #'` 禁用字串外，新增 `check_deferral_sections` 對 Step 5、Step 5c、Step 10b 做區段級正反雙向與單處突變檢查。

## Risks / Trade-offs

- **[單檔 15 行小修未再經 3-voice 重審]** → 緩解：僅限單檔 ≤ 15 行且不改公開介面與契約，仍須通過完整本地與遠端 CI 並交 Step 8 Human Quick Pass 人工檢視 diff。相比另開 PR 的十倍成本與噪音，風險可控。
- **[寫入 active change `tasks.md` 產生額外 commit]** → 緩解：在 PR 合併前隨同分支推送（經 `preflight-pr-push.sh` 與 CI），讓待辦與程式碼／規格在同一個 PR 原子落地。

# Design: gate-deferred-review-issues

## Context

`pr-cycle-deep` 現行的 Step 5 與 Step 5c 存在結構性耦合：Evidence gate 將無證據、格式不符、未重現、單一 voice `grep` 0 命中與精確度挑剔一律移入 `## Deferred for lack of evidence`，但 Step 5c 規定對 `## Deferred for lack of evidence` 中所有 Important 建立一張標題為 `"Deferred from review: PR #{{pr_number}}"` 的 GitHub issue。這使證據閘門淘汰掉的雜訊在 Step 5c 全部復活為永久工單。

同時，`check_review_counts.py` 與 `review_markdown.py` 會掃描 `final.md` 正文內所有 `- Code-review source: CR-<n>` 行（不限定段落標題），核對與 `code-review-filtered.json` 一一對應。因此新增或調整 `final.md` 區段時，只要維持相同的 `- Code-review source: CR-<n>` 列表項目格式，計數閘門即完全相容。

## Decisions

### D1：在 `final.md` 分離「未實證紀錄區」與「已實證延後區」

- `## Deferred for lack of evidence` 維持收錄缺證據、證據格式不符、精確度類、`evidence did not reproduce`、單一 voice `grep` 0 命中與現行架構不可達項目，保留原文與理由供 Step 5b PR 留言備查，並明定此區段**禁止建立 GitHub issue**。
- 新增 `## Verified Deferred Important` 區段，僅收錄經 lead 確認在現行架構真實可觸發（或 Critical 證據指令經修補一次仍無法執行而保守降級為 Important）、但因 Round 2 僅阻擋 Critical 或屬於本 PR `Non-goals` 之外的既有缺陷而未阻擋合併者。

### D2：Step 5c 改為四路過濾閘門，合併前禁止建票

在進入後續流程前，對非阻擋項目依序執行四路分流：

1. 未實證、未重現、現行架構不可達與 Actionable NIT：留在 Step 5b 的 PR 留言，禁止建立 GitHub issue。
2. Round 2 單檔小修當場結清：已確認可觸發的真問題若修改範圍在單一檔案、15 行以內且不改變公開介面或 Review Contract，在進入 Step 8 前直接修完並通過本地與遠端 CI（套用 Step 6 的 `preflight-pr-push.sh` 守衛推送），不啟動 Round 3 重審，也不建票。
3. 進行中 Spectra change 優先承接：若項目隸屬當前未封存（active）的 Spectra change（如規格條文對齊、開旗標前置條件、archive 前確認項），寫入該 change 的 `tasks.md` 由 `spectra archive` 把關，禁止另建 GitHub issue。
4. 獨立跨範圍問題延至合併後建票：僅通過上述三道過濾後仍需獨立追蹤的已實證問題，寫入 `$REVIEW_DIR/deferred-issue.md` 候選檔，留待 Step 10 確認 PR 已 `MERGED` 後建立。PR 尚未合併（含 circuit breaker 暫停或 `Return to redesign`／`CLOSED`）時絕不執行 `gh issue create`。

### D3：Step 10b 合併後具名建票與正反雙向契約測試

- 在 Step 10 確認 PR 已 `MERGED` 並取得 merge commit SHA 後，若存在待建票的 `Verified Deferred Important`，建立每個 PR 至多一張 GitHub issue（禁止將無關微末雜項混裝入票；雜項留在 PR 留言）。
- 標題必須寫明具體模組與問題症狀，禁止使用 `--title "Deferred from review: PR #..."` 制式標題；標籤依問題性質貼上目標儲存庫既有領域標籤（如 `bug`、`spec-gap`、`harness`、`infra`），可搭配 `deferred-from-review` 標註來源。
- `test_convergence_contract.py` 同時將新錨點加入 `REQUIRED_ANCHORS`、將舊制式標題 `--title "Deferred from review: PR #` 與 circuit breaker 強制建票措辭加入 `FORBIDDEN_STRINGS`，確保退回舊寫法時測試立即變紅。

## Risks / Trade-offs

- **[單檔 15 行小修未再經 3-voice 重審]** → 緩解：僅限單檔 ≤ 15 行且不改公開介面與契約，仍須通過完整本地與遠端 CI 並交 Step 8 Human Quick Pass 人工檢視 diff。相比另開 PR 的十倍成本與噪音，風險可控。
- **[寫入 active change `tasks.md` 產生額外 commit]** → 緩解：在 PR 合併前隨同分支推送（經 `preflight-pr-push.sh` 與 CI），讓待辦與程式碼／規格在同一個 PR 原子落地。

## 1. 契約檢查器與負向案例

- [x] 1.1 在 `check_convergence_contract(text)` 實作「Mechanical conformance checks protect the Review Contract」及設計決策「Mechanical checker 同時保護必要規則與已知矛盾」：必要錨點涵蓋五段 contract、frozen snapshot、`Contract mapping:`、human acceptor、blocking-set LGTM、conditional R2，forbidden rules 涵蓋現有 unanimous/NIT veto wording；以 `uv run pytest plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py -q` 驗證既有測試仍通過。
- [x] 1.2 新增合成 mutation tests，驗證「Deep review requires a confirmed Review Contract」、「Contract amendments preserve review integrity」與「Cross-debate Round 2 is conditional」的必要文字缺失會轉紅，且插入 `全員 LGTM（含 actionable NIT）` 會失敗；以指定 pytest 檔案收集並通過所有新增案例驗證。

## 2. Review Contract 與 finding 邊界

- [x] 2.1 在 `/pr-cycle-deep` pre-review 流程交付設計決策「Review Contract 使用五個固定段落並在 R1 前確認」與 Implementation Contract 的「Observable behavior」及「Interface and data shape」：新／既有 PR 都必須取得 human-confirmed frozen contract，缺段落停止 reviewer launch；以 checker 真實檔案測試及人工比對五個固定 headings 驗證。
- [x] 2.2 在 R1 prompt、aggregation 與 amendment 規則交付「Blocking findings map to a closed set of merge-gate sources」、「Scope exclusions and deferrals do not become merge gates」、「Residual-risk acceptance belongs to a human」，並落實設計決策「Blocking finding 必須映射到封閉的 merge-gate 來源」、「Human 單獨擁有 residual-risk acceptance」、「Contract 凍結且只有 material amendment 會重啟 R1」；缺 mapping、缺 acceptor及未確認 amendment 必須採用 Implementation Contract「Failure modes」的 disposition，以 pytest anchors 和人工 review prompt/aggregator content assertion 驗證。

## 3. LGTM、conditional R2 與整體驗證

- [x] 3.1 交付「LGTM depends on contract compliance and the blocking set」與設計決策「Aggregator 的 blocking set 是唯一 LGTM gate」：移除 frontmatter／convergence 的 unanimous voice veto，只有 non-blocking finding 的 `NEEDS_CHANGES` 不阻止前進；以 forbidden mutation tests 與真實 SKILL.md checker 驗證。
- [x] 3.2 交付設計決策「Cross-debate R2 使用 activation gate」：所有 voice 仍跑 R1，只有 candidate blocker 或 blocking disagreement 才跑 R2，clean R1 明確輸出 skip 訊息；以 conditional-R2 mutation test 與人工檢查 R1→gate→R2/aggregate 兩條路徑驗證。
- [x] 3.3 依 Implementation Contract「Acceptance and verification」執行指定 pytest、`spectra analyze add-pr-review-contract`、`spectra validate add-pr-review-contract` 與 1220 行預算檢查，並確認「Scope boundaries」只修改 deep skill、checker/tests 與本 change artifacts；所有命令成功且 `git diff --name-only` 無 scope 外檔案才完成。

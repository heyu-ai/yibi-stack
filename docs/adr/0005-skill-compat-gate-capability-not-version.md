---
id: "0005"
title: "Skill 相容性閘門用能力探測，不用 semver 版本字串比對"
status: proposed
date: 2026-07-18
deciders: [howie]
related:
  issue: 256
  supersedes_clause:
    adr: "0004"
    note: "取代 ADR-0004『負面／風險』段中『版本檢查』那一半；『能力檢查』那一半保留並升為主機制"
  prs:
    - number: 249
      note: "Phase 1 白老鼠：PR #249 review 收斂出版本字串閘門不可行"
---

## Context

ADR-0004（Plugin-Primary 交付）在「負面／風險」段訂下一條被標為「最重要的一條」的要求。原文：

> - **版本落差取代路徑落差。** 使用者安裝的 CLI 可能落後 plugin 的 SKILL.md。每個 skill 都必須
>   加上能力／版本檢查並 fail-loud。這比今天「靜默解析到錯 repo」是**更好的失敗**，但它是新增
>   的失敗模式。**這是最重要的一條**：若少了它，Phase 2/3 等於把大聲的路徑失敗換成安靜的行為
>   不一致——嚴格來說比現狀更糟。

問題出在這條要求同時提了「能力／版本檢查」兩種機制，而其中**「版本檢查」（semver 字串比對）在
ADR-0004 自己指定的安裝方式下做不到**：

ADR-0004 的安裝路徑是 `uv tool install git+https://github.com/heyu-ai/yibi-stack`
（見 ADR-0004「驗證閘門」段，行 159），它裝的是 **HEAD**。但套件的版本字串取自上次 release 時
寫進 `pyproject.toml` 的值——**兩次 release 之間的每一個 commit 都回報同一個版本字串**。因此：

- 一個裝了「上次 release 之後、含 breaking change 的 HEAD」的使用者，其 `<cli> --version` 仍印
  出上次 release 的版本號。
- semver 比對（「skill 需要 >= X.Y.Z」）對這種 CLI 會回報 PASS。凍結的版本字串仍表示宣告的 release
  baseline，但在本 repo 的靜態版本字串 + 未標 tag 的 git HEAD 安裝模式下，這項資訊不可靠且不完整，
  不足以單獨作為相容性閘門：它無法區分「真的相容」與「HEAD 已經 breaking 但版本字串還沒 bump」。

PR #249 review 收斂出：套件 semver 版本字串不足以單獨作為相容性閘門，portman 隨即**已改用存在性＋
可執行閘門（`command -v` + `--version` 退出碼），不再用 semver 比對**。這與 ADR-0004 文字之間留有
已知歧異——本 ADR 就是要消解這個歧異。

**ADR-0004 曾被 in-place 修訂過一次，之後已完整還原**，目前仍是原始 accepted 狀態、含這條做不到
的要求。這也暴露出本 repo 尚無「ADR 該如何修訂」的成文慣例（見下方決定 5）。

## Decision（proposed — 待 howie 裁決）

1. **確認推翻成立。** ADR-0004 那條要求裡的 **semver 版本字串比對**部分不予採用；`command -v` +
   能力探測是相容性閘門的主機制。ADR-0004 的其餘部分（含「能力檢查 + fail-loud」的精神）不變。

2. **`<cli> --version` 的輸出值降為診斷用途。** 版本字串只用來讓使用者／log 看到宣告的 release
   baseline，不比較其輸出值、不以 semver 作為相容性閘門。其退出碼仍依決定 3 用於可執行性檢查。

3. **存在性＋可執行閘門用 `command -v <cli>` + 非零退出即 fail-loud。** skill 的前置檢查確認 CLI
   有裝且可執行：`command -v <cli>` 找得到，並以 `<cli> --version` 的退出碼作為可執行性 smoke test，
   不比較其輸出的版本字串。任一失敗即以清楚訊息 fail-loud（指出「請
   `uv tool install git+...` 安裝／升級 `<cli>`」），而非靜默 fallback；但 `command -v` 只能證明
   PATH 中有同名指令，不能單獨證明解析到預期的 CLI。

4. **真正的相容性閘門用能力／protocol revision 探測，不用版本號。** 當某個 skill 真的依賴某項
   CLI 行為時，用行為層級的探測判斷相容：比對 `<cli> capabilities`（或等價子命令）輸出的能力
   集合、或一個明確的 protocol/schema revision 整數，而非版本字串。能力集合是 CLI 對自己「會做
   什麼」的權威宣告，不受「release 之間版本字串凍結」影響。

5. **在有 skill 真正需要版本專屬功能之前，不要設計版本專屬閘門。** 現況沒有任何 skill 依賴某個
   CLI 的版本專屬新功能；為不存在的需求預先設計閘門，只會製造出資訊不可靠且不完整的假保證。
   等到第一個真需求出現時，再依決定 4 加上該功能對應的能力探測。

6. **建立 ADR 修訂慣例，寫進 `docs/adr/README.md`：**
   - **In-place 修訂 + 註記**：僅限錯字、連結、補充脈絡等**不改變決定實質**的更動；須在該 ADR
     底部加一則帶日期的 `## Amendments` 記錄說明改了什麼、為何改。
   - **Superseding / 部分取代 ADR**：任何**改變決定實質**的更動，一律開新 ADR，於 frontmatter 用
     `supersedes`（整份取代）或 `supersedes_clause`（取代某段）指向舊 ADR，並在舊 ADR 底部加
     `## Superseded by` 反向連結。舊 ADR 的 `status` 視情況改為 `superseded`（整份）或維持
     `accepted`，並在該 ADR 加註記指向取代它的 ADR（部分取代可用文末 `## Superseded by` 區塊）。
   - **理由**：ADR 是決策的歷史紀錄，實質更動若就地覆寫會抹掉「為何當初這樣決定、後來為何改」的
     軌跡——本 ADR 自身（ADR-0004 曾被 in-place 改實質、又還原）正是反例。

## Consequences

- **正面**：Phase 2/3（mycelium CLI change 等）不會複製一條做不到的閘門；相容性保證從「假的
  版本 PASS」換成「真的能力探測」，是有資訊的檢查。fail-loud 的精神（ADR-0004 最重視的那點）
  由決定 3 的存在性閘門承接，不是被丟掉。
- **負面 / 風險**：能力探測需要 CLI 端提供 `capabilities`（或等價）子命令；在第一個真需求出現前，
  各 skill 只有「存在性 + 可執行」層級的閘門，無法擋「CLI 有裝但行為已 breaking」——但這正是決定 5
  的取捨：那種閘門在今天沒有真需求可對應，硬設只會是假保證。
- **對 ADR-0004 的關係**：本 ADR 部分取代 ADR-0004「負面／風險」段的「版本檢查」子句；ADR-0004
  其餘決定（Gap A 抽 CLI、Gap B 定位修復、`scripts/` 排除於 wheel 等）不受影響。

## 待裁決事項（howie）

- [ ] 確認決定 1（推翻 semver 版本字串閘門）成立。
- [ ] 確認決定 3/4 的替代機制（`command -v` 存在性閘門 + 能力探測）。
- [ ] 確認能力集合如何避免過時：決定 4 首次實作時須定義 machine-readable 格式與 CI contract test，
  讓能力宣告和實際行為保持同步。
- [ ] 確認過渡期取捨：skill 已依賴 CLI 行為、但尚只有存在性閘門的窗口，是可接受且有時限的風險。
- [ ] 確認決定 6 的 ADR 修訂慣例文字，並同意寫進 `docs/adr/README.md`。
- [ ] 核准後把本 ADR `status` 改為 `accepted`。

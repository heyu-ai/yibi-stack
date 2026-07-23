## Context

issue #145（2026-06-08 建立）打包兩個文件缺口：lifecycle skill 缺 `/code-review --fix` opt-in
路徑、skill authoring 規範缺 `disallowed-tools` 與 `\$` escape 文件。2026-07-23 盤點確認
五項症狀中四項未完成、一項目標檔案已不存在（pr-review-cycle-mob 已由 pr-cycle-deep 取代）。

三個前提已對官方文件（code.claude.com）重新驗證（2026-07-23）：

- `/code-review --fix` 存在且語意不變；`/simplify` 自 v2.1.154 起為 cleanup-only（不找 bug）。
- 官方 frontmatter key 為 `disallowed-tools`（hyphen 形式）；語意為「skill 執行期間自可用
  工具池移除列出的工具，turn 結束後解除」；值接受空格/逗號分隔字串或 YAML list。
- `\$` escape：僅單一反斜線直接置於 token（數字、ARGUMENTS、已宣告參數名）前才轉義；
  反斜線在其他 `$` 前原樣保留。

現有落點：pr-review-cycle 的 Step 2 與 pr-cycle-deep 的 Solo Review 段落各有一句
「/code-review does not modify code」的 report-only 措辭；rule 11 已有 effort 與
v2.1.186 frontmatter keys 的完整段落，`disallowed-tools` 是唯一缺席的官方 key。

## Goals / Non-Goals

**Goals:**

- 兩個 lifecycle runbook 補上 opt-in auto-apply cleanups 小節，預設 report-only 不變。
- rule 11 補 `disallowed-tools` 與 `\$` escape 官方語意；rule 13 補 layer 消歧 cross-ref；
  skill 模板補註解行。

**Non-Goals:**

- 不改 pr-cycle-fast：它僅在 fallback 引用 /code-review，report-only 語意在該處正確。
- 不改 mob-code-review-only：review-only 是它的設計契約，加自動套用路徑違反其定位。
- 不改預設行為：report-only 仍是預設，本 change 只補「使用者主動要求時怎麼走」的指引。
- 不在本 change 把 `disallowed-tools` 導入既有 skill（如 issue-triage）：實際採用需逐一
  評估各 skill 的工具需求，另開 change。
- 不恢復或另建 pr-review-cycle-mob 對應內容：該 skill 已由 pr-cycle-deep 取代。

## Decisions

### 採用官方 hyphen 形式 disallowed-tools，不用 issue 原文的 disallowedTools

官方文件 frontmatter 參考表使用 `disallowed-tools`。v2.1.186 起 key 名
case/separator-insensitive 是 runtime 的容錯，不是文件風格的授權——文件一律寫官方
canonical 形式，並在段落內註記 runtime 容錯這件事（引用 rule 11 既有的 v2.1.186 段落）。

### opt-in 小節落點：pr-review-cycle 與 pr-cycle-deep 兩處，措辭一致

issue 原文的第二落點 pr-review-cycle-mob 已不存在；其後繼者中 pr-cycle-deep 有同樣的
「does not modify code」措辭（Solo Review 段落），是語意上的正確替代落點。
mob-code-review-only 同為後繼者但契約是 review-only，明確排除。
兩處措辭保持一致（spec 的 Wording consistent scenario），避免同一契約兩種說法。

### rule 11 為 owner，rule 13 只放 cross-ref 消歧小節

依 rule 11 的 Dual-Source Document Ownership 紀律：`\$` escape 的完整規則只寫在 rule 11
（skill authoring 的 owner 文件）；rule 13 的小節只負責一件事——告訴讀者這是
Markdown/skill-body 層的替換機制、不是 bash quoting，完整規則見 rule 11。
避免兩份完整說明日後 drift。

### 官方引文照貼原文並加驗證戳記

依 rule 11 的 Cross-doc Cite 紀律（方向性主張必貼原文）與「verified 是版本主張」紀律：
兩段官方文件引文照貼英文原文，並標注來源 URL 與查證日期（2026-07-23）。
`\$` escape 的邊界行為（`\\$1` 不轉義等）在 apply 階段以拋棄式 slash command 實測一次，
把實測時的 Claude Code 版本寫進戳記——文件主張與 probe 結果綁定版本，供日後 re-probe。

### plugin 內容變更走 lockstep version bump

plugins/pr-flow 下兩個 SKILL.md 變更屬 plugin 內容變更，依本 repo 慣例 PR 內含
lockstep bump：以 bash scripts/sync-plugin-versions.sh 帶入新 patch 版本同步所有
plugins/*/package.json（sdd plugin 的 .claude-plugin/plugin.json 由該腳本或手動同步，
apply 時依 CLAUDE.md 的 sdd 版本 lockstep gotcha 檢查）。不自跑 make release。

## Implementation Contract

本 change 為純文件變更（SKILL.md / rules / template），無 runtime、build、tooling 行為變更；
唯一的機械效果是 plugin 版本號 bump。驗收條件：

- 兩個 runbook 各有一個「Auto-apply cleanups (optional)」小節，位於 report-only code review
  區塊之後；小節內含：opt-in 條件、/code-review --fix 與 /simplify 分工、
  「套用後變更走既有 diff-review + commit 流程」三要素。
- rule 11 有 disallowed-tools 段落（官方引文 + key 名 + 值格式 + 語意 + 使用情境 + 戳記）
  與 `\$` escape 段落（官方引文 + 邊界表 + probe 戳記）。
- rule 13 有 layer 消歧小節，cross-ref rule 11。
- skills/_template/SKILL.md.tpl frontmatter 有 disallowed-tools 註解行。
- make ci 全綠（含 markdownlint：注意 MD028 blockquote 與 MD013 行長）；
  git add 後再跑（未 add 的新內容 --all-files 掃不到）。
- plugins/*/package.json 版本一致且高於 main 當前版本。

範圍邊界：只動 Impact 列出的六個檔案；不動 pr-cycle-fast、mob-code-review-only、
不動任何既有 skill 的 frontmatter（模板除外）。

## Risks / Trade-offs

- [官方文件語意再變（doc rot）] → 引文帶來源與查證日期戳記；`\$` 邊界行為在 apply 時
  本機 probe 並記版本，供日後 re-probe 判斷是否過期。
- [兩個 runbook 的 opt-in 措辭日後各自演化 drift] → spec 的 Wording consistent scenario
  把一致性寫成可驗收條件；日後修改任一處時 spec 可供 cross-check。
- [markdownlint 回圈（MD028/MD013）] → 依 rule 11 既有指引，commit 前先跑
  pre-commit markdownlint-cli2 對六個檔案單檔驗證。
- [`\\$1` 等邊界的官方描述與實際 runtime 不一致] → probe 為準：若實測與官方文字不符，
  文件記實測行為並標注差異，不照抄官方文字。

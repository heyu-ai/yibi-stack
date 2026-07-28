# Plan: `/codex-cli` — Claude 規劃、Codex 實作、Claude 驗收

本文件記錄設計決策與被否決的方案。執行細節在
`plugins/3rd-tools/skills/codex-cli/SKILL.md`（runbook）與同目錄的 `contract.md`（委託契約）。

## Problem

這個 repo 目前有三條 Codex 路徑，全部是**唯讀**的：

| 既有入口 | sandbox | 職責 |
|---|---|---|
| `plugins/3rd-tools/skills/codex-consult/SKILL.md:76` | `-s read-only` | 問答式第二意見 |
| `plugins/3rd-tools/skills/codex-review/SKILL.md:179` | `-s read-only` | 對 branch diff 做 review |
| `plugins/dev-cycle/skills/pr-cycle-deep/` | `-s read-only` | mob review 的一票 |

沒有任何入口讓 Codex **寫 code**。想委託實作只剩 `~/.claude/agents/fable.md` 這個全域 agent，
而它有三個問題讓它不適合當這個缺口的答案：

1. **完全沒有規則傳遞**。`fable.md:93` 的 packet 只有「別碰 git、別裝套件」，
   Codex 收不到 repo 的雙語規範、bash 反模式、module 結構等任何約束。
2. **驗收只有 Gemini 一個 P1 gate**（`fable.md:116`），不跑 repo 自己的 CI。
   這正踩到全域 CLAUDE.md 記的那條：委託外部模型時驗收清單必須等於 repo CI 全面，
   手挑子集會讓對方「宣稱全綠」與「CI 真的綠」脫鉤。
3. **不在 repo 內**，無法隨 repo 演進更新，也不受本 repo 的 lint / CI 管轄。

## Why Codex ignores the rules today

`AGENTS.md` 是 Codex CLI 原生會讀的規則檔，直覺上該把規範寫在那裡。但本 repo 的 `AGENTS.md`
**被 gitignore**（`.gitignore:259`，與 `GEMINI.md` 同一段註解「Spectra auto-generated files」）：
它是 `spectra update` 的產物，不進版控，且下一次 `spectra update` 會覆寫。內容也只有 Spectra
那段 marker block，沒有任何編碼規範。

`CLAUDE.md` 與 `.claude/rules/` 則是 Claude Code 專屬機制，Codex 不會自動讀。

所以「Codex 不 follow rule」不是提示詞寫得不夠好，是**結構性的**：它從來沒拿到過那些規則，
而唯一原生的傳遞管道剛好是本 repo 唯一不進 git 的那個檔。

## Design decisions

### D1 — 規則傳遞：skill 自帶契約 + 每次動態挑 rules

常駐約束寫在 `plugins/3rd-tools/skills/codex-cli/contract.md`，由 SKILL.md 在組 packet 時
併入前綴。每次委託時，再由 Claude 依本次任務會碰到的路徑，挑出匹配的 `.claude/rules/*.md`
列進必讀清單。

契約隨 skill 走而不是寫進 repo 根目錄，有三個理由：`AGENTS.md` 不進 git 也會被覆寫（見上節）；
契約的內容其實是通用的（禁讀路徑、不碰 git、語言規範、跑全量 CI），repo-specific 的部分本來
就由動態挑 rules 承擔；skill 是 `scope: global`，契約隨它安裝才能跨 repo 生效。

被否決的方案：

- **寫進 `AGENTS.md`**：原始設計方向，因上述 gitignore 事實而作廢。若日後要走這條，
  必須先把 `AGENTS.md` 從 spectra 的生成清單中拆出來，那是另一個範圍的決策。
- **把 14 個 rule 檔全文塞進契約**：每次 Codex 呼叫都吃下整份規則語料，token 成本不成比例；
  只列路徑而不列內容，則 Codex 未必主動去讀——折衷是列路徑加一行摘要，並要求它回報讀了哪些。
- **只靠 packet 動態注入、不要常駐契約**：Codex 在 `-s workspace-write` 下會自主探索與多輪
  修改，packet 只在第一輪起作用，沒有常駐約束兜底。

契約段落有兩個非顯而易見的要求，都來自實帳教訓：

1. **禁讀清單必須精確，且要顯式宣告「應該讀」的路徑**。只寫禁區（`~/.claude/`、
   `.claude/skills/`）時，外部模型會保守擴大解讀成整個 `.claude/` 都不碰，
   連指名要讀的 `.claude/rules/*.md` 都跳過。契約因此寫成
   「MUST NOT read `~/.claude/`、`~/.agents/`、`.claude/skills/`、`agents/`」
   加上「You SHOULD read `.claude/rules/*.md`」。
2. **驗收清單等於 repo 全量 CI**，不列 pytest / ruff / mypy 子集。

### D2 — 寫入範圍：當前 worktree + `workspace-write`

`codex exec -s workspace-write -C "$ROOT"`，直接改目前 checkout，但派工前兩道 gate：

- **branch gate**：在 `main` / `master` 就停。
- **工作區乾淨 gate**：`git status --porcelain` 非空就停——否則收貨時無法分辨哪些改動是 Codex 的。

被否決的方案：

- **skill 自行開 worktree 隔離**：與背景 session 既有的 `EnterWorktree` 機制打架，
  且 `.claude/rules/15` 明載 linked worktree 不可 checkout `main`，多一層自動化就多一類事故。
- **先 dry-run 再實作**：多一輪往返，日常任務不划算；高風險改動由使用者自行先跑
  `/codex-consult` 取得計畫即可。

### D3 — 驗收：Claude review + 最多 2 輪回修

Codex 的自述**不可信**，收貨一律以 git 為準（`git status --short` + `git diff --stat` + 讀完整
diff），再跑 repo 全量 CI。Claude 找到的 finding 逐字回饋 Codex 修，最多 2 輪；
仍有問題就停下並如實列出未解 finding，不假裝完成。

被否決：再串第三方模型交叉 review——與既有 `/mob-code-review-only`、`/pr-cycle-deep` 職責重疊，
需要時使用者可自行接續。

## Flow

| Step | 動作 | 失敗處置 |
|---|---|---|
| 0 | preflight：binary / auth / repo root / branch gate / 工作區乾淨 gate | 任一不過即停 |
| 1 | Claude 讀檔並寫 self-contained brief（Codex 無對話歷史） | — |
| 2 | 依改動路徑挑 rules，產生必讀清單 | 無 `.claude/rules/` 時 `[WARN]` 續跑 |
| 3 | `codex exec -s workspace-write -o <last-message>` | 非零退出即停，不可把失敗輸出當成果 |
| 4 | 以 git 查核實際改動 | Codex 宣稱完成但 diff 為空 → `BLOCKED` |
| 5 | 跑全量 CI，再確認 `git diff --name-only` 為空 | 非空表示 formatter 就地改過檔，需一併提交 |
| 6 | Claude review → finding 逐字回饋 Codex（≤ 2 輪） | 逾輪次即停並列出未解 finding |
| 7 | 報告 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` | — |

Step 5 的第二個檢查看似多餘，實則是本 repo 踩過的實帳（PR #248）：pre-commit 的 formatter hook
是**就地改檔**後才回報通過，所以本地綠是真的，卻無法從 commit 出來的樹重現，CI 必紅。

本 skill **不做** commit / push / PR——那屬於使用者或既有 `/pr-cycle-*` 的職責。

## Trigger boundaries

`description` 需明確把三個鄰居的領地讓出去，避免 over-trigger：

| 意圖 | 正確入口 |
|---|---|
| 問 Codex 技術問題（無 diff 可看） | `/codex-consult` |
| 請 Codex review 現成 diff | `/codex-review` |
| 多模型 mob review | `/mob-code-review-only`、`/pr-cycle-deep` |
| **規劃 → 讓 Codex 寫 code → 驗收** | **`/codex-cli`（本 skill）** |

## Residual risks

- **Codex 可能不讀被指名的 rule**。契約要求它在報告中聲明讀了哪些 rule 檔，把「沒讀」
  從不可觀測變成可觀測，但無法強制。Claude 在 Step 6 review 時仍須自行對照規則。
- **Prompt injection 經由 repo 內容**。與既有 `/codex-review` 同一信任邊界（trusted repo 假設），
  `-s workspace-write` 讓風險高於唯讀路徑：Codex 可寫檔。branch gate 與工作區乾淨 gate 讓
  任何非預期改動都能用 git 完整還原，這是主要的緩解。
- **跨 repo 使用時無 `.claude/rules/`**。此時只有 skill 自帶的 `contract.md` 生效，
  repo-specific 的規範完全落空；skill 會 `[WARN]` 而非靜默跳過，讓使用者知道這次派工
  少了哪一層約束。

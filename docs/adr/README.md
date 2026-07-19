# Architecture Decision Records

此目錄記錄 yibi-stack 的架構決策。

## Index

| ID | Title | Status | Date |
|----|-------|--------|------|
| [0001](0001-spectra-amplifier-plugin-redesign.md) | Spectra Amplifier Plugin 重設計 — 對齊 yibi-mvp ADR-0006/0008 (Wave D) | accepted | 2026-05-27 |
| [0002](0002-bash-parser-bug-hook-workaround.md) | CC Bash Parser Bug Workaround — PreToolUse Hook for D3/D4/D5 Patterns | accepted | 2026-06-02 |
| [0003](0003-gwscli-go-gmail-cli-design.md) | gwscli — Go Native Gmail CLI 設計 | accepted | 2026-04-14 |
| [0004](0004-plugin-primary-packaging.md) | Plugin-Primary 交付 — 把 tasks/* 做成可安裝的 CLI distribution | accepted | 2026-07-14 |
| [0005](0005-skill-compat-gate-capability-not-version.md) | Skill 相容性閘門用能力探測，不用 semver 版本字串比對 | proposed | 2026-07-18 |

## ADR 修訂慣例

（本慣例由 ADR-0005 提出，待核准後生效）

ADR 是決策的歷史紀錄。實質更動若就地覆寫，會抹掉「為何當初這樣決定、後來為何改」的軌跡。
故區分兩種更動：

| 更動類型 | 做法 |
|----------|------|
| **不改變決定實質**（錯字、連結、補充脈絡） | In-place 修訂，並在該 ADR 底部加一則帶日期的 `## Amendments` 記錄，說明改了什麼、為何改。 |
| **改變決定實質**（推翻、替換機制、調整範圍） | 一律**開新 ADR**。新 ADR frontmatter 用 `supersedes`（整份取代）或 `supersedes_clause`（取代某段）指向舊 ADR；舊 ADR 底部加 `## Superseded by` 反向連結。舊 ADR `status` 視情況改 `superseded`（整份）或維持 `accepted`，並在該 ADR 加註記指向取代它的 ADR（部分取代可用文末 `## Superseded by` 區塊）。 |

反例：ADR-0004 曾被 in-place 改動實質、之後又還原，過程在文件與 main 線性歷史上無跡可循——正是
此慣例要避免的。

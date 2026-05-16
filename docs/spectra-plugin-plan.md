# Plan: 把 spectra + openspec + spectra-amplifier 工作流封裝為可安裝 plugin

> **狀態（2026-05-15）**：全部 7 個 Step 已完成，plugin 住在 `plugins/spectra/`。
> Phase 2（yibi-stack 拆 repo）也已完成。本文件作為設計決策記錄保留。
>
> **v0.2 更新（2026-05-16）**：plugin 改名為 `sdd`（`plugins/spectra/` → `plugins/sdd/`），PR review skills 移至 `plugins/pr-flow/`，`qa-test-design` 移入 `sdd`。本文件記錄 v0.1 計畫，現況請以 `plugins/sdd/` 和 `plugins/pr-flow/` 為準。

## Context

新工程師即將加入協作，需要一鍵安裝目前散落於 `skills/`、`docs/openspec/` 的「Spectra 變更管理 + Spec Kit 五層展開」工作流。

- `skills/spectra-amplifier/SKILL.md` 是核心方法論（純 markdown，`scope: global`、`type: know`、無 Python 依賴）。
- `skills/pr-review-cycle/`、`pr-review-cycle-mob/`、`pr-review-cycle-codex/` 的 Step 8/10/11 收尾呼叫 `spectra list/archive/analyze`。
- `docs/openspec/changes/auto-detect/` 是 openspec 格式的真實範例。
- 本 repo 已是 marketplace（`.claude-plugin/marketplace.json`），`bash-hygiene` 作為 scaffold 樣板。

**Spectra CLI 維護狀況研究結果**：

| 項目 | 事實 |
|------|------|
| Upstream repo | https://github.com/kaochenlong/spectra-app（public，open source，**578 stars**） |
| 創立日 | 2026-02-04（3 個月內爆紅） |
| 維護節奏 | v2.2.5 (4/22) → v2.3.0 (5/8) → **v2.3.1 (5/12)**，月更甚至週更 |
| 作者 | Chien Lung Kao（5xCamp Ruby 訓練機構社群熟人；homepage `spectra.5xcamp.us`） |
| 性質 | **公開個人/社群專案**（非商業 SaaS），無 license 欄位但已上 Homebrew Cask 等同默許散佈 |
| **安裝管道（已確認）** | `brew install --cask spectra-app`（已上 homebrew-cask core，95.5MB） |
| 平台 | **macOS only**（cask 限定；無 Linux/Windows binary） |
| 二進位 | `/Applications/Spectra.app`，bundle ID `app.spectra.dev`，arm64 thin binary |
| AI 整合 | `spectra init --tools claude,cursor` 是內建 first-class 設計 |
| Schema | `spec-driven (package) — Default OpenSpec workflow` 是 Spectra 預設 schema |

→ **結論**：Spectra 是活躍維護的公開個人專案，可放心 depend；唯一現實限制是 **macOS only**。

## Goal

讓新工程師執行 `claude plugin install spectra@yibi-stack` 後立刻獲得：

1. spectra-amplifier 方法論 skill（Spec Kit 五層展開）
2. pr-review-cycle 三個 skill 的 Spectra Archive 收尾步驟
3. openspec 目錄格式範本（proposal / design / tasks / spec delta）
4. SessionStart hook：偵測 `spectra` CLI 是否在 PATH，缺失時提示但不阻擋（degraded mode）
5. `/spectra:setup` slash command：一鍵診斷 + 引導去 spectra.dev 下載

## Recommended Approach

**單一 `plugins/spectra/` plugin，內含 4 個 skill subfolder + hook + 1 個 slash command + 範本**。

採取「**徹底搬遷 + degraded mode**」策略：

- 把 4 個相關 skill 從 `skills/` **整個搬進** `plugins/spectra/skills/`，外層 `skills/` 改為相對路徑 symlink 反向指回（make install 不受影響）。
- plugin README 第一段明確標示 **prereq: 從 https://spectra.dev 下載 Spectra.app for macOS**。
- SessionStart hook 偵測缺失時，inject 一行提示「amplifier 方法論可獨立使用，但 archive/validate/analyze 需要 CLI」——不 block。
- 不 wrap `/spectra-propose`、`/spectra-apply`（那些是 spectra app 自帶；wrap 會 drift）。只加一個 `/spectra:setup` 做依賴診斷。

### 為什麼選這個方案

1. **single source of truth**：4 個 skill 整體搬遷，plugin 是唯一住址。
2. **symlink 相容性**：外層 `skills/<name>/` 為相對路徑 symlink，git clone 到任何路徑都能正常解析（R2 緩解）。
3. **degraded mode 保留跨平台彈性**：amplifier 純 markdown 流程仍可用，只是無法執行 archive。
4. **不發明安裝幻覺**：spectra.dev 是唯一真實安裝管道，README 老實寫。

## Implementation Steps（已完成）

### ✅ Step 1：建立 plugin scaffold

```
plugins/spectra/
├── .claude-plugin/plugin.json
├── package.json
├── README.md
├── hooks/
│   ├── hooks.json
│   └── check-spectra-cli.sh
├── commands/setup.md
├── skills/
└── references/
```

### ✅ Step 2：搬遷 4 個 skill

```
plugins/spectra/skills/spectra-amplifier/SKILL.md
plugins/spectra/skills/pr-review-cycle/SKILL.md
plugins/spectra/skills/pr-review-cycle-mob/SKILL.md
plugins/spectra/skills/pr-review-cycle-codex/SKILL.md
```

外層 `skills/<name>/` 為相對路徑 symlink（`../plugins/spectra/skills/<name>/`）。

### ✅ Step 3：hook 與 slash command

- `hooks/hooks.json`：SessionStart hook，呼叫 `check-spectra-cli.sh`
- `hooks/check-spectra-cli.sh`：`command -v spectra` 通過 → silent；失敗 → degraded mode 提示
- `commands/setup.md`：`spectra --version`、`spectra schemas`、PATH 狀態診斷

### ✅ Step 4：references/ 範本

```
references/openspec-layout.md
references/proposal-template.md
references/design-template.md
references/tasks-template.md
references/spec-delta-template.md
references/spectra-archive-snippet.md
```

### ✅ Step 5：README.md

章節：What it does → Prerequisites（`brew install --cask spectra-app`）→ Install → What you get（表格）→ Linux/Windows degraded mode note → License

### ✅ Step 6：marketplace.json 已包含 `spectra` entry

### ✅ Step 7：skills/README.md 索引

spectra-amplifier、pr-review-cycle 三個 skill 的索引行標註住址在 `plugins/spectra/`。

## 安裝測試

```bash
claude plugin marketplace add howie/yibi-stack
claude plugin install spectra@yibi-stack

# 開新 session，應看到 SessionStart hook 輸出
# (有 spectra CLI: silent; 無 spectra: 提示 spectra.dev)
```

### Symlink 兼容性測試

```bash
make install    # 應正常掃描到 spectra-amplifier (global scope)
make status     # 應顯示 spectra-amplifier 仍在 install 清單
```

### Degraded mode 測試

```bash
# 暫時把 spectra 移開
mv /usr/local/bin/spectra /usr/local/bin/spectra.bak
# 開新 session，hook 應提示「CLI not found, amplifier still usable」
mv /usr/local/bin/spectra.bak /usr/local/bin/spectra
```

## Risks（設計時的考量，已緩解）

| 風險 | 緩解 |
|------|------|
| **R2**：symlink 跨 git worktree 行為 | 用相對路徑 symlink（`../plugins/spectra/skills/...`），不用絕對路徑 |
| **R4**：plugin 名 `spectra` 與 macOS app 同名 | README 第一段明確聲明 plugin 不包含 binary |
| **R5**：hook 提示 macOS only 造成 Linux 困擾 | degraded mode 描述強調 amplifier 不依賴 CLI 仍可用 |

## Out of Scope (v0.1)

- `/spectra-propose`、`/spectra-apply` wrapper（spectra app 自帶，避免 drift）
- 自動偵測 `docs/openspec/` 目錄並建議 `spectra archive`
- Linux/Windows 正式支援（degraded mode 已足夠）
- `make sync-plugin-skills`（雙向 diff 檢查，留 v0.2）

# Agent Git Worktree 目錄架構與清理機制研究：內部巢狀（.claude/worktrees）vs 外部集中（~/.omp/wt）

> 日期：2026-09-06
> 背景：評估 Coding Agent（Claude Code、Oh My Pi / omp）在執行隔離任務、PR checkout 與並行分支開發時，Git Worktree 的存放位置（專案內部子目錄 vs 專案外部全域目錄）之架構取捨，以及對應的生命週期管理與清理機制。

---

## TL;DR

1. **專案內部巢狀（如 `.claude/worktrees/<name>/`）的致命傷在於「工具鏈相容性」**：
   巢狀 worktree 會使外部 CLI 工具（如 Antigravity CLI、OpenAI Codex CLI）、LSP 與程式碼掃描器在向上追溯 Git 根目錄時陷入 active workspace 混淆（如 yibi-stack 實測 issue #153：嵌套 worktree 導致 agy `@file` 解析失敗、進入無窮 agentic 檔案探索）。
2. **Oh My Pi (omp) 選擇將 agent-managed worktree 集中置於專案外部（`~/.omp/wt/`）**：
   保持主 repo 為乾淨的單一檔案樹，杜絕巢狀 Git 邊界混淆、IDE 索引穿透與 pre-commit hooks 誤掃。
3. **omp 支援階層式目錄自訂，但強制要求絕對路徑或 `~` 前綴**：
   順序為 `OMP_WORKTREE_DIR`（環境變數）> `worktree.base`（設定項）> `~/.omp/wt`（預設）。omp 刻意忽略相對路徑，以防在不同 cwd 執行時產生路徑跳躍。
4. **清理機制依場景分為三層，各司其職**：
   - **即時自動銷毀（Subagent 任務隔離）**：`task` 工具指定 `isolated: true`，在 macOS 走 APFS Copy-on-Write clone（秒開秒關），結束時由 `cleanupIsolation` 自動回收，零殘留。
   - **CLI 集中批次清理（PR 審查）**：集中於 `~/.omp/wt/` 的 PR checkout，透過 `omp wt clear [--dry-run|--all]` 一鍵全域收回，無需跨多個 repo 翻找。
   - **專案級分支安全清理（開發分支）**：透過 `/clean-wt` 依據「三項正面證據鏈（E1/E2/E3）」進行 fail-closed 判定，嚴格保護未提交檔案與未合併工作。

---

## 1. 架構對比：專案內部（.claude/worktrees）vs 專案外部（~/.omp/wt）

| 比較面向 | 專案內部巢狀（如 `.claude/worktrees/`） | 專案外部集中（如 `~/.omp/wt/`） |
| :--- | :--- | :--- |
| **預設實作者** | Claude Code (`EnterWorktree`) | Oh My Pi (`omp wt` / `pr_checkout`) |
| **工具鏈相容性** | ⚠️ **高風險**：易引發雙重 `.git` 解析失敗、外部 CLI workspace 混淆 | ✅ **零干擾**：主 repo 與 worktree 彼此是獨立的 sibling 樹 |
| **主目錄整潔度** | 需依賴 `.gitignore` 嚴格排除；漏掉時 IDE 索引、ripgrep、pre-commit 全被污染 | ✅ **主目錄永遠保持乾淨**，不影響主 repo 任何搜尋與檔案掃描 |
| **外部工具路徑** | 相對路徑（如 `--add-dir .`）容易失效或讀到父目錄 | 相對或絕對路徑皆指向獨立邊界，語意清晰 |
| **清理與盤點** | 散落於各個專案底下的隱藏目錄，日久極易遺忘並佔用磁碟空間 | ✅ **集中一處**，單一指令（`omp wt`）即可跨專案全景清點與清理 |
| **工作區安全性** | 若使用者執行 `rm -rf <project>` 或切換分支重置，內部 worktree 可能遭殃 | 即使主專案臨時 reset 或重抓，外部 worktree 依然獨立存在 |

### 為什麼巢狀 Worktree 會成為工具鏈的地雷？（以 yibi-stack 歷史事故為例）

1. **Issue #153：Antigravity CLI (agy) Agentic 逃逸與超時**
   在 nested worktree（`.claude/worktrees/<name>/`）環境下，agy 接收 `@file` 參數時無法正確向上解析主 repo 與 sub-worktree 的邊界，
   導致它認為檔案「不存在」，進而觸發 agy 的自主搜尋機制（agentic file-search）。
   它會開始翻遍整個磁碟尋找 stale scratch input，最終造成超時（10 分鐘以上）或針對錯誤的 repo 產生幻覺 review。
2. **`--add-dir .` 的 Active Workspace 解析失效（agy 1.1.22 實測）**
   agy 在 1.1.22 版本後不再將相對路徑 `.` 視為 active workspace。如果 worktree 嵌在內部且工具呼叫傳入相對路徑，外部程序會直接判定「無作用中的 workspace」，回傳 141 bytes 的空白拒答卻 exit 0，造成看似成功的靜默失敗。
3. **Pre-commit / Linter / Search 穿透**
   若 `.claude/worktrees` 稍有設定不慎未被工具排除，執行 `grep`、`fd`、`pytest` 或 `mypy` 時，會同時把主分支與多個 worktree 分支的幾十萬行程式碼全部載入記憶體，引發 OOM 或型別重複定義錯誤。

---

## 2. Oh My Pi (omp) 的 Worktree 設計與配置介面

omp 的設計哲學是將 **agent-managed 的臨時環境與使用者的主檔案樹徹底解耦**。

### 2.1 預設路徑與目錄命名

- **基礎目錄**：`~/.omp/wt/`（或 XDG-aware data root 底下的 `wt/`）。
- **子目錄命名規則**：`<number>-<repo-hash>`
  - `<number>`：PR 編號或工作任務 ID。
  - `<repo-hash>`：主專案路徑的 7 位 16 進制雜湊碼（`hashPath(primaryRepoRoot)`）。
  - **優點**：即使多個不同專案有相同 PR 編號（如 PR #42），也不會在 `~/.omp/wt/` 產生撞名衝突。

### 2.2 階層式路徑覆寫（Configuration Hierarchy）

omp 提供兩層自訂機制，依序解析：

1. **環境變數 `OMP_WORKTREE_DIR`**（優先度最高）：

   ```bash
   export OMP_WORKTREE_DIR="/Users/howie/.omp/wt"
   ```

2. **設定檔項 `worktree.base`**（在 `config.yml` 或 `settings.json`）：

   ```yaml
   worktree:
     base: ~/.omp/wt
   ```

3. **系統預設值**：`~/.omp/wt`。

> **設計關鍵規範**：
> omp 原始碼明確規範：**覆寫路徑必須是絕對路徑或以 `~` 開頭，相對路徑（如 `.claude/worktrees`）會被直接忽略並退回預設值**。
> 這是刻意的防御性設計：避免 agent 在不同的工作目錄（cwd）切換時，因為相對路徑解析產生非預期的目錄跳躍與散落。

---

## 3. omp 的 Subagent 隔離技術（Beyond Git Worktree）

除了標準的 Git Worktree 之外，omp 在子任務隔離（`task` 工具 `isolated: true`）層級引入了 OS 原生的檔案系統隔離技術（Platform Abstraction Layer, PAL：`pi-natives` / `pi-iso`）：

### 3.1 隔離後端支援矩陣

omp 依據作業系統能力自動協商最佳隔離後端（`isolation.backend: auto`）：

| 後端名稱 | 適用平台 | 機制 | 特點 |
| :--- | :--- | :--- | :--- |
| **`apfs`** | macOS (Darwin) | APFS Copy-on-Write (CoW) Clone | **首選**。微秒級克隆整棵工作樹，不佔額外磁碟空間，效能極高 |
| **`overlayfs`** | Linux | Linux Kernel OverlayFS / FUSE | 利用 upperdir/lowerdir 分層掛載，寫入隔離 |
| **`reflink` / `btrfs` / `zfs`** | Linux / BSD | 區塊層級 Copy-on-Write | 支援 CoW 的現代檔案系統克隆 |
| **`projfs`** | Windows | Windows Projected File System | 虛擬化檔案系統投射 |
| **`rcopy`** | 通用 fallback | 一般遞迴複製（Recursive copy） | 最後保底手段 |

### 3.2 任務結束後的自動回寫與銷毀

1. 子 agent 在隔離區塊內完成修改。
2. 系統自動比對 baseline，產出 unified patch 或提交到臨時分支（`mergeMode === "branch"`）。
3. 主 session 驗收並套用 patch / cherry-pick。
4. **自動觸發 `cleanupIsolation`**：卸載掛載點或刪除 CoW 克隆目錄，子 session 標記為 `parked` 且不可 revive，**達成完全自動、零磁碟殘留**。

---

## 4. Worktree 的生命週期與清理機制（三個維度）

若因為 PR 審查或手動多分支開發而建立了持續性的 worktree，清理時機與機制可依以下三種維度管理：

```text
[Worktree 清理的三層防線]
┌────────────────────────────────────────────────────────────────────────┐
│ 1. 即時自動銷毀 (Subagent Isolation)                                    │
│    - 時機：任務結束 (Success / Fail / Abort)                              │
│    - 機制：cleanupIsolation 自動解除掛載與刪除目錄 (零殘留)                │
├────────────────────────────────────────────────────────────────────────┤
│ 2. 全域集中批次清理 (PR Review Worktrees)                                │
│    - 時機：完成一批 PR 審查、定期維護時                                    │
│    - 機制：omp wt clear [--dry-run | --all]                              │
├────────────────────────────────────────────────────────────────────────┤
│ 3. 專案級內容防誤刪保護 (Feature 分支 / 本地開發)                         │
│    - 時機：PR Squash-merge 落地後                                        │
│    - 機制：/clean-wt 依據三重正面證據鏈 (E1/E2/E3) fail-closed 安全刪除     │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.1 維度一：即時自動銷毀（Subagent 任務）

- **觸發時機**：Subagent 完成任務 yield、超時中斷、或使用者手動 cancel 任務。
- **清理動作**：系統在 finalizer 中無條件執行 `cleanupIsolation`，不依賴手動介入。

### 4.2 維度二：全域集中批次清理（omp 內建 PR 工具）

- **觸發時機**：當進行跨分支 PR 檢閱累積數個 worktree，或需要釋放磁碟空間時。
- **操作指令**：

  ```bash
  # 1. 檢視現有 agent-managed worktree
  $ omp wt

  # 2. 安全預覽（Dry-run：印出會被刪除的目錄，不實際動手）
  $ omp wt clear --dry-run

  # 3. 執行清理（清理已非 live 狀態的 PR checkout）
  $ omp wt clear

  # 4. 強制清空所有 entry
  $ omp wt clear --all
  ```

### 4.3 維度三：專案級內容防誤刪證據鏈（`/clean-wt`）

針對本機 feature 開發分支，`yibi-stack` 實作了專屬的 `/clean-wt` 指令（`clean_wt.sh`），採用 **Fail-Closed（預設拒絕）** 哲學，防止誤刪未合併的勞動成果。

#### 三重正面證據鏈（任一成立才歸 SAFE）

1. **E1 — Tip 已是 `origin/main` 的祖先**（`git merge-base --is-ancestor`）：
   - 歷史直接包含（適用於 fast-forward 或標準 merge commit）。
2. **E2 — 把分支併回 main 為 No-op**（`git merge-tree --write-tree`）：
   - 內容等價證明。即使是 Squash-merge 產生了全新 commit SHA，若合進 main 不產生任何新檔案差異，即證明內容已完整進 main。
3. **E3 — PR 的 merge commit 仍在 `origin/main` 歷史中**（`gh` + `git merge-base`）：
   - 解決 E2 在 squash-merge 後 main 又被修改導致 merge-tree conflict 的死角。
   - 要求 4 條件全滿：PR 狀態為 MERGED、基準分支匹配、本地 tip SHA 匹配、PR `mergeCommit` 現仍是 main 祖先。

#### 絕對安全防護（BLOCKED & KEEP）

- **BLOCKED**：只要 worktree 內存在未提交（uncommitted）或 untracked 檔案（如臨時筆記、草稿），**一律阻擋刪除**。
- **KEEP**：使用者當前所在的分支、或尚有 open PR 的分支，**永遠不刪**。

---

## 5. 結論與工程實務建議

1. **避免在專案根目錄建立巢狀 Worktree（如 `.claude/worktrees`）**：
   除非有極其特殊的本地需求，否則強烈建議遵循外部集中原則。巢狀目錄對外部 CLI 工具鏈（agy/codex/linters）的干擾極大，是得不償失的架構債。
2. **採用集中管理目錄（`~/.omp/wt/`）**：
   保持主 repo 潔淨。所有臨時分支由主控工具集中管理，空間回收時只需在全域單點清點（`omp wt`），維護心智負擔最低。
3. **清理節奏標準化**：
   - **子任務**：交付系統自動清理（`isolated: true`）。
   - **完成 PR 時**：於 PR squash-merge 落地後，回到主 repo 執行 `/clean-wt --apply` 清理本地分支。
   - **定期維護**：每週或每月執行一次 `omp wt clear` 清理殘留的 PR 審查工作區。

# Claude Code 週報 — 2026-05-25

> 自動排程任務 `claude-release-note` 產出。整理本週 Claude Code release note 的開發者重點，
> 並對照 yibi-stack（原 `ainization-skill`）內的 skill 產出更新建議清單。

## 涵蓋範圍與資料來源

- **版本範圍**：`2.1.133` – `2.1.150`（即上一份週報之後的所有版本，約 2026-05-13 ~ 05-23）。
- **資料來源**：官方 CHANGELOG（`raw.githubusercontent.com/anthropics/claude-code/HEAD/CHANGELOG.md`）為主，
  日期以 Releasebot 首次收錄時間（May 23 最後更新）近似校正。
- **重要提醒**：Claude Code CHANGELOG **不含日期**，僅有版本號。下表日期為近似值，可能有 1–2 天誤差；
  版本內容本身則以官方 CHANGELOG 原文為準。

| 版本 | 近似日期 | 一句話重點 |
| ---- | -------- | ---------- |
| 2.1.150 | 05-23 | 內部基礎建設改善（無使用者可見變更） |
| 2.1.149 | 05-23 | `/usage` 分類用量、`/diff` 鍵盤捲動、GFM checkbox |
| 2.1.148 | 05-23 | 修 Bash tool exit 127 回歸 |
| 2.1.147 | 05-22 | **`/simplify` 改名 `/code-review` 且行為大改**、pinned 背景 session |
| 2.1.145 | 05-22 | `claude agents --json`、修 bare 環境變數賦值的權限 bypass |
| 2.1.144 | 05-20 | `/resume` 支援背景 session、`/model` 改為「只改本 session」 |
| 2.1.143 | 05-19 | plugin 相依強制、`worktree.bgIsolation`、stop hook block 上限 |
| 2.1.142 | ~05-16 | `claude agents` 新 flags、fast mode 預設 Opus 4.7 |
| 2.1.141 | ~05-15 | hook `terminalSequence`、Rewind「Summarize up to here」 |
| 2.1.140 | ~05-15 | Agent `subagent_type` 模糊比對、修 symlink settings 熱重載 |
| 2.1.139 | ~05-14 | **agent view（`claude agents`）、`/goal`、hook `args` exec form** |
| 2.1.136 | ~05-14 | `autoMode.hard_deny`、大量穩定性修正 |
| 2.1.133 | ~05-13 | **hooks/Bash 取得 `$CLAUDE_EFFORT`、`worktree.baseRef`** |

---

## Part 1 — 開發者需要注意的新技巧、功能與改進

### A. 工作流與 Agent（本週最大變化）

- **Agent view（`claude agents`）— Research Preview（2.1.139）**：一個畫面列出所有 Claude Code
  session（running / blocked-on-you / done）。後續版本快速補強：背景 session 會與互動式 session
  並列、標記 `bg`（2.1.144）；`claude agents --json` 可把活躍 session 輸出成 JSON 給 script
  消費（tmux-resurrect、status bar、session picker）（2.1.145）；pinned 背景 session（`Ctrl+T`）
  閒置時不會被砍、更新時就地重啟（2.1.147）。
- **`/goal` 指令（2.1.139）**：設定一個「完成條件」，Claude 會跨多個 turn 持續工作直到條件成立；
  互動式、`-p`、Remote Control 皆可用，並以 overlay 顯示即時 elapsed / turns / tokens。
- **背景 session 全面強化（2.1.142–2.1.147）**：`claude agents` 新增 `--add-dir`、`--settings`、
  `--mcp-config`、`--plugin-dir`、`--permission-mode`、`--model`、`--effort`、
  `--dangerously-skip-permissions` 等 flag；`/resume` 可挑背景 session；背景 subagent 完成
  通知會顯示耗時。
- **⚠️ `/simplify` 改名為 `/code-review`，且行為徹底改變（2.1.147）**：原本「清理並修改程式碼」
  （cleanup-and-fix）的行為**已被移除**。新的 `/code-review` 只**回報**正確性 bug，可指定
  effort（如 `/code-review high`），加 `--comment` 可把 finding 貼成 GitHub PR inline comment。
  → **凡是把 `/simplify` 當作「會自動重整程式碼」的流程都會壞掉**（見 Part 2 P0-1）。
- **`/ultrareview`（雲端多 agent 平行 code review）**：`claude ultrareview [target]` 可在 CI／
  script 非互動執行，`--json` 輸出原始結果（2.1.120）。
- **`/model` 行為調整（2.1.144）**：`/model` 現在只改「當前 session」；在 picker 按 `d` 才設成
  新 session 的預設。
- **fast mode 預設模型升級（2.1.142）**：fast mode 預設改用 Opus 4.7；要釘回 4.6 設
  `CLAUDE_CODE_OPUS_4_6_FAST_MODE_OVERRIDE=1`。

### B. Hooks（對自動化／本 repo 影響最大）

- **`$CLAUDE_EFFORT` 進入 hook 與 Bash tool（2.1.133）**：hooks 現在透過 JSON input 的
  `effort.level` 欄位與 `$CLAUDE_EFFORT` 環境變數收到當前 effort；**Bash tool 執行的指令也能直接
  讀 `$CLAUDE_EFFORT`**。這讓 hook／script 能依 effort 調整行為（深掃 vs. 速掃）。
- **hook `args: string[]` exec form（2.1.139）**：command 型 hook 可用 `args` 陣列**直接 spawn
  程式、不經 shell**，所以路徑 placeholder 永遠不必加引號，徹底避開引號／subshell 地雷。
- **`CLAUDE_PROJECT_DIR` 普及（2.1.139）**：MCP stdio server 現在也會收到 `CLAUDE_PROJECT_DIR`；
  plugin／hook 的 command 字串可直接引用 `${CLAUDE_PROJECT_DIR}`。
- **PostToolUse `continueOnBlock`（2.1.139）**：PostToolUse hook 設 `continueOnBlock: true`
  時，hook 的拒絕理由會回饋給 Claude 並讓 turn 繼續，而非中斷。
- **hook `terminalSequence` 輸出欄位（2.1.141）**：hook 可在沒有 controlling terminal 的情況下
  發送桌面通知、視窗標題、bell。
- **Stop / SubagentStop hook input 加欄位（2.1.145）**：新增 `background_tasks` 與
  `session_crons`，讓收尾 hook 知道還有哪些背景工作／排程。
- **Stop hook 無限 block 防護（2.1.143）**：stop hook 連續 block 8 次後 turn 會自動結束並警告；
  上限可用 `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` 調整。
- **其他修正**：`ConfigChange` hook 對 symlink settings 的誤觸發已修（2.1.140）；hook 若寫入
  terminal 會破壞互動 prompt，現在 hook 一律在無 terminal 存取下執行（2.1.139）；prompt 型
  `SessionStart`/`Setup`/`SubagentStart` hook 現在會給明確錯誤要求改用 command 型（2.1.142）。

### C. Skills 與 Plugins

- **`effort:` frontmatter 確認可用（2.1.149）**：修正了「狀態列顯示使用者 baseline `/effort`
  而非 skill/agent `effort:` frontmatter 套用後的值」——間接確認 skill/command frontmatter 的
  `effort:` 是正式且生效的機制。
- **argument-hint 修正（2.1.149）**：修正「Tab 補完一個 frontmatter `name:` 與目錄名不同的
  skill 後，argument-hint 與漸進式參數提示不出現」。
- **`Skill(name *)` wildcard 修正（2.1.139）**：`Skill()` 權限規則的 wildcard 形式現在如
  `Bash(ls *)` 一樣做 prefix match；subagent 也能透過 Skill tool 發現 project／user／plugin skill。
- **`context: fork` 無限迴圈修正（2.1.145）**：修掉「用 `context: fork` 的 skill 反覆自我呼叫」。
- **plugin 可見度／管理**：根層放 `SKILL.md` 而無 `skills/` 子目錄的 plugin 也會被視為一個 skill
  （2.1.142）；`claude plugin details <name>` 顯示元件清單與 per-session token 估算（2.1.139）；
  `/plugin` marketplace browse 會顯示「投影 context cost」（per-turn / per-invocation token 估計）
  （2.1.143）；plugin 相依強制：`claude plugin disable` 會擋住「被其他啟用 plugin 依賴」的目標，
  `enable` 會連帶啟用相依（2.1.143）。
- **skill listing**：skill description 列出上限早已從 250 提到 1,536 字元；超過會在啟動時警告。

### D. 權限、安全與 Bash

- **bare 環境變數賦值的權限 bypass 修正（2.1.145）**：修掉「Bash 指令中對非 allowlist 環境變數的
  純賦值會被自動核准」的漏洞。
- **權限解析器對 `cd`/`pushd`/`popd` 的修正（2.1.149）**：修掉「解析器信任 `PWD`/`OLDPWD`/
  `DIRSTACK` 的過期變數追蹤值」；同時修掉 PowerShell 內建 `cd` 函式（`cd..`、`cd\` 等）改變工作
  目錄而不被偵測的 bypass。
- **`autoMode.hard_deny`（2.1.136）**：auto mode 新增「無條件封鎖」分類規則，不受使用者意圖或
  allow 例外影響。
- **deny rule 穿透 exec wrapper**：deny rule 已可看穿 `env`/`sudo`/`watch`/`ionice`/`setsid`
  等 wrapper（2.1.113，本 repo CLAUDE.md 已記錄）。

### E. 新增設定參數 / 環境變數速查（2.1.133–2.1.150）

| 名稱 | 類型 | 版本 | 用途 |
| ---- | ---- | ---- | ---- |
| `worktree.baseRef` | settings | 2.1.133 | `fresh`（從 `origin/<default>`）\| `head`（從本地 HEAD，保留未推送 commit） |
| `worktree.bgIsolation` | settings | 2.1.143 | 設 `"none"` 讓背景 session 直接編輯工作副本，不強制 `EnterWorktree` |
| `sandbox.bwrapPath` / `sandbox.socatPath` | settings | 2.1.133 | Linux/WSL 指定 bubblewrap / socat 自訂路徑 |
| `autoMode.hard_deny` | settings | 2.1.136 | auto mode 無條件封鎖規則 |
| `parentSettingsBehavior` | settings(admin) | 2.1.133 | `first-wins` \| `merge`，控制 SDK `managedSettings` 是否併入 policy merge |
| `$CLAUDE_EFFORT` | env（hook/Bash） | 2.1.133 | hook 與 Bash tool 子程序可讀的當前 effort |
| `effort.level` | hook JSON input | 2.1.133 | hook input 內的 effort 欄位 |
| `CLAUDE_CODE_SESSION_ID` | env（Bash） | 2.1.132 | Bash tool 子程序環境，與 hook 收到的 `session_id` 一致 |
| `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` | env | 2.1.143 | stop hook 連續 block 上限（預設 8） |
| `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN` | env | 2.1.132 | 退出全螢幕 alt-screen renderer |
| `CLAUDE_CODE_PLUGIN_PREFER_HTTPS` | env | 2.1.141 | 以 HTTPS（非 SSH）clone GitHub plugin 來源 |
| `CLAUDE_CODE_OPUS_4_6_FAST_MODE_OVERRIDE` | env | 2.1.142 | 把 fast mode 釘回 Opus 4.6 |
| `CLAUDE_CODE_POWERSHELL_RESPECT_EXECUTION_POLICY` | env | 2.1.143 | 讓 PowerShell tool 不要加 `-ExecutionPolicy Bypass` |
| `hook args: string[]` | hook 設定 | 2.1.139 | exec form，直接 spawn 不經 shell |
| `hook continueOnBlock` | hook 設定 | 2.1.139 | PostToolUse：把拒絕理由回饋並繼續 turn |
| `hook terminalSequence` | hook 輸出 | 2.1.141 | hook 發送桌面通知 / 視窗標題 / bell |

---

## Part 2 — yibi-stack（ainization-skill）skill 更新與修改建議清單

> 對照本週 release note 的新設定參數與技巧，逐一比對 `skills/` 與 `plugins/*/skills/`，
> 依優先級排序。**P0 = 已壞需修**、**P1 = 高價值建議**、**P2 = 值得做**。
> 所有建議皆需照 `/pr-review-cycle` 流程落地，不直接改 main。

### P0 — 已壞，需立即修正

#### P0-1　`/simplify` 改名 `/code-review` 且行為改變（2.1.147）

- **受影響檔案**：
  - `plugins/pr-flow/skills/pr-review-cycle/SKILL.md` — Step 2「Simplify」
  - `plugins/pr-flow/skills/pr-review-cycle-mob/SKILL.md` — Step 2「Simplify」
  - `plugins/pr-flow/skills/pr-review-cycle-codex/SKILL.md`（已標 DEPRECATED，仍引用）
- **問題**：兩個 skill 的 Step 2 都執行 `/simplify`，並假設它會**修改程式碼**
  （原文：「先 simplify 讓程式碼進入最終形態」「若 `/simplify` 無任何改動，略過 commit」、
  commit message `refactor(...): simplify per /simplify review`）。自 2.1.147 起：
  1. `/simplify` 指令**不存在**了（改名 `/code-review`）。
  2. 即使改叫 `/code-review`，「清理並修改程式碼」的行為**已被官方移除**——它現在只**回報** bug。
- **建議修法**：重新設計 Step 2。兩條路擇一：
  - **(A) 把 Step 2 改為「`/code-review` 缺陷回報」**：執行 `/code-review high`（或依 effort），
    把回報的 bug 當成 review finding 進入既有的 fix 迴圈；移除「simplify 會自動改碼」的假設與
    那段獨立 commit 邏輯。commit message 改為 `fix(...): address /code-review findings`。
  - **(B) 若仍要「程式碼最終形態」這一步**：改用 mob/Claude reviewer 明確下「重構建議」指令，
    或把該步驟併入既有 parallel review。
  - 連帶更新 frontmatter `description` 內出現的 `simplify` 字樣，並更新 `pr-retrospective`／
    `skills/README.md`／`plugins/pr-flow/README.md` 中對 simplify 步驟的描述。
- **附帶價值**：`/code-review --comment` 可把 finding 直接貼成 GitHub PR inline comment，
  可考慮納入 `pr-review-cycle` 作為「reviewer 留言」的選項。

### P1 — 高價值建議

#### P1-2　settings.json hooks：`$(git rev-parse …)` → `${CLAUDE_PROJECT_DIR}`

- **受影響檔案**：`.claude/settings.json`（6 個 hook command 全部）。
- **現況**：所有 hook command 用 `"$(git rev-parse --show-toplevel)"/.claude/hooks/xxx.sh`。
  這個 `$()` 命令替換包在雙引號內，正是本 repo `rule 13/14` 自己列為反模式的 subshell 結構；
  且在非 git 環境會失效。
- **建議修法**：
  - **最小改動（低風險）**：把 `"$(git rev-parse --show-toplevel)"` 換成 `${CLAUDE_PROJECT_DIR}`
    （Claude Code 內建 placeholder，2.1.139 確認 plugin/hook command 可引用）。
  - **進階（對齊本 repo bash hygiene 哲學）**：評估改用 2.1.139 的 hook **`args: string[]`
    exec form**，直接 spawn script 不經 shell，路徑 placeholder 完全免引號。注意：exec form
    不能用 `|| exit 2`，需讓 `protect-push.sh` 等 script 自己 `exit 2`（目前是靠 command
    字串尾的 `|| exit 2` 轉換）。
- **理由**：這項修正讓 `.claude/settings.json` 與本 repo 的 `13-bash-anti-patterns.md`／
  `16-allowlist-hygiene.md` 自洽——目前是「規則禁止 `$()`，但自己的 settings.json 在用」。

#### P1-3　`bash-hygiene-audit` 與 `rule 16`：納入內建 `/less-permission-prompts`

- **受影響檔案**：`tasks/bash_hygiene_audit/`＋`skills/bash-hygiene-audit/SKILL.md`、
  `.claude/rules/16-allowlist-hygiene.md`、`plugins/bash-hygiene/skills/bash-anti-patterns/SKILL.md`。
- **背景**：Claude Code 內建 `/less-permission-prompts` skill（2.1.111）會掃描 transcript 裡常見的
  唯讀 Bash／MCP 呼叫，**自動產生一份排序過的 allowlist 建議**寫入 `.claude/settings.json`。
  （備註：本 repo `.runtime/logs/` 已出現 `fewer-permission-prompts-weekly_*.log`，疑似已有
  相關排程在跑——值得確認兩者是否重疊。）
- **建議**：
  - `bash-hygiene-audit` SKILL.md 增一段：說明它與內建 `/less-permission-prompts` 的分工
    （前者管 hook 攔截 audit log，後者管 allowlist 自動建議）。
  - **`rule 16` 補一節警告**：`/less-permission-prompts` 自動產生的 allowlist 建議**必須先用
    rule 16 的紅旗準則複查**——它可能產生中間 wildcard 或變數賦值 prefix 的 pattern，不可
    無腦「Yes, and don't ask again」。
- **理由**：本 repo 對 allowlist 衛生有完整規則，而官方剛好出了一個會「自動寫 allowlist」的工具，
  兩者必須對接，否則自動建議會繞過本 repo 的安全準則。

#### P1-4　`harness-eval` / `harness-eval-focus`：rubric 補上本週新能力

- **受影響檔案**：`skills/harness-eval/SKILL.md`、`skills/harness-eval-focus/SKILL.md`
  （harness plugin 為 README-only 容器，skill 實體在 `skills/` 下）。
- **背景**：harness-eval 以 8 維度評 Claude Code harness 就緒度（CLAUDE.md / hooks / settings /
  skills / testing / git / rules / security）。本週新增多項 harness 能力應納入評分基準：
  - hooks 維度：`args` exec form、`continueOnBlock`、`terminalSequence`、`type: "mcp_tool"`
    hook、PreCompact 可用 `exit 2`／`{"decision":"block"}` 擋壓縮、PostToolUse `duration_ms`。
  - settings 維度：`worktree.baseRef`、`worktree.bgIsolation`、`autoMode.hard_deny`、
    `skillOverrides`、`disableSkillShellExecution`。
  - skills 維度：`effort:` frontmatter、description ≤ 1,536 字元上限。
- **建議**：更新 D2（hooks）、D3（settings）、D4（skills）的 rubric 條目與評分權重，
  讓 harness-eval 能偵測「該用而未用」的新能力。

#### P1-5　hooks 善用 `$CLAUDE_EFFORT`（2.1.133）

- **受影響檔案**：`.claude/hooks/post-edit-mypy.sh`、`bash-ap1-inline-check.sh`、
  `bash-ap2-check.py`、`pre-compact-handover.sh`。
- **背景**：2.1.133 起 hook 與 Bash tool 子程序皆可讀 `$CLAUDE_EFFORT`／`effort.level`。
- **建議**：評估讓重型 hook 依 effort 分流，例如 `post-edit-mypy.sh` 在 `low` effort 時跳過或
  縮小檢查範圍、`high` 時做完整檢查。同時更新 CLAUDE.md 既有 gotcha「`${CLAUDE_EFFORT}` 在
  SKILL.md 不展開……用 `echo "${CLAUDE_EFFORT:-normal}"` eval」——現在 `$CLAUDE_EFFORT`
  是 Bash tool 真實環境變數，這個 eval 寫法更穩、可正式寫入文件。

### P2 — 值得做

#### P2-6　為深掃型 skill 釘 `effort:` frontmatter

- **檔案**：`plugins/sdd/skills/spectra-amplifier/SKILL.md`（及其他有 effort 表格者）。
- **現況**：`spectra-amplifier`、`pr-review-cycle-mob`、`pr-review-cycle-codex`、`codex` 在
  **body 有 effort 表格，但 frontmatter 沒有 `effort:` 欄位**。`rule 11` 已寫明
  「spectra-amplifier 可設 `effort: high`」，但尚未落地。
- **建議**：依 `rule 11` 的決策表，為「規格深度展開／深度 review」類 skill 在 frontmatter 釘
  `effort:`，避免使用者在 low session 誤觸發長批次。2.1.149 已確認 `effort:` frontmatter
  生效且狀態列正確顯示。

#### P2-7　`session-memory` / handover：對齊官方 `/recap` 與 Rewind「Summarize up to here」

- **檔案**：`plugins/growth/skills/session-memory/SKILL.md`、`.claude/hooks/pre-compact-handover.sh`。
- **背景**：官方已內建 session recap（2.1.108，`/recap`）與 Rewind 選單的「Summarize up to
  here」壓縮（2.1.141）；compaction prompt 也已要求模型保留使用者敏感指令（2.1.139）。
- **建議**：session-memory SKILL.md 增一段說明它與內建 `/recap` 的分工（前者是跨 session／跨
  機器的持久 handover，後者是單 session 內的回顧），避免使用者混淆或重工。`pre-compact-handover.sh`
  目前用 `exit 2` 攔截壓縮（符合 2.1.105 文件）；可選擇性改用 `{"decision":"block"}` 回傳形式，
  語意更明確（非必要，現行 `exit 2` 仍正確）。

#### P2-8　`scheduler`：對齊背景 session 與 `/goal`

- **檔案**：`skills/scheduler/SKILL.md`、`tasks/scheduler/`。
- **背景**：本週背景 session／`claude agents`／`/goal` 大幅強化；`--resume`／`--continue` 會
  復活未過期的排程任務（2.1.110）；Stop/SubagentStop hook input 新增 `session_crons`
  （2.1.145）；`CronList` 輸出缺漏修正（2.1.136）。
- **建議**：scheduler SKILL.md 的 FAQ／常見問題增列：與官方 `/goal`（完成條件驅動）和背景
  session（`claude --bg`）的定位差異——本 repo scheduler 是「定時 cron」，`/goal` 是「條件
  達成才停」，兩者互補。若 scheduler 與 Claude Code 內建 cron 有交集，需確認不互踩。

#### P2-9　`skills/_template/SKILL.md.tpl`：effort 區塊措辭與官方支援註記

- **檔案**：`skills/_template/SKILL.md.tpl`。
- **建議**：在 effort 表格附近註明「`${CLAUDE_EFFORT}` 在 skill 內容中由 Claude Code 官方支援
  （2.1.120 起）」，並可在範本 frontmatter 加上 `effort:`（選填）的註解，引導新 skill 作者
  依 `rule 11` 決定是否釘 effort。

#### P2-10　`bump-version`：提及 `claude plugin tag`

- **檔案**：`plugins/pr-flow/skills/bump-version/SKILL.md`、CLAUDE.md「Plugin 發布」段。
- **背景**：2.1.118 新增 `claude plugin tag`——為 plugin 建立帶版本驗證的 release git tag。
- **建議**：本 repo 用 `make release` 做 plugin lockstep 升版；可在 bump-version SKILL.md
  補一句說明 `claude plugin tag` 是官方單一 plugin 的 tag 工具，與本 repo 的 lockstep 流程
  關係（本 repo 仍以 `make release` 為主，`claude plugin tag` 不取代它）。

#### P2-11　確認 `worktree.baseRef: "fresh"` 符合 PR-in-worktree 工作流

- **檔案**：`.claude/settings.json`（已設 `worktree.baseRef: "fresh"`）。
- **背景**：`worktree.baseRef` 為 2.1.133 新增，本 repo 已設 `fresh`。但 2.1.133 原文提醒：
  `fresh` 會讓 `EnterWorktree` 的 base 改回 `origin/<default>`（自 2.1.128 一直是本地 `HEAD`），
  **新 worktree 不會帶入未推送的本地 commit**；要保留未推送 commit 需設 `"head"`。
- **建議**：本 repo PR review 大量使用 worktree（`.claude/worktrees/`）。請確認：若工作流中
  「先在 main/branch 上本地 commit、再進 worktree」會發生，`fresh` 會讓那些 commit 不在新
  worktree 內。若這是刻意選擇（強制乾淨 base）則無需改；若曾因此遺失 commit，改 `"head"`。
  屬「複查設定」項，非 bug。

### 各 skill 影響速查

| Skill / 檔案 | 本週是否受影響 | 對應建議 |
| ------------ | -------------- | -------- |
| `pr-review-cycle` | **是（已壞）** | P0-1 |
| `pr-review-cycle-mob` | **是（已壞）** | P0-1 |
| `pr-review-cycle-codex` | 是（已 DEPRECATED） | P0-1（順帶） |
| `.claude/settings.json` hooks | 是 | P1-2 |
| `bash-hygiene-audit` | 是 | P1-3 |
| `bash-anti-patterns` / `rule 16` | 是 | P1-3 |
| `harness-eval` / `harness-eval-focus` | 是 | P1-4 |
| `.claude/hooks/*`（mypy/ap1/ap2/precompact） | 是 | P1-5、P2-7 |
| `spectra-amplifier` | 是 | P2-6 |
| `session-memory` | 是 | P2-7 |
| `scheduler` | 是 | P2-8 |
| `_template/SKILL.md.tpl` | 是 | P2-9 |
| `bump-version` | 是 | P2-10 |
| `codex` | 輕微 | P2-6（effort frontmatter） |
| `claude-md-prune` / `pr-retrospective` | 輕微 | 連帶更新 simplify 描述（P0-1） |
| `tdd-kentbeck` / `flutter-tdd` / `qa-test-design` | 否 | — |
| `local-port-manager` / `new-task-module` | 否 | — |
| `detect-ai-slop` / `verify-gemini-models` / `learn` | 否 | — |

---

## 建議落地順序

1. **先修 P0-1**（pr-review-cycle 系列的 `/simplify` 失效）——這是會讓使用者流程當場壞掉的項目。
2. **再做 P1-2**（settings.json hook 路徑）——一次性、低風險、且讓 repo 與自家 rule 自洽。
3. P1-3 / P1-4 / P1-5 可合併為一個「對齊 2.1.133–2.1.150 新能力」的 PR。
4. P2 各項視 backlog 容量分批，建議透過 `/pr-retrospective` 的 Lesson Classifier 路由。

> 所有變更請走 `/pr-review-cycle`（小型）或 `/pr-review-cycle-mob`（需群審）流程，不直接推 main。

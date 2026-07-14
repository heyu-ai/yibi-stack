---
id: "0004"
title: "Plugin-Primary 交付 — 把 tasks/* 做成可安裝的 CLI distribution"
status: accepted
date: 2026-07-14
deciders: [howie]
related:
  issue: 222
  prs:
    - number: 215
      note: "pr-retrospective bootstrap self-locate（已 merge）— 其解析邏輯在本 ADR 的終局會整段刪除"
    - number: 221
      note: "pr-control-log 套用同樣修法（open）— 同上"
    - number: 230
      note: "本 ADR + Gap B 修復"
---

## Context

本專案**主要以 Claude plugin 形式交付**；`make install`（git clone + symlink 到
`~/.claude/skills`）只是本機開發方便，不是出貨路徑。

Issue #222 記錄了擋住此前提的兩個結構性缺口。下列事實在做出決定前**皆已對 repo 重新實測**，
非推論。

### Gap A — `tasks/*` 從不出貨

`.claude-plugin/marketplace.json` 每個 entry 只有 `source` 路徑（如 `"./plugins/pr-flow"`，
marketplace.json:16-70），**沒有任何 file list / include / exclude 機制**，所以 plugin 的
payload 就是它自己那個目錄。`tasks/` 位於 repo root、與 `plugins/` 平行——在所有 plugin 目錄
之外，因此永遠搆不到。實測：`~/.claude/plugins/cache/yibi-stack/pr-flow/1.6.0/` 只有
`commands/ skills/ package.json README.md`，**無 `tasks/`**。

有 6 個 skill、橫跨 3 個 plugin 依賴它，且目前全標 `scope: global`：

| plugin | skill | 依賴模組 |
|---|---|---|
| pr-flow | pr-cycle-fast | `tasks.pr_orchestrator` |
| pr-flow | pr-control-log | `tasks.mycelium` |
| pr-flow | pr-retrospective | `tasks.mycelium` |
| growth | mycelium | `tasks.mycelium` |
| growth | learn | `tasks.mycelium` |
| util | local-port-manager | `tasks.local_port_manager` |

它們靠讀 `~/.agents/config.json` 的 `skill_repo` 找 checkout，再
`uv run --directory "$SKILL_REPO" python -m tasks.X`。**該 key 只有 clone + `make install`
後才存在**——與 plugin-only 安裝直接矛盾。這個失敗模式甚至已經寫在 repo 自己的文件裡：
`plugins/pr-flow/skills/pr-control-log/SKILL.md:232`。

此外 `.claude/hooks/pre-compact-handover.sh` 與 `post-compact-handover-back.sh` 是
**in-process import** `tasks.mycelium`。它們同樣位於所有 plugin 目錄之外，是**第二個未出貨
且假設有 checkout 的表面**——Gap A 不只限於 skill。

### Gap B — plugin 出貨的資源，skill bash 定位不到

`CLAUDE_PLUGIN_ROOT` 在 **hook** context 有值，但在 **skill bash 沒有**（agent 是透過 Bash
tool 執行 skill 的 bash，該環境不帶 plugin context）。這是未文件化的平台限制，實測結果已記於
`plugins/pr-flow/skills/pr-retrospective/SKILL.md:48`。

因此 `plugins/sdd/skills/spectra-amplifier/SKILL.md:86,757` 是**永遠執行不到的死碼**：

```bash
SDD_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/sdd}"
```

變數恆為 unset，所以永遠 fallback 到 `plugins/sdd`——那是 repo 相對路徑，而同一段 SKILL.md
自己就承認它在 host 專案中不存在。

**Gap B 與 Gap A 是不同的 bug，修法也不同。** 資源其實**有出貨**：
`~/.claude/plugins/cache/yibi-stack/sdd/1.6.0/scripts/check_spec_coverage.py` 存在。沒有東西
缺席，**壞的只有定位邏輯**。故 Gap B 不需任何架構裁決即可修——已於 PR #230 完成。

### 推翻 issue 原本框架的三項發現

為本 ADR 所做的研究推翻了 issue 內文的三個假設：

1. **三個模組全都可抽，不只 mycelium。** `local_port_manager`（443 LOC、零跨模組 import、
   已 home-anchored 於 `~/.agents/ports.json`、無 subprocess）**比 mycelium 更乾淨**。
   `pr_orchestrator`（1,470 LOC）原本預期會因「它是操作 repo 的工具」而被判出局，但實測其
   目標 repo 早已是完整貫穿的 `--repo-root` 參數，且有測試（PROR-ST-030/032/033/034/036/040）
   釘住此行為——這正是 standalone CLI 的形狀。它唯一的真實阻礙是 3 處
   `from .._paths import RUNTIME_DIR` 把狀態錨定在 checkout。
2. **真實依賴集合只有 `click` + `pydantic`。** 15 個宣告的 runtime 依賴中 **9 個零 import**
   （playwright、python-dotenv、pikepdf、cryptography、tabula-py、pillow、pytesseract、
   markdownify——全是 ainization-skill fork 的遺留）。整個 `tasks/` 的聯集就是兩個純 Python
   wheel，外加 `tiktoken`，而後者在 `tasks/mycelium/lessons_service.py:678` 已經是
   optional-with-fallback。其餘宣告的依賴（anthropic、sqlalchemy、psycopg2-binary、requests、
   pdfplumber）**只被 `scripts/` 使用**——那是一套硬編碼到 `localhost:5435/ledgerone` 的個人
   帳務工具，本來就不可能出貨給其他使用者。
3. **repo 是 PUBLIC**，所以 `uv tool install git+https://github.com/heyu-ai/yibi-stack` 不需要
   PyPI 帳號、不需要 publish pipeline、不需要 release artifact workflow。issue 把「無 build /
   publish 流程」列為阻礙，但真正需要的只是 `[build-system]` + `[project.scripts]` 兩段設定。

第四點消滅了 issue 列出的最大成本：**抽取不需要改 package 名稱**。保留 `tasks.` import path、
只加 console script entry point，26 個測試模組與 12 處硬編碼的 `python -m tasks.mycelium`
字串**完全不用動**。

## Decision

**把 `tasks/*` 做成單一可安裝的 Python distribution，暴露多個 console script，經
`uv tool install git+https://github.com/heyu-ai/yibi-stack` 安裝。**

Skill 直接呼叫裸指令（`mycelium ...`、`portman ...`、`pr-orchestrator ...`）。整個
`SKILL_REPO` 解析層——`~/.agents/config.json` 查找、兩支 `bootstrap.sh`、`uv run --directory`
——全部刪除。

**粒度：單一 distribution、多 entry point**（非三個獨立 package）。一份 build 設定、一道安裝
指令。因為依賴集合只是兩個純 Python wheel，使用者為了 mycelium 安裝時，連帶拿到 `portman` 與
`pr-orchestrator` 的成本近乎為零。

package import path 維持 `tasks.*`。只改動 `[build-system]`、`[project.scripts]`、依賴清單，
以及 wheel 的打包範圍。

### 被否決的替代方案

**把 `tasks/` 搬進各 plugin 目錄出貨。** Claude Code **沒有 plugin 相依機制**，所以 `pr-flow`
與 `growth` 都需要 mycelium 時，只能二選一：重複一份、或再拆一個「shared」plugin，但其他三個
plugin 無法宣告對它的相依。兩份 mycelium 各自漂移，正是
`.claude/rules/18-single-source-of-truth.md` 明文禁止的 dual-source 失敗模式——而且
`.claude/hooks/` 還會從 checkout import 第三份。

**維持現狀 + 誠實標示**（6 個 skill 改 `scope: project`，README 拿掉 plugin-only 承諾）。
成本最低、零風險，也確實修好了「不誠實」這件事——但它等於對價值最高的那批 skill 放棄
plugin-primary 前提。**保留為退路**：若 Phase 1 顯示打包成本超出預期，回到此方案。

**只修 Gap B、延後 Gap A。** 不是被否決，是**被吸收**。Gap B 不需架構裁決，已作為 Phase 0
先行出貨（PR #230）。這是排序，不是替代方案。

## Consequences

### 正面

- Plugin-only 安裝對這 6 個 skill 成為**事實**；`scope: global` 從願望變成真的。
- 6 份 SKILL.md 中約 60 行脆弱的 `SKILL_REPO` 解析消失，連同兩支 `bootstrap.sh` 及其失敗模式。
- `~/.agents/config.json` 的 `skill_repo` / `skill_repos` key 失去所有 reader，其「多 repo 共寫
  單一 key」的漂移風險（issue #197、#199）不再構成問題。
- 砍掉 9 個死依賴，讓每位貢獻者的 `uv sync` 擺脫 Java runtime 需求（tabula-py）與瀏覽器下載
  （playwright）。
- 版本落差變成**可見且可修**（`uv tool upgrade`），而非靜默解析到某個過期 checkout 的內容。

### 負面 / 風險

- **版本落差取代路徑落差。** 使用者安裝的 CLI 可能落後 plugin 的 SKILL.md。每個 skill 都必須
  加上能力／版本檢查並 fail-loud。這比今天「靜默解析到錯 repo」是**更好的失敗**，但它是新增
  的失敗模式。**這是最重要的一條**：若少了它，Phase 2/3 等於把大聲的路徑失敗換成安靜的行為
  不一致——嚴格來說比現狀更糟。
- **`uv tool install` 成為那 6 個 skill 的前置需求。** 與「mycelium 是使用者另外安裝的 tool」
  前提一致，但必須在**失敗當下**告知，而不是只寫在 README。
- **`tasks/_paths.RUNTIME_DIR` 必須廢除** repo 錨定形式
  （`PROJECT_ROOT = Path(__file__).resolve().parents[1]`）。在 pip 安裝下它會解析進
  site-packages。`local_port_manager` 已示範目標寫法（`Path.home() / ".agents"`），而
  `pr_orchestrator` 的 archive 路徑也已半採用。
- **`scripts/` 必須排除在 wheel 之外**，否則帳務工具的重量級依賴會繞回來。
- **開發用的 `.claude/hooks/` in-process import 維持綁 checkout。** 可接受：那些 hook 是本 repo
  的開發工具，不是出貨產物。

### 驗證閘門

Phase 1 是白老鼠。若在乾淨機器上 `uv tool install git+https://github.com/heyu-ai/yibi-stack`
無法產生可用的 `portman`，則**在 mycelium 或 pr_orchestrator 動工前重新檢視本 ADR**。

實作計畫見 [docs/plugin-primary-plan.md](../plugin-primary-plan.md)。

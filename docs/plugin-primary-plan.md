# Plan: Plugin-Primary 交付（issue #222）

決策與理由見 [ADR-0004](adr/0004-plugin-primary-packaging.md)。本文件只談執行。

**形狀**：5 個 PR，每個都可獨立出貨、獨立 revert。Phase 0 不依賴任何架構裁決，最先落地。
Phase 1 是刻意挑選的低風險白老鼠，用來在任何有價值的東西搬動之前，先證明打包骨架可行。

| Phase | PR | 範圍 | 風險 | 前置 |
|---|---|---|---|---|
| 0 | Gap B + 清理 | locator 修復、marketplace 漂移 | 低 | — |
| 1 | 打包骨架（白老鼠） | pyproject、砍死依賴、`portman` | 低 | — |
| 2 | mycelium → `mycelium` | 6 個 skill 中的 4 個 | 中 | 1 |
| 3 | pr_orchestrator → `pr-orchestrator` | 第 6 個 skill | 中 | 1 |
| 4 | 收尾 + 誠實雙軌 | 刪 SKILL_REPO 層、README、scope | 低 | 2, 3 |

Phase 2 與 Phase 3 彼此獨立，Phase 1 落地後可並行。

---

## Phase 0 — Gap B 與清理（PR #230，已完成）

不依賴 Gap A 裁決。修的是目前真實壞掉的行為。

### 0.1 spectra-amplifier 資源定位

`plugins/sdd/skills/spectra-amplifier/SKILL.md:86,757` 是死碼：
`SDD_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/sdd}"`。該變數在 skill bash 恆為 unset，所以永遠
fallback 到 host 專案不存在的 repo 相對路徑——**靜默錯誤，從不報錯**。

改成有序候選鏈，且**每個候選都用「能力檢查」把關**——驗真正需要的那個檔案讀不讀得到，而非
只驗目錄存在。這正是 `bootstrap.sh:33` 已經記下的教訓（rule 11/18、PR #215）：只驗目錄存在
會讓錯的 root 靜默通過。

| # | 候選 | 何時命中 |
|---|------|---------|
| 1 | `$CLAUDE_PLUGIN_ROOT` | 目前恆不命中；保留在首位，Claude Code 未來若補上即自動生效 |
| 2 | `installed_plugins.json` 的 `installPath` | **plugin 安裝的正常路徑**，記錄「目前生效版本」 |
| 3 | `plugins/sdd` | 在 yibi-stack 源碼 repo 內開發時 |

三者皆未命中即 fail-loud 並印出安裝指令。

> **不要**用 `cache/yibi-stack/sdd/*/` glob 取版本：cache 內多版本並存（實測 1.2.5 / 1.3.1 /
> 1.6.0），而 glob 是字典序，`1.10.0` 會排在 `1.9.0` 之前——選到錯版本且不報錯。
> `installed_plugins.json` 才是「哪個版本生效」的單一真相來源。依
> `.claude/rules/13-bash-anti-patterns.md`，單行 `python3 -c` 是 SKILL.md 讀 JSON 的既定寫法
> （已有 4 份 SKILL.md 先例），而 `ls | head -1` 是明文禁止的。

**先有雞先有蛋的限制**：這段 locator **不能**抽成獨立腳本——因為「定位那支腳本」正是要解的
問題本身。它必須留在 inline bash。整份 SKILL.md 只定義一次 resolver 區塊，兩個呼叫點
（:86 與 :757）共用。

### 0.2 spectra-amplifier 斷掉的 symlink — 本機殘留，**repo 不需改動**

`~/.claude/skills/spectra-amplifier` → `yibi-stack/skills/spectra-amplifier`，目標已不存在
（symlink 日期 5/26，早於該 skill 遷入 `plugins/sdd/skills/`）。

**看似顯然的修法是錯的。** 補上
`skills/spectra-amplifier -> ../plugins/sdd/skills/spectra-amplifier` 從 sibling 類比看很合理，
但實測說了別的話：

| sdd skill | scope | `skills/` 有 symlink？ |
|---|---|---|
| event-storming、problem-frames、qa-test-design | `global` | 有 |
| **figma-design-sync、spectra-amplifier** | `project` | **沒有** |

這個缺席是**一致且刻意的**：兩個 `scope: project` 的 sdd skill 本來就不建 symlink。而且 sdd
plugin 已經出貨 spectra-amplifier——實測
`~/.claude/plugins/cache/yibi-stack/sdd/1.6.0/skills/spectra-amplifier` 存在。補 symlink 會讓
該 skill **被重複註冊**（plugin 一次、`~/.claude/skills` 一次）。

所以 repo 沒有東西要修。那個斷掉的 symlink 是遷移前留下的**本機殘留**，而且**任何 repo 改動
都無法移除使用者機器上的 symlink**。本機處理掉即可：

```bash
rm ~/.claude/skills/spectra-amplifier   # 斷掉的 symlink；該 skill 現由 sdd plugin 提供
```

記錄於此，是因為 issue 把它列在「附帶發現」，而直覺修法反而有害。

### 0.3 marketplace / README 漂移

`plugins/writing/` 有 `plugin.json` 與 `package.json`（v1.8.0），但**不在
`.claude-plugin/marketplace.json`**（只列 7 個）。README 卻在 6 處
（`:94, :104, :153, :238, :248, :297`）叫人執行 `claude plugin install writing@yibi-stack`
——一道無法解析的指令。下游實測佐證：`writing` 不在 plugin cache，也不在
`installed_plugins.json`。

已把 `writing` 加進 `marketplace.json`。（替代方案是從 README 拿掉，但該 plugin 是完整的——
`plugin.json` v1.8.0 加一個可用的 `detect-ai-slop` skill——且目前只能經 full-install 取得，
卻被廣告在 plugin-only 軌上。）

順手修正：`3rd-tools` 的 marketplace 描述宣稱有「AI slop detection」，但 `detect-ai-slop` 住在
`writing`，且全 repo 別無他處。`3rd-tools` 實際出貨的是 agy / codex / verify-gemini-models，
描述已改為與現實相符——與 `writing` 缺席同屬 doc-vs-code 漂移，靠查證而非照抄才發現。

### 0.4 ~~移除被 commit 的 `__pycache__`~~ — **不是真問題**

查證後撤銷。`plugins/sdd/scripts/__pycache__/` 與
`plugins/3rd-tools/skills/verify-gemini-models/.venv/` **兩者皆未被追蹤且已 gitignore**
（`.gitignore:2`、`:140`）；`git ls-files plugins/sdd/scripts/` 只回傳 4 個真正的原始檔。
它們是本機建置雜訊，不是被 commit 的產物。

刻意以刪除線保留此條目：本計畫的早期草稿曾斷言它們被 commit，那是錯的。Phase 1 的
`[tool.hatch.build.targets.wheel].packages = ["tasks"]` 仍是控制 wheel 範圍的正確做法，與此無關。

### Phase 0 驗證（已完成）

- 模擬 host 專案：在**非** yibi-stack checkout 的目錄執行 resolver，確認解析到 cache 並找到
  `check_spec_coverage.py`。
- **Mutation 測試能力閘門**：依 `.claude/rules/09-test-conventions.md`，沒有測試驅動的 guard
  等於零覆蓋——要靠「弄壞它」而非「讀它」來驗證。實測 5/5 通過：
  - 無任何候選命中 → 回傳空值（呼叫端 fail-loud）
  - 目錄存在但缺少腳本 → **被拒絕**（能力閘門，非存在閘門）
  - 舊碼在同一 cwd 解析到不可讀的 `plugins/sdd`——重現了原始 bug
- `pre-commit --all-files` 全綠（含 `lint-skill-bash`），1393 個測試通過。

---

## Phase 1 — 打包骨架（白老鼠：`local_port_manager`）

`local_port_manager` 是刻意挑的白老鼠：443 LOC、零跨模組 import、只用 `click` + `pydantic`、
無 subprocess，且**已經 home-anchored** 在 `~/.agents/ports.json`、全程路徑可注入。它能走完
完整打包路徑，卻承擔最小風險。

### 1.1 pyproject

```toml
[project]
name = "yibi-stack"        # 原為 "ainization-skill" — fork 遺留的過期身分
dependencies = ["click>=8.1", "pydantic>=2.0"]

[project.optional-dependencies]
tokens = ["tiktoken>=0.7"]   # mycelium token 預算；缺少時自動退化為 len/4

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project.scripts]
portman = "tasks.local_port_manager.cli:cli"

[tool.hatch.build.targets.wheel]
packages = ["tasks"]         # 排除 scripts/、plugins/、本機 .venv
```

**砍掉 8 個零 import 的依賴**：playwright、python-dotenv、pikepdf、cryptography、tabula-py、
pillow、pytesseract、markdownify。這一刀同時移除 Java runtime 需求（tabula-py）與瀏覽器下載
（playwright）。

> 零 import 的依賴其實有 9 個，但第 9 個 `psycopg2-binary` **不可砍**：sqlalchemy 靠連線字串
> 的 scheme 載入它作為 postgres driver，故它移入 `ledger` extra 而非移除。「零 import」不等於
> 「沒人用」——這正是本 PR 需要逐一查證而非依賴 grep 計數的原因。

**`scripts/` 是其餘依賴的唯一持有者。** anthropic、sqlalchemy、psycopg2-binary、requests、
pdfplumber **只**被 `scripts/` 使用——那是硬編碼到 `localhost:5435/ledgerone` 的個人帳務工具。
它不該進公開 wheel（`packages = ["tasks"]` 已處理），但本機使用仍需要依賴，故移入
`[project.optional-dependencies].ledger`，並**明確補上 `pandas`**：
`scripts/compare_billing.py:10` 直接 import 它，目前卻只靠 tabula-py 的 transitive 滿足——
砍掉 tabula-py 而不宣告 pandas 會靜默弄壞那些腳本。

`tiktoken` 在 `tasks/mycelium/lessons_service.py:678` 被使用，卻**未在任何地方宣告**、也不在
`uv.lock` 裡。它已有 `ImportError` fallback，故應放 extra 而非 core。

改名後重跑 `uv lock`（目前 lock 的 root package 仍寫 `ainization-skill`）。

### 1.2 接上白老鼠

- 加 `portman` entry point。
- 改寫 `plugins/util/skills/local-port-manager/SKILL.md:19-22`：刪掉 config.json resolver 與
  `cd "$SKILL_REPO"`，9 個呼叫點全改為 `portman ...`。
- 加 fail-loud preflight：`command -v portman`，缺少時印出 `uv tool install` 指令並停止。
- 把 `service.py:31-46` 的 `BOOTSTRAP_ENTRIES`（硬編碼個人專案 `yibi-mvp`、`voice-lab`、
  `coachly`、`coaching365`）移出即將發佈的工具——改進設定或直接拿掉。

### Phase 1 驗證（ADR-0004 的決策閘門）

1. `uv build` 產出 wheel；檢查內含 `tasks/`，且**不含** `scripts/` 或任何 `.venv`。
2. 在乾淨路徑執行 `uv tool install git+https://github.com/heyu-ai/yibi-stack` → 在**沒有任何
   clone** 的情況下 `portman --help` 可用。
3. `make ci` 全綠（完整 `--all-files`，依 CLAUDE.md——不是 `--files`）。
4. 既有 307 LOC 的 LPM 測試原封不動通過（import path 未改）。

**若第 2 步在乾淨機器上失敗，停止，並在 Phase 2 之前重新檢視 ADR-0004。**

---

## Phase 2 — mycelium

涵蓋 6 個 skill 中的 4 個：`growth/mycelium`、`growth/learn`、`pr-flow/pr-control-log`、
`pr-flow/pr-retrospective`。

- 加 `mycelium = "tasks.mycelium.cli:cli"`。**import path 不變**——26 個測試模組與 12 處硬編碼
  的 `python -m tasks.mycelium` 字串（`insight_hook.py:202`、`recap_hook.py:212`、
  `cli.py:86-88,125,160`、`account.py:52`、`distill_service.py:10`、`insight_hook.py:32`、
  `recap_hook.py:28`）全部繼續運作。那些字串仍應改寫為 `mycelium ...` 以求正確（它們會被寫進
  生成的 hook 指令），但屬美觀問題，不擋路。
- 改寫 4 份 SKILL.md，直接呼叫 `mycelium ...`。
- **刪除兩支 `bootstrap.sh`** 及其 SKILL.md 呼叫點。這正是 PR #215 / #221 所預期的終局——它們
  在舊架構下是正確的局部最優。
- 加版本能力閘門（見下方「跨階段議題」）。
- `semantic_index.py:68` 在 runtime 載入 `sqlite_vec` SQLite extension，並有 FTS5 fallback
  （`:64-65`）。確認該 fallback 在 pip 安裝的直譯器下仍成立——它不是 Python import，wheel 不會
  帶它。
- `.claude/hooks/{pre-compact-handover,post-compact-handover-back}.sh` 在 `cd "$REPO_ROOT"` 後
  in-process import `tasks.mycelium`。它們是開發專用、位於所有 plugin 目錄之外、從不出貨——
  維持綁 checkout。**在 PR 說明中明講**，以免被誤認為疏漏。

> **Phase 1 留下的兩顆地雷（PR #249 mob review 發現，三家一致認為非 Phase 1 blocker）**
>
> Phase 1 的 `packages = ["tasks"]` 已經**出貨**了這些模組，只是還沒有 console script 暴露
> 它們——所以問題今天不可達。**Phase 2 加上第二個 entry point 的那一刻就會爆**：
>
> 1. **`tasks/_paths.py:5-6` 的 `PROJECT_ROOT = Path(__file__).resolve().parents[1]`**
>    在 wheel 安裝下解析進 `site-packages/`，於是 `RUNTIME_DIR` 變成 `site-packages/.runtime`
>    ——寫入落在安裝樹，升級時**靜默消失**。共 10 個模組 import 它。
>    `portman` 之所以安全，是因為其 import chain 零 `_paths` 引用、`REGISTRY_PATH` 直接用
>    `Path.home()`。Phase 3 的「狀態重新錨定」涵蓋此項——**但 Phase 2 的 mycelium 先落地，
>    必須先確認 mycelium 是否碰 `_paths`**（其資料層已 home-anchored 於
>    `~/.agents/handover/`，但要實測而非假設）。
> 2. **`tasks/_worktree_guard.py:49` 呼叫 `PROJECT_ROOT/scripts/assert_not_worktree.sh`**，
>    而該腳本**不在 wheel 內**（`packages = ["tasks"]` 不含 `scripts/`）。影響
>    `scheduler` / `mycelium` / `nightly_agent` / `pr_orchestrator` 的 install 路徑。
>    失敗是 **fail-closed 且大聲**（「找不到 worktree 守門腳本」），不是靜默——這是它不算
>    blocker 的原因。但 `pip install yibi-stack && python -m tasks.scheduler install` 今天
>    已經是死的。Phase 2 暴露 mycelium 時，需 `force-include` 該腳本或改寫 guard 的定位方式。

---

## Phase 3 — pr_orchestrator

涵蓋第 6 個 skill：`pr-flow/pr-cycle-fast`（15 個呼叫點）。

- **狀態重新錨定。** `tasks/_paths.py` 的 `PROJECT_ROOT = Path(__file__).resolve().parents[1]`
  使 `RUNTIME_DIR` 在 pip 安裝下解析進 site-packages。三個消費端：`config.py:12,17-19`、
  `log.py:9,11`、`dispatcher.py:7,10`。改為 `~/.agents/pr_orchestrator/`——`local_port_manager`
  已在用的模式，且 `config.py:18` 的
  `_ARCHIVE_BASE = Path.home()/".claude"/"pr_orchestrator"` 也已半採用。
- 加 `pr-orchestrator = "tasks.pr_orchestrator.cli:cli"`。
- **`dispatcher.py`（77 LOC）** 產生的 Claude Code subagent spawn manifest 內含
  `uv run python -m tasks.pr_orchestrator transition ...`（`:39, :68-71`），改寫為 console script。
- 改寫 `plugins/pr-flow/skills/pr-cycle-fast/SKILL.md` 的全部 15 個 `uv run --directory` 呼叫點。
- **保住 `--repo-root` 貫穿。** `cli.py:177,197` 與測試
  PROR-ST-030/032/033/034/036/040 釘住每個 git/gh 呼叫的 `cwd == repo_root`。在 console script
  下 cwd 是使用者的 shell——這是**與當初那些測試所針對的 `uv run --directory` 不同**的錯誤 cwd
  風險。用 mutation 反證：弄壞 `cwd=` 的傳遞，確認有測試會 fail。

---

## Phase 4 — 收尾與誠實雙軌

- 刪除 `~/.agents/config.json` 的 `skill_repo` / `skill_repos` **reader**：
  `tasks/mycelium/models.py:179-225`（schema + `resolve_skill_repo()`）、
  `commands/scripts/handover-read.sh:7`、
  `plugins/3rd-tools/skills/verify-gemini-models/scripts/check_models.py:21`。
  再退役 writer `scripts/register_skill_repo.py`（`Makefile:115`）。
  **順序必須 reader 先於 writer**，避免任何中間 commit 留下「reader 拿不到 key」的狀態。
- 那 6 個 skill 的 `scope: global` 此時**成為事實**。對照 README 的定義查核，不要用假設的。
- README：讓雙軌誠實。Plugin-only 現在對 6 個 skill 都成立，**前提是 `uv tool install`**——
  該前提要寫在使用當下，不能只寫在 README。
- 評估用 `yibi-plugin-root <plugin>` console script 取代 Phase 0 的 inline locator。CLI 反正已
  安裝，所以現在可行；但它會讓 sdd（今天是純 markdown + 一支 `uv run python` 腳本）綁上 Python
  安裝。**評估，不要假設。**

---

## 跨階段議題

### 版本落差是新的失敗模式（修訂於 PR #249）

路徑落差變成版本落差：安裝的 CLI 可能落後 plugin 的 SKILL.md。每個遷移過的 skill 都需要
fail-loud 的 preflight：

```text
command -v mycelium  → 不存在？印出 `uv tool install git+https://github.com/heyu-ai/yibi-stack`，停止
mycelium --version   → 非零退出（安裝損毀）？印出 `uv tool install --force ...`，停止
```

> **本節原本要求的是 semver 比對，該做法已於 PR #249 撤銷。** 原文寫
> 「`mycelium --version` → 低於此 SKILL.md 所需最低版本？印出 `uv tool upgrade`，停止」。
> 三家 reviewer 獨立收斂確認它做不到：`uv tool install git+` 裝的是 **HEAD**，而 metadata
> 版本字串是**上次 release** 的值——兩次 release 之間的每個 commit 都回報同一個版本，
> 比較不到任何東西。提出此要求的 Codex 在 R2 主動撤回。詳見
> [ADR-0004](adr/0004-plugin-primary-packaging.md) 的「負面／風險」修訂註記。

**修正後的分工**：

| 目的 | 機制 | 狀態 |
|------|------|------|
| 指令不存在 | `command -v <cli>` → fail-loud + 安裝指令 | Phase 1 已實作（portman） |
| 安裝損毀 | `<cli> --version` 非零退出 → fail-loud + 重裝指令 | Phase 1 已實作（portman） |
| 診斷／bug report | `<cli> --version` 的輸出（人看的） | Phase 1 已實作（portman） |
| **真正的相容性閘門** | capability/protocol revision 或具體行為 probe | **尚未設計** |

最後一列刻意留白：**在有 skill 真正需要版本專屬功能之前不要設計它**。預先加一道恆真的
版本比較（`MIN_VERSION="1.9.0"` 在 portman 只存在於 >= 1.9.0 的今天等同 `command -v`），
是一道 PASS 不帶資訊的閘門——rule 09 明文禁止的形狀，且會讓讀者誤以為漂移已被守住。

Phase 2 若讓 mycelium 的 SKILL.md 依賴新 subcommand，屆時才設計 probe（例如比對
`mycelium capabilities` 的輸出集合，而非版本號）。

### 單一真相來源的暴露面

> **註（PR #249）**：本節原本引用 `.claude/rules/18-single-source-of-truth.md`，但**該檔案
> 不存在**（`.claude/rules/` 只有 01-11、13、15、16）——dangling reference，正是 rule 11
> 「cross-doc cite 必須驗證兩端」要防的形狀。改引用實際存在的 rule 11。

依 `.claude/rules/11-skill-authoring.md`（「Spec and SKILL.md behavioral guards must stay in
sync」「Cross-doc Cite Must Paste the Original Quote」），每個階段都製造出會靜默漂移的
doc/code 契約：

- **SKILL.md 宣稱的 preflight 能力 vs. 它實際做的檢查** → PR #249 實例：SKILL.md 只印
  `--version`，測試檔的 docstring 卻宣稱 preflight 會「判斷」版本。**閘門本身就是 regression
  test，要斷言它**——不要只在文件裡宣稱它存在。
- README 的安裝指令 vs. `marketplace.json` → 已經漂移過一次（`writing`）。Phase 0 之後，加一道
  檢查：README 廣告的每個 plugin 都必須存在於 `marketplace.json`。
- **plugin README 的 Prerequisites vs. skill 的實際依賴** → PR #249 實例：`plugins/util/README.md`
  在 skill 已不需 checkout 之後，仍叫使用者 `git clone && make install`。**遷移一個 skill 時，
  必須同時檢查它所屬 plugin 的 README**。
- `pyproject` version vs. `uv.lock` → 同 commit 一起 bump（既有 CLAUDE.md 規則）。
- **`[project.scripts]` 宣告 vs. entry point 真的解析得到** → 由 `scripts/tests/test_packaging.py`
  斷言（泛用寫法，Phase 2/3 新增 console script 時自動涵蓋）。
- **wheel 打包範圍 vs. ADR 宣稱** → 由 `scripts/packaging_smoke_test.sh` 斷言，接在 CI
  （不可用 `@pytest.mark.slow`：`addopts = "-m 'not slow'"` 連 CI 都 deselect，等於永不執行）。

### 搜尋衛生

`.claude/worktrees/` 內有本次觸及檔案的約 4 份陳舊副本。全 repo grep 會有約 5 倍雜訊，可能製造
「呼叫點很多」的假象。**所有 grep 都限定在主 checkout。**

### 不在此範圍（值得另開 issue）

- **`scripts/` 是另一個應用程式。** 個人帳務工具（HSBC 匯入、帳單比對、Claude 分類），硬編碼到
  單一機器的 Postgres，因 fork 而意外同居本 repo。它持有剩下 5 個依賴。它大概應該整個離開本
  repo；Phase 1 只是把它隔離在 extra 之後。
- **`harness-eval` 不可經 plugin 安裝**（README:96），維持 checkout-only。

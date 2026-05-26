# Skills 索引

此目錄為 agent 執行介面層。每個 skill 對應一個日常工作任務或方法論，包含完整的 SKILL.md runbook。

## Scope 說明

每個 skill 的 SKILL.md frontmatter 有 `scope` 欄位：

| scope | 意義 | 安裝方式 |
|-------|------|---------|
| `global` | 跨專案可用（方法論 / 通用工具）| `make install`（預設） |
| `project` | 本 repo 限定（需要 `tasks/` Python 實作）| `make install-project` |

`make install-all` = `build-tools` + `install` + `install-project` + `install-handover-hooks` + `install-scheduler` + `patch-pr-review-agents`（新環境一次到位）。

## Plugin Pack 安裝

Global skill 已依主題分組為 plugin pack，可透過 Claude Code marketplace 選擇性安裝：

```bash
claude plugin marketplace add howie/yibi-stack  # 一次性註冊

claude plugin install growth@yibi-stack          # mycelium + learn + handover/newjob
claude plugin install pr-flow@yibi-stack         # PR 全流程 6 skills + 5 commands
claude plugin install sdd@yibi-stack             # spectra-amplifier + qa-test-design + /sdd:setup
claude plugin install bash-hygiene@yibi-stack    # bash-anti-patterns + protect-push
claude plugin install 3rd-tools@yibi-stack       # codex + agy + verify-gemini-models + detect-ai-slop
claude plugin install tdd@yibi-stack             # tdd-kentbeck + flutter-tdd + ci-triage
claude plugin install util@yibi-stack            # local-port-manager + debug command
```

---

## 可用 Skills

### 全域 Skill（`scope: global`，任何專案可用）

#### 可執行 / 工具型

| Skill | 類型 | 住址 | 描述 | SKILL.md |
|-------|------|------|------|----------|
| `mycelium` | tool | [plugins/growth/](../plugins/growth/README.md) | 跨對話工作記憶中樞：跨 Agent / 跨帳號 / 跨機器的統一 handover 交班與 insight 收集系統，所有產出收斂至 `~/.agents/` | [mycelium/SKILL.md](mycelium/SKILL.md) |
| `learn` | tool | [plugins/growth/](../plugins/growth/README.md) | 統一教訓管理 — 整合 handover 交班教訓、insight 洞察，支援瀏覽、搜尋、修剪、匯出 | [learn/SKILL.md](learn/SKILL.md) |
| `local-port-manager` | exec | [plugins/util/](../plugins/util/README.md) | 機器層 port 分配登錄，管理多專案服務 port 避免衝突。支援 suggest（查不寫）+ reserve（確認後登記）兩步驟工作流 | [local-port-manager/SKILL.md](local-port-manager/SKILL.md) |
| `protect-push` | tool | [plugins/bash-hygiene/](../plugins/bash-hygiene/README.md) | 安裝 Claude Code PreToolUse hook，防止 worktree branch 的 git push 直推 origin/main | [protect-push/SKILL.md](protect-push/SKILL.md) |
| `bash-hygiene-audit` | exec | [tasks/bash_hygiene_audit/](../tasks/bash_hygiene_audit/) | bash-hygiene hook audit log 管理：啟用/停用記錄、查看近期 hook 攔截事件、統計違規比例與熱點 pattern | [bash-hygiene-audit/SKILL.md](bash-hygiene-audit/SKILL.md) |
| `harness-eval` | exec | [plugins/harness/](../plugins/harness/README.md) | Claude Code harness 就緒度評量：8 維度 0-100 分，PASS/WARN/FAIL 清單，優先改善 TODO。涵蓋 CLAUDE.md / hooks / settings / skills / testing / git / rules / security | [harness-eval/SKILL.md](harness-eval/SKILL.md) |
| `harness-eval-focus` | know | [plugins/harness/](../plugins/harness/README.md) | 單維度深度稽核：配合 /harness-eval 使用，發現 WARN/FAIL 後針對 D1~D8 某維度精準挖掘具體修法。含 hook lifecycle 覆蓋、permission 4 層模型、CLAUDE.md signal-to-noise 等深度 rubric | [harness-eval-focus/SKILL.md](harness-eval-focus/SKILL.md) |
| `pr-retrospective` | tool | [plugins/pr-flow/](../plugins/pr-flow/README.md) | PR 收尾五問回顧（agent 推論草稿、使用者校準），寫入 mycelium handover；依 Lesson Classifier 路由 lessons 到 `.claude/rules/` 或 CLAUDE.md，再觸發 hookify、writing-skills 等下游 skill | [pr-retrospective/SKILL.md](pr-retrospective/SKILL.md) |
| `claude-md-prune` | tool | [plugins/pr-flow/](../plugins/pr-flow/README.md) | 審查並精簡 CLAUDE.md：把累積的 gotcha 路由到對應的 `.claude/rules/` 子檔，刪除過期或重複內容，維持 CLAUDE.md 在 Anthropic 建議的 200 行軟上限內 | [claude-md-prune/SKILL.md](claude-md-prune/SKILL.md) |
| `codex` | tool | [plugins/3rd-tools/](../plugins/3rd-tools/README.md) | OpenAI Codex CLI 第二意見：review（pass/fail gate）、challenge（對抗模式）、consult（詢問 codebase）；auth 確認用兩次 bash call，不觸發 if/elif 確認框 | [codex/SKILL.md](codex/SKILL.md) |
| `agy` | tool | [plugins/3rd-tools/](../plugins/3rd-tools/README.md) | Antigravity CLI（Gemini）第二意見：review（PASS/FAIL gate）、challenge（對抗模式找 bug/security）；不啟動 mob 流程的輕量單一 Gemini reviewer | [agy/SKILL.md](agy/SKILL.md) |
| `verify-gemini-models` | exec | [plugins/3rd-tools/](../plugins/3rd-tools/README.md) | 驗證 Gemini 模型在 Google AI Studio 與 Vertex AI 上的實際可用性（LLM / TTS / Live），支援 Gemini 3.x global 端點 | [verify-gemini-models/SKILL.md](verify-gemini-models/SKILL.md) |

#### 知識型（方法論）

| Skill | 住址 | 描述 | SKILL.md |
|-------|------|------|----------|
| `bump-version` | [plugins/pr-flow/](../plugins/pr-flow/README.md) | Project-level 版本 bump（Flutter/Python/Node.js/Go）+ CHANGELOG 生成 + git tag 發布，附帶 commit-msg hook 安裝 | [bump-version/SKILL.md](bump-version/SKILL.md) |
| `spectra-amplifier` | [plugins/sdd/](../plugins/sdd/README.md) | Spec Kit 五層深度規格展開 + OpenSpec 變更管理框架融合方法論 | [spectra-amplifier/SKILL.md](spectra-amplifier/SKILL.md) |
| `qa-test-design` | [plugins/sdd/](../plugins/sdd/README.md) | 六大測試設計技術（等價類別、邊界值、決策表、狀態轉移、Pairwise、風險導向） | [qa-test-design/SKILL.md](qa-test-design/SKILL.md) |
| `pr-review-cycle` | [plugins/pr-flow/](../plugins/pr-flow/README.md) | 完整 PR 生命週期：建立 PR → /code-review 缺陷偵測 → parallel review（Claude pr-review-toolkit 4 subagent）→ fix → re-review → CI → merge → spectra archive + Jira sync。適用小型 feature / 快速合併 | [pr-review-cycle/SKILL.md](pr-review-cycle/SKILL.md) |
| `pr-review-cycle-mob` | [plugins/pr-flow/](../plugins/pr-flow/README.md) | Mob review by multiple frontier-model agents：自動偵測 codex / gemini，≥1 家可用即啟動 R1 獨立 + R2 交叉 debate + aggregate；fix → re-review 直到全員 LGTM → 人類快速複查 → CI → merge | [pr-review-cycle-mob/SKILL.md](pr-review-cycle-mob/SKILL.md) |
| `pr-review-cycle-codex` | [plugins/pr-flow/](../plugins/pr-flow/README.md) | [DEPRECATED] codex-only 強化版；想要 mob 群審用 `/pr-review-cycle-mob`，小型 PR 用 `/pr-review-cycle` | [pr-review-cycle-codex/SKILL.md](pr-review-cycle-codex/SKILL.md) |
| `bash-anti-patterns` | [plugins/bash-hygiene/](../plugins/bash-hygiene/README.md) | Claude Code agent 下 bash 指令三層防線：AP1 過度複雜單行 / AP2 bash 字串 Unicode / AP3 stateful cd；Rule 14 shell 引號衛生；Rule 15 不可逆操作邊界；含判斷標準、對策決策樹與可選裝 PreToolUse hook | [bash-anti-patterns/SKILL.md](bash-anti-patterns/SKILL.md) |
| `tdd-kentbeck` | [plugins/tdd/](../plugins/tdd/README.md) | Kent Beck TDD + Tidy First 方法論，Red→Green→Refactor 循環與 commit 紀律 | [tdd-kentbeck/SKILL.md](tdd-kentbeck/SKILL.md) |
| `flutter-tdd` | [plugins/tdd/](../plugins/tdd/README.md) | Flutter 行動應用 TDD 專家指引：unit/widget/BLoC/integration/golden 五類測試 | [flutter-tdd/SKILL.md](flutter-tdd/SKILL.md) |
| `ci-triage` | [plugins/tdd/](../plugins/tdd/README.md) | CI 失敗快速診斷漏斗（Lint → Type → Security → Tests），含 Python / JS / Go 工具範例 | [ci-triage/SKILL.md](ci-triage/SKILL.md) |
| `detect-ai-slop` | [plugins/3rd-tools/](../plugins/3rd-tools/README.md) | 系統化辨識 AI 生成文字，含模型特徵比對與去除 AI 味建議 | [detect-ai-slop/SKILL.md](detect-ai-slop/SKILL.md) |

---

### 本 Repo 限定 Skill（`scope: project`，需 `make install-project`）

#### 可執行 Skill

| Skill | 類型 | 描述 | SKILL.md | 相依工具 |
|-------|------|------|----------|---------|
| `scheduler` | exec | 管理 Skill Scheduler — 設定定期自動執行的排程、查看執行狀態、手動觸發 job | [scheduler/SKILL.md](scheduler/SKILL.md) | `uv`, MiniShell ACP Gateway |
| `new-task-module` | exec | 根據本 repo 的 module 結構規範自動建立新 task module 骨架（7 個檔案）並更新索引 | [new-task-module/SKILL.md](new-task-module/SKILL.md) | -- |

---

### 外來安裝技能（透過 `skills-lock.json` 管理，內容在 `~/.agents/skills/`）

| Skill | 描述 | 來源 |
|-------|------|------|
| `steve-jobs-perspective` | Steve Jobs 思維框架：6 個心智模型、8 條決策啟發式、完整角色扮演規則 | `alchaincyf/steve-jobs-skill` |

> 外來技能由 `skills-lock.json` 追蹤版本與 hash，透過 `.claude/skills/<name>` symlink 掛載，**不在 `skills/` 目錄下維護內容**。更新指令：`npx skills upgrade <name>`

---

## 執行方式

1. 選擇對應的 skill
2. 開啟 `SKILL.md`
3. 照步驟依序執行

## 新增 Skill

參考 [`_template/SKILL.md.tpl`](_template/SKILL.md.tpl) 取得標準格式。

知識型 skill 只需建立 `skills/<skill-name>/SKILL.md`；可執行 skill 需同時在 `tasks/<task_name>/` 建立 Python 實作。

## Skill 生命週期

```text
ideas/    → 構想筆記（純 .md）
drafts/   → 開發中（有目錄結構但尚未發佈）
skills/   → 正式發佈（透過 make install 安裝 symlink）
```

升級指令：`make promote SKILL=<name>`

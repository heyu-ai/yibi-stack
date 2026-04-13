# Skills 索引

此目錄為 agent 執行介面層。每個 skill 對應一個日常工作任務或方法論，包含完整的 SKILL.md runbook。

## 可用 Skills

### 可執行 Skill（執行指令、產生檔案或寄送資料）

| Skill | 描述 | SKILL.md | 相依工具 |
|-------|------|----------|---------|
| `gmail-scan` | 通用 Gmail 掃描（非金融類），支援多 profile 郵件搜尋與附件下載。金融帳單請用 gmail-billing | [gmail-scan/SKILL.md](gmail-scan/SKILL.md) | `gws` CLI, `uv` |
| `gmail-billing` | 從 Gmail 掃描金融帳單 PDF，自動下載、解密、分類、轉 CSV。支援 on-demand 補掃與每季定期批次匯入 | [gmail-billing/SKILL.md](gmail-billing/SKILL.md) | `gws` CLI, `uv`, Java Runtime |
| `gmail-scan-stock` | 掃描富邦／國泰／永豐金證券月對帳單，彙整庫存股票總現值 | [gmail-scan-stock/SKILL.md](gmail-scan-stock/SKILL.md) | `uv` |
| `einvoice-blank-upload` | 上傳空白未使用發票號碼到財政部電子發票整合服務平台（每兩個月） | [einvoice-blank-upload/SKILL.md](einvoice-blank-upload/SKILL.md) | `uv`, Playwright, 人工 CAPTCHA |
| `icf-global-news-digest` | 爬取 ICF 官網最新消息與活動，翻譯繁中，產出 Markdown 週報與 HTML 電子報並寄出（Agent-driven，無 Python 實作） | [icf-global-news-digest/SKILL.md](icf-global-news-digest/SKILL.md) | `gws` CLI, Chrome MCP |
| `gmail-newsletter` | 從 Gmail 擷取訂閱電子報：付費電子報輸出全文 Markdown（供匯入 Heptbase），免費電子報（中/英）由 Claude 生成每日摘要 digest | [gmail-newsletter/SKILL.md](gmail-newsletter/SKILL.md) | `gws` CLI, `uv` |
| `scheduler` | 管理 Skill Scheduler — 設定定期自動執行的排程、查看執行狀態、手動觸發 job、安裝/卸載 LaunchAgent | [scheduler/SKILL.md](scheduler/SKILL.md) | `uv`, MiniShell ACP Gateway（claude job） |

### 工具型 Skill（安裝或設定開發工具）

| Skill | 描述 | SKILL.md |
|-------|------|----------|
| `handover` | 跨對話、跨裝置、跨 Agent 的工作交班系統。使用 SQLite 保存工作狀態，避免 context rot。支援寫入、讀取、搜尋交班記錄（需 `sqlite3`） | [handover/SKILL.md](handover/SKILL.md) |
| `protect-push` | 安裝 Claude Code PreToolUse hook，防止 worktree branch 的 git push 直推 origin/main | [protect-push/SKILL.md](protect-push/SKILL.md) |

### 知識型 Skill（純 Markdown 方法論指引）

| Skill | 描述 | SKILL.md |
|-------|------|----------|
| `tdd-kentbeck` | Kent Beck TDD + Tidy First 方法論，Red→Green→Refactor 循環與 commit 紀律 | [tdd-kentbeck/SKILL.md](tdd-kentbeck/SKILL.md) |
| `qa-test-design` | 六大測試設計技術（等價類別、邊界值、決策表、狀態轉移、Pairwise、風險導向） | [qa-test-design/SKILL.md](qa-test-design/SKILL.md) |
| `detect-ai-slop` | 系統化辨識 AI 生成文字，含模型特徵比對與去除 AI 味建議 | [detect-ai-slop/SKILL.md](detect-ai-slop/SKILL.md) |
| `howie-writing-style` | 模擬 Howie 個人中文寫作風格（四段式架構、茶水間語氣） | [howie-writing-style/SKILL.md](howie-writing-style/SKILL.md) |
| `local-port-manager` | 本地 Port 衝突解決工具（開發中） | [local-port-manager/SKILL.md](local-port-manager/SKILL.md) |

### 外來安裝技能（透過 `skills-lock.json` 管理，內容在 `.agents/skills/`）

| Skill | 描述 | SKILL.md | 來源 |
|-------|------|----------|------|
| `steve-jobs-perspective` | Steve Jobs 思維框架：6 個心智模型、8 條決策啟發式、完整角色扮演規則，以 Jobs 視角分析產品與策略 | [.agents/skills/steve-jobs-perspective/SKILL.md](../.agents/skills/steve-jobs-perspective/SKILL.md) | `alchaincyf/steve-jobs-skill` |

> 外來技能由 `skills-lock.json` 追蹤版本與 hash，透過 `.claude/skills/<name>` symlink 掛載，**不在 `skills/` 目錄下維護內容**。更新指令：`npx skills upgrade <name>`

## 執行方式

1. 選擇對應的 skill
2. 開啟 `SKILL.md`
3. 照步驟依序執行

## 新增 Skill

參考 [`_template/SKILL.md`](_template/SKILL.md) 取得標準格式。

知識型 skill 只需建立 `skills/<skill-name>/SKILL.md`；可執行 skill 需同時在 `tasks/<task_name>/` 建立 Python 實作。

## Skill 生命週期

```text
ideas/    → 構想筆記（純 .md）
drafts/   → 開發中（有目錄結構但尚未發佈）
skills/   → 正式發佈（透過 make install 安裝 symlink）
```

升級指令：`make promote SKILL=<name>`

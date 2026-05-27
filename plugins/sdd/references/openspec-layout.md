# OpenSpec 目錄結構指引

OpenSpec 是 Spectra CLI 使用的變更管理目錄格式，用於追蹤功能規格從提案到封存的生命週期。

> **路徑前綴**：本模板使用 `docs/openspec/`（適合有 docs/ 組織的 repo）。
> 無 docs/ 組織的 repo 可改用 `openspec/` 作為根目錄；plugin SKILL.md 預設即如此。
> 選定一種，在 repo 內保持一致即可。

## 標準目錄結構

```text
docs/openspec/changes/<change-name>/
├── proposal.md         Step 1b/4/5 規格（User Stories / 假設約束 / 完工標準）
├── design.md           Step 3 資料模型與 API schema（按需）
├── testplan.md         Step 2 TC 表格 + Coverage Analysis
├── tasks.md            實作工作清單（phase + parallelizable marker + 追溯 US）
└── specs/
    └── <cap>/
        └── spec.md     Gherkin scenarios（#### Scenario: <slug> -- <title>）
```

`<change-name>` 通常與 feature branch 名稱相近（kebab-case）。

## Spectra CLI 生命週期指令

```bash
spectra init                                 # 初始化專案（建立 .spectra/ 配置）
spectra new artifact proposal --change <name> --stdin  # 建立 proposal artifact
spectra list                                 # 列出進行中的 change
spectra show <change-name>                   # 顯示 change 詳情
spectra analyze <change-name> [--json]       # 分析 artifact 一致性與缺口
spectra validate <change-name>               # 驗證 change 完整性
spectra status                               # 顯示 artifact DAG 狀態
spectra archive <change-name> [--yes]        # 封存已完成 change（不可逆，需確認）
```

## Delta Markers

在 `specs/*.md` 中用 marker 標記規格變更：

| Marker | 用途 |
|--------|------|
| `[ADDED]` | 新增的行為或屬性 |
| `[MODIFIED]` | 修改既有行為或屬性 |
| `[REMOVED]` | 移除的行為或屬性 |

## Spectra Amplifier Step 對應

| Step | 對應文件 | 內容 |
|------|---------|------|
| Step 0 | — | Domain Discovery 前置檢查（讀 event-storming.md 若存在）|
| Step 1 | proposal.md + specs/ | US+AC + Gherkin scenarios（#### Scenario: slug）|
| Step 2 | testplan.md | qa-test-design dispatch → TC 表格 + Coverage Analysis |
| Step 3 | design.md | 資料模型、API schema、序列圖（按需）|
| Step 4 | proposal.md | 假設（Assumptions）+ 硬性限制（Constraints）+ Out of Scope |
| Step 5 | proposal.md + tasks.md | 完工標準 + SMK 冒煙測試 + Traceability Matrix |

Tasks 是實作層（非 Step 層）：從 proposal/design 追溯建立，含 parallelizable 標記（[P]）。

## 範例

live in-repo 範例（真實 change）：`docs/openspec/changes/auto-detect/`

範本骨架（可複製開始）：此目錄下的 `*-template.md`

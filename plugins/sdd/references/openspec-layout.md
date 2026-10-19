# OpenSpec 目錄結構指引

OpenSpec 是 Spectra CLI 使用的變更管理目錄格式，用於追蹤功能規格從提案到封存的生命週期。

## 解析規格根目錄

以下 `<spec-root>` 是依**目標 repo 根目錄**的 `.spectra.yaml` 解析出的路徑佔位符，
不是固定的 `docs/openspec/`，也不是本 plugin 所在 repo 的路徑：

1. 若設定檔明確提供 `spec_dir`，依 YAML 語意讀取非空字串（支援引號、註解與 flow mapping）。
   例如 `spec_dir: "docs/specs" # 規格目錄` 會將 `<spec-root>` 解析成 `docs/specs/`。
   路徑以 repo 根目錄為相對基準，必須留在 repo 內；絕對路徑、`..` 越界及 symlink 逃出 repo 都不接受。
2. 搜尋既有證據時，依序查設定根目錄、支援的 `openspec/`、`docs/openspec/`，正規化並去重。
   只有設定檔不存在或省略 `spec_dir` 時，才直接使用兩個預設根目錄，並以第一個實際存在者為主要根目錄。
   新增與更新文件使用目前設定根目錄；不要在預設路徑另建副本。
3. 設定檔存在卻不可讀、YAML 不合法、`spec_dir` 非字串或空白字串是設定錯誤，必須明確失敗，
   不能回退預設值或回報「沒有 change」。明確設定的根目錄不存在、已有目錄不可讀或查詢工具失敗，
   同樣必須回報錯誤；預設根目錄或子目錄不存在要記錄為「不存在」，不能當成零命中或已完成的證據。
4. 跨根目錄遷移時保留舊、新路徑證據，但目前設定根目錄是 canonical；同名 change 先查目前
   根目錄的 active，再查其他 active，最後查 archive。舊路徑刪除不代表 change 消失，
   舊 archive 不得覆蓋目前 active 的狀態。

ADR 位置另依目標 repo 的文件導覽與實際目錄解析，以 `<adr-root>` 表示；若位於規格樹內，
以解析後的 `<spec-root>/...` 定位，不假定固定為 `docs/adr/`。目錄不存在或不可讀不等於沒有 ADR。

## 標準目錄結構

```text
<spec-root>/changes/<change-name>/
├── proposal.md         Step 1b/4/5 規格（User Stories / 假設約束 / 完工標準）
├── design.md           Step 3 資料模型與 API schema（按需）
├── testplan.md         Step 2 TC 表格 + Coverage Analysis
├── tasks.md            實作工作清單（phase + parallelizable marker + 追溯 US）
└── specs/
    └── <cap>/
        └── spec.md     Gherkin scenarios（#### Scenario: <slug> -- <title>）
```

`<change-name>` 通常與 feature branch 名稱相近（kebab-case）。

其他證據位置也使用同一份解析結果：

| 類型 | 位置 |
|------|------|
| Active change | `<spec-root>/changes/<change-name>/` |
| Archived change | `<spec-root>/changes/archive/<archive-name>/`（依實際封存名稱查找） |
| Stable spec | `<spec-root>/specs/<cap>/spec.md` |
| ADR | `<adr-root>/`（若在規格樹內，展開為對應的 `<spec-root>/...`） |

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

路徑示意（不宣稱任何 repo 目前存在此 change）：`<spec-root>/changes/auto-detect/`。
例如目標 repo 設定 `spec_dir: docs/specs`，此示意路徑展開為 `docs/specs/changes/auto-detect/`；
引用真實 change 前，仍須先確認目前根目錄與實際目錄存在。

範本骨架（可複製開始）：此目錄下的 `*-template.md`

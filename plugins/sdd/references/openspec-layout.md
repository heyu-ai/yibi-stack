# OpenSpec 目錄結構指引

OpenSpec 是 Spectra CLI 使用的變更管理目錄格式，用於追蹤功能規格從提案到封存的生命週期。

## 標準目錄結構

```text
docs/openspec/changes/<change-name>/
├── proposal.md         Layer 1-2-4-5 規格（User Stories / 功能規格 / 假設約束 / 可測試性）
├── design.md           Layer 3 資料模型與 API schema
├── tasks.md            實作工作清單（phase + priority + 追溯 US/FS）
└── specs/
    └── <name>-core.md  Delta spec（GIVEN/WHEN/THEN + 變更標記）
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

## Spec Kit 五層對應

| Layer | 對應文件 | 內容 |
|-------|---------|------|
| Layer 1 | proposal.md | User Stories（四元素萃取：Actors/Actions/Data/Constraints）|
| Layer 2 | proposal.md | 功能規格（FS-NNN）× 五維度展開（RFC 2119）+ QA 速檢；結果 → specs/ |
| Layer 3 | design.md | 資料模型、API schema、序列圖 |
| Layer 4 | proposal.md | 假設（Assumptions）與硬性限制（Constraints）|
| Layer 5 | proposal.md | 可測試性（Done 定義、冒煙測試、QA 技術建議）|

Tasks 是實作層（非 Spec Kit 層）：從 proposal/design 追溯建立，含優先序標記（P = Priority）。

## 範例

live in-repo 範例（真實 change）：`docs/openspec/changes/auto-detect/`

範本骨架（可複製開始）：此目錄下的 `*-template.md`

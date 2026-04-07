---
globs: skills/**
---
# SKILL.md 撰寫規範

## Frontmatter（必填）

```yaml
---
name: <skill-name>        # kebab-case，與目錄名稱一致
type: exec                # exec | tool | know
description: <一行中文說明，包含觸發關鍵字>
---
```

## Exec Skill 標準 4 步驟

```markdown
## 步驟

### Step 1 — 環境確認
cd 到 git repo 根目錄，確認工具可用：
- `uv --version` ✓
- 確認 `.env` 存在

### Step 2 — 設定確認
確認 .runtime/<config>.json 存在，向使用者確認關鍵參數：
- Profile：{{profile_name}}

### Step 3 — 執行
uv run python -m tasks.<module> <command> --profile {{profile_name}}

### Step 4 — 結果報告
回報執行結果：成功筆數、失敗項目、產出路徑。
```

## `{{value}}` Placeholder

需要向使用者確認的參數用雙大括號：`{{profile_name}}`、`{{date}}`。

## FAQ 表格

每個 exec skill 末尾附 FAQ：

```markdown
## 常見問題

| 問題 | 解法 |
|------|------|
| 找不到設定檔 | 執行 `setup` 子命令建立預設設定 |
| API 403 錯誤 | 確認 `.env` 的 token 是否過期 |
```

## Knowledge Skill（type: know）

- 只包含方法論指引，無 Python 執行步驟
- 可有多個 section（如 Core Loop、Anti-patterns）
- `description` 欄位放豐富的觸發關鍵字

## 更新索引

建立或修改 skill 後，必須更新 `skills/README.md` 的索引表格。

## 參考模板

`skills/_template/SKILL.md` 是標準格式參考。

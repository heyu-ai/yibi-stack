---
globs: skills/**
---
# SKILL.md 撰寫規範

## Frontmatter（必填）

```yaml
---
name: <skill-name>        # kebab-case，與目錄名稱一致
type: exec                # exec | tool | know
scope: global             # global | project（必填，缺漏會讓 make install 失敗）
description: <一行中文說明，包含觸發關鍵字>
---
```

### scope 選擇標準

| scope | 判斷依據 |
|-------|---------|
| `global` | 純方法論，或執行步驟在任何 git repo 都能跑（知識型 skill、通用工具） |
| `project` | 步驟需要 `uv run python -m tasks.*`、`.runtime/*.json` profile、或本 repo 特定資源 |

**重要**：`make install` 預設只裝 `scope: global` 的 skill。缺少 `scope:` 欄位會讓 install 以 `exit 1` 失敗並顯示錯誤提示，必須補上。

若 skill 的實作住在此 repo 但語意上跨專案有用（如 session-memory、local-port-manager），在 SKILL.md 的執行步驟開頭加上 skill_repo 路徑解析後可設為 `global`：

```bash
SKILL_REPO=$(python3 -c "import json,pathlib; print(json.loads((pathlib.Path.home()/'.agents'/'config.json').read_text()).get('skill_repo') or '')") || { echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; }
[ -z "$SKILL_REPO" ] && { echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; }
[ -d "$SKILL_REPO" ] || { echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; }
cd "$SKILL_REPO"
```

**注意**：不要用 `$(jq -r '.skill_repo' …)`（單引號 filter）或 `$(jq -r .skill_repo …)`（unquoted filter）。
前者觸發 AP1 D 類 hook；後者通過本地 hook 但 Claude Code 內建 parser 把 leading-dot token 視為無法解析的 string 節點，執行時跳出確認框。
`python3 -c` 單行寫法是唯一兩邊都通過的形式。

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

## README 表格分類與 frontmatter type 一致性

`skills/README.md` 有兩張獨立表格：「可執行/工具型（exec/tool）」和「知識型（know）」。
**分類依據是 SKILL.md frontmatter 的 `type` 欄位，不是功能感覺**：

| frontmatter `type` | 應放的表格 |
|--------------------|-----------|
| `exec` 或 `tool` | 可執行/工具型 |
| `know` | 知識型（方法論）|

常見錯誤：`type: know` 的 skill 因「感覺可執行」而被放入工具型表格（如 `bump-version`）。
維護 README 時，先用 `grep -m1 '^type:' skills/<name>/SKILL.md` 確認 type 再決定位置。

## 參考模板

`skills/_template/SKILL.md.tpl` 是標準格式參考。

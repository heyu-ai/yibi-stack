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
SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text()).get("skill_repo") or "")') || { echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; }
[ -z "$SKILL_REPO" ] && { echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; }
[ -d "$SKILL_REPO" ] || { echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; }
cd "$SKILL_REPO"
```

**注意**：不要用 `$(jq -r '.skill_repo' …)`（單引號 filter）或 `$(jq -r .skill_repo …)`（unquoted filter）。
前者觸發 AP1 D 類 hook；後者通過本地 hook 但 Claude Code 內建 parser 把 leading-dot token 視為無法解析的 string 節點，執行時跳出確認框。
`python3 -c` 單行寫法是唯一兩邊都通過的形式，但**必須用單引號包 `-c` 的表達式**（bash 外層單引號、Python 內部字串改用雙引號）。
`$(python3 -c "...")` 雙引號形式在 `$()` 內建立 string AST 節點，觸發 `Unhandled node type: string`。

## Frontmatter — `effort`（選填，2026-05 新增）

v2.1.133+ Claude Code 支援 skill / slash command 在 frontmatter 指定 effort，**覆寫呼叫端的 model effort**：

```yaml
---
name: <skill-name>
type: exec
scope: global
effort: medium     # 選填；low | medium | high
description: ...
---
```

### 何時用 effort frontmatter

| 情境 | 建議 |
|------|------|
| skill 為「重型批次」（大量下載、長批次掃描、規格深度展開） | 釘 `effort: medium` 或 `high`，避免使用者在 low session 誤觸發長批次 |
| skill 為「快速摘要型」 | 釘 `effort: low`，省 token |
| skill 在不同 effort 下行為差不多 | 不填，跟隨呼叫端 |

### 與 SKILL.md 內 `${CLAUDE_EFFORT}` 區塊的關係

frontmatter `effort` 是**覆寫**呼叫端 effort 的最終值；SKILL.md body 內的 `${CLAUDE_EFFORT}` 表格定義**該 effort 下的執行策略**。兩者搭配：

- 不填 frontmatter `effort` + body 有 `${CLAUDE_EFFORT}` 表格 → 跟隨呼叫端動態分流
- 填 frontmatter `effort: medium` + body 有 `${CLAUDE_EFFORT}` 表格 → 強制走 medium 那列

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

`skills/README.md` 在「全域 Skill」section 下有兩張表格：「可執行/工具型（exec/tool）」和「知識型（know）」。`scope: project` 的 exec skill 屬於第三張「本 Repo 限定」表格，不在此規則範圍。
**分類依據是 SKILL.md frontmatter 的 `type` 欄位，不是功能感覺**：

| frontmatter `type` | 應放的表格 |
|--------------------|-----------|
| `exec` 或 `tool` | 可執行/工具型 |
| `know` | 知識型（方法論）|

常見錯誤：`type: know` 的 skill 因「感覺可執行」而被放入工具型表格（如 `bump-version`）。
維護 README 時，先用下列指令確認 type 再決定位置（從 repo 根目錄執行）：

```bash
grep -m1 '^type:' skills/<name>/SKILL.md
```

## 參考模板

`skills/_template/SKILL.md.tpl` 是標準格式參考。

## 決策表與 Prose 的自洽性

決策表（mode table）必須自給自足：不能只靠表格外的 prose 描述例外行為。
agent 閱讀 SKILL.md 時按 table row 優先執行，表格外的說明段落容易被跳過。

正確做法：

- 在表格加 guard row（如「任一工具 BINARY_OK+NOT_AUTHED → 先執行停止流程，不進入 count 計算」）
- 或在對應 row 的動作欄明確標注適用條件（如「0（全部 NOT_FOUND，無 auth 失敗）」）

反模式：prose 說「偵測到 X 狀態時停止」，但 table 的 `count=0` row 說「redirect 終止」——agent 跟著 table 走，prose 的 intent 完全被覆蓋。

## FAQ 修復指令格式

FAQ 表格中的修復指令必須符合三個條件：

1. **使用實際變數名**：不用 literal `KEY` 這類 placeholder，直接寫 `CODEX_API_KEY` / `GEMINI_API_KEY` 等實際名稱
2. **shell-hygiene-safe 語法**：用 parameter expansion `"${VAR# }"` 去除前置空格，不用 `$(echo $VAR)` subshell（後者在 zsh 不 trim、且觸發 Rule 14 quoting hygiene hook）
3. **跨 shell 相容**：指令在 zsh（macOS 預設）與 bash 均能正確執行

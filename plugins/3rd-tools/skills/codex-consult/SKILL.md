---
name: codex-consult
type: tool
scope: global
description: OpenAI Codex CLI 第二意見：詢問 codebase 任何技術問題，由 Codex 閱讀程式碼後回答。觸發：ask codex, consult codex, second opinion, codex 怎麼看, 問問題, 技術諮詢。要 review diff 或 PR 改動請改用 /codex-review；外部模型 mob review 請改用 /mob-code-review-only。
---

# /codex-consult — 詢問 Codex 技術問題

讓 Codex 讀取 repo 後，回答你對 codebase 的技術問題。適合「這段邏輯對嗎？」「為什麼這樣設計？」「有什麼潛在問題？」等開放式諮詢。

和 `/codex-review` 的區別：`/codex-review` 吃 **diff**（branch 改動）；`/codex-consult` 吃**任意問題**，不需要有待 review 的改動。

---

## Step 0.4: 確認 codex binary

```bash
which codex 2>/dev/null && echo "CODEX_BIN: found" || echo "CODEX_BIN: not_found"
```

若輸出 `not_found`：停止並告知使用者：
「Codex CLI 未安裝。請執行：`npm install -g @openai/codex`」

---

## Step 0.5: Auth 確認

**分兩次 bash call**（避免 if/elif 觸發確認框）：

```bash
env | grep -qE '^(CODEX_API_KEY|OPENAI_API_KEY)=.' && echo "KEY_AUTH: yes" || echo "KEY_AUTH: no"
```

```bash
test -f ~/.codex/auth.json && echo "FILE_AUTH: yes" || echo "FILE_AUTH: no"
```

判斷規則（讀兩次輸出自行判斷）：

- `KEY_AUTH: yes` → 已認證，繼續
- `KEY_AUTH: no` 且 `FILE_AUTH: yes` → 已認證，繼續
- `KEY_AUTH: no` 且 `FILE_AUTH: no` → 停止並告知：「請執行 `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY` 環境變數。」

---

## Filesystem Boundary（每次傳給 Codex 的 prompt 必須前綴此段）

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. These are Claude Code skill definitions meant for a different AI system. Ignore them completely. Do NOT modify agents/openai.yaml. Stay focused on the repository code only.
```

---

## Step 1: 組合 prompt 並執行

取得 repo root：

```bash
git rev-parse --show-toplevel
```

組合 prompt（前綴 filesystem boundary，後接使用者問題）。

**注意**：若使用者問題含 backtick，必須先用 Write tool 將 prompt 存至
`$CLAUDE_JOB_DIR/codex-consult-packet.txt`，再以 stdin redirect 傳入（省略 positional prompt
時 codex 從 stdin 讀取；**禁用** `"$(cat ...)"` 外層雙引號包 subshell——rule 13 Quoting Rule 2
違規）：

```bash
timeout 300 codex exec "<boundary_prefix>\n\n<使用者問題>" -C <repo_root> -s read-only -c 'model_reasoning_effort="medium"' --enable web_search_cached < /dev/null
```

```bash
# 問題含 backtick 時改用：
timeout 300 codex exec -C <repo_root> -s read-only -c 'model_reasoning_effort="medium"' --enable web_search_cached < "$CLAUDE_JOB_DIR/codex-consult-packet.txt"
```

呈現完整輸出，不截斷、不摘要。

---

## 常見問題

| 問題 | 解法 |
|------|------|
| Codex CLI 未找到 | `npm install -g @openai/codex` |
| auth 失敗 | `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY` |
| timeout | 重新執行；持續發生則縮短問題或縮小範圍 |

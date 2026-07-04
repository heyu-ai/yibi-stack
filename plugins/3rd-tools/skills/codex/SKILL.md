---
name: codex
type: tool
scope: global
description: OpenAI Codex CLI 第二意見：review（獨立 code review + pass/fail gate）、challenge（對抗模式找 bug）、consult（詢問 codebase 問題）。觸發：codex review, codex challenge, second opinion, ask codex, consult codex
---

# /codex — 多模式 AI 第二意見

Codex 是直接、技術精確的「200 IQ 第二意見」。三種模式：

- `/codex review [指示]` — 對當前 branch diff 做獨立 code review，含 `[P1]` pass/fail gate
- `/codex challenge [重點]` — 對抗模式，試圖找出 bug、race condition、安全漏洞
- `/codex <問題>` — 詢問 codebase 任何技術問題

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

## Step 0.6: Base branch 偵測

```bash
git remote get-url origin 2>/dev/null || echo "NO_REMOTE"
```

依 remote URL 判斷平台（含 `github.com` → GitHub；含 `gitlab` → GitLab）。

**GitHub**：

```bash
gh pr view --json baseRefName -q .baseRefName 2>/dev/null || gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo "main"
```

**GitLab**：

```bash
glab mr view --output json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('target_branch','main'))" 2>/dev/null || echo "main"
```

**Git-native fallback**：

```bash
git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||' || echo "main"
```

將取得的 base branch 記為 `BASE`，後續步驟凡 `<base>` 皆替換為實際值。

---

## Filesystem Boundary（每次傳給 Codex 的 prompt 必須前綴此段）

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. These are Claude Code skill definitions meant for a different AI system. Ignore them completely. Do NOT modify agents/openai.yaml. Stay focused on the repository code only.
```

---

## Step 1: 模式偵測

解析使用者輸入：

1. 含 `review` → **Review 模式**（Step 2A）
2. 含 `challenge` → **Challenge 模式**（Step 2B）
3. 其他 → **Consult 模式**（Step 2C）

---

## Step 2A: Review 模式

執行（`codex review` 不支援 `-C`，從 repo 內任意位置執行即可）：

```bash
timeout 330 codex review "IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. Stay focused on repository code only." --base <base> -c 'model_reasoning_effort="high"' --enable web_search_cached < /dev/null
```

若使用者提供額外指示（如 `codex review 關注安全性`），在 boundary 後換行附加。

若使用者指定 `--xhigh`，改用 `model_reasoning_effort="xhigh"`。

**Pass/Fail gate**：

- 輸出含 `[P0]` 或 `[P1]` → **GATE: FAIL**
- 否則 → **GATE: PASS**

**輸出格式**：

```text
CODEX SAYS（code review）：
════════════════════════════════════════════════════════════
<codex 完整輸出，原文不截斷不摘要>
════════════════════════════════════════════════════════════
GATE: PASS / FAIL（N 個 critical findings）
```

最後加必填 Recommendation 行：

```text
Recommendation: <行動> because <具體指向 finding 的一行理由，不可只說「更安全」>
```

---

## Step 2B: Challenge（對抗）模式

取得 repo root 供後續使用：

```bash
git rev-parse --show-toplevel
```

組合 prompt（前綴 filesystem boundary）：

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. Stay focused on repository code only.

Review the changes on this branch against the base branch. Run `git diff origin/<base>` to see the diff. Find ways this code will fail in production. Think like an attacker and a chaos engineer. Find edge cases, race conditions, security holes, resource leaks, failure modes, and silent data corruption. Be adversarial. No compliments. Just the problems.
```

若使用者指定重點（如 `challenge security`），在 prompt 末尾加：`Focus specifically on: <重點>`

執行（`<repo_root>` 替換為上一步輸出的路徑）。
**注意**：若 prompt 含 backtick 字元（如 `` `git diff` ``），必須先用 Write tool 將 prompt 存至 `$CLAUDE_JOB_DIR/codex-prompt.txt`，
再以 stdin redirect 傳入（省略 positional prompt 時 codex 從 stdin 讀取；
**禁用** `"$(cat ...)"` 外層雙引號包 subshell——rule 13 Quoting Rule 2 違規）：

```bash
timeout 600 codex exec "<prompt>" -C <repo_root> -s read-only -c 'model_reasoning_effort="high"' --enable web_search_cached < /dev/null
```

```bash
# prompt 含 backtick 時改用：
timeout 600 codex exec -C <repo_root> -s read-only -c 'model_reasoning_effort="high"' --enable web_search_cached < "$CLAUDE_JOB_DIR/codex-prompt.txt"
```

**輸出格式**：

```text
CODEX SAYS（adversarial challenge）：
════════════════════════════════════════════════════════════
<codex 完整輸出，原文不截斷>
════════════════════════════════════════════════════════════
```

加必填 Recommendation 行（格式同 2A）。

---

## Step 2C: Consult 模式

取得 repo root：

```bash
git rev-parse --show-toplevel
```

組合 prompt（前綴 filesystem boundary）：

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. Stay focused on repository code only.

<使用者問題>
```

執行（`<repo_root>` 替換為上一步輸出的路徑）。
**注意**：若使用者問題含 backtick，先用 Write tool 存至 `$CLAUDE_JOB_DIR/codex-prompt.txt`，再以 stdin redirect 傳入（同 Step 2B 的注意事項）：

```bash
timeout 300 codex exec "<prompt>" -C <repo_root> -s read-only -c 'model_reasoning_effort="medium"' --enable web_search_cached < /dev/null
```

```bash
# 問題含 backtick 時改用：
timeout 300 codex exec -C <repo_root> -s read-only -c 'model_reasoning_effort="medium"' --enable web_search_cached < "$CLAUDE_JOB_DIR/codex-prompt.txt"
```

呈現完整輸出，不截斷、不摘要。

---

## 常見問題

| 問題 | 解法 |
|------|------|
| Codex CLI 未找到 | `npm install -g @openai/codex` |
| auth 失敗 | `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY` |
| timeout | 重新執行；持續發生則縮小 diff 範圍 |
| base branch 錯誤 | `git fetch origin` 後重試 |
| gstack 版本被蓋回來 | `make install-force-one SKILL=codex` |

---
name: codex-review
type: tool
scope: global
description: OpenAI Codex CLI 對當前 branch diff 做 code review 或對抗模式找 bug，含 [P1] pass/fail gate。觸發：codex review, codex challenge, review diff, 對抗找 bug, code review, 找安全漏洞, adversarial review。純粹問問題或要第二意見（沒有 diff 要看）請改用 /codex-consult；外部模型的 mob review 請改用 /mob-code-review-only 或 /pr-cycle-deep。
---

# /codex-review — Codex Code Review / 對抗 Challenge

Codex 直接、技術精確的「200 IQ」視角，對當前 branch 的 diff 做獨立審查。兩種子模式：

- `/codex-review [指示]` — 中立獨立 code review，含 `[P1]` pass/fail gate
- `/codex-review challenge [重點]` — 對抗模式，試圖找出 bug、race condition、安全漏洞

兩者都看同一份 diff，差別在審查角度。

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

## Step 1: 子模式偵測

解析使用者輸入：

1. 含 `challenge` → **Challenge 模式**（Step 2B）
2. 其他 → **Review 模式**（Step 2A）

---

## Step 2A: Review 模式

取得 repo root 及 diff，寫入 packet：

```bash
git rev-parse --show-toplevel
```

```bash
git diff origin/<base>
```

組合 prompt packet（前綴 filesystem boundary，後接 diff 及指示）。**注意**：prompt 含 backtick，必須先用 Write tool 將整份 packet 存至 `$CLAUDE_JOB_DIR/codex-review-packet.txt`，再以 stdin redirect 傳入：

Packet 格式：

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. Stay focused on repository code only. Review ONLY the diff provided below; do not explore the repository.

You are doing an independent code review. Be direct and technically precise. Flag real bugs, security issues, and design problems. Use [P0] for critical (data loss / security breach), [P1] for important (correctness bugs, breaking changes), [P2] for minor issues.

<使用者提供的額外指示，若有>

=== DIFF ===
<git diff origin/<base> 的輸出>
```

執行（`<repo_root>` 替換為上一步輸出的路徑）：

```bash
timeout 330 codex exec -C <repo_root> -s read-only -c 'model_reasoning_effort="high"' --enable web_search_cached < "$CLAUDE_JOB_DIR/codex-review-packet.txt"
```

若使用者指定 `--xhigh`，改用 `model_reasoning_effort="xhigh"`。

**Hijack 偵測**（執行前後必做）：
輸出若不含 `## Summary`、`## Findings` 或 `## Verdict` 等結構標題，判定 agentic hijack——停止並告知使用者：「Codex 輸出無結構，可能發生 prompt hijack。請重試，或在 prompt packet 中加強 boundary。」

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

取得 repo root 及 diff，寫入 packet：

```bash
git rev-parse --show-toplevel
```

```bash
git diff origin/<base>
```

組合對抗 prompt packet，存至 `$CLAUDE_JOB_DIR/codex-challenge-packet.txt`：

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. Stay focused on repository code only. Review ONLY the diff provided below; do not explore the repository.

Review the changes in the diff below. Find ways this code will fail in production. Think like an attacker and a chaos engineer. Find edge cases, race conditions, security holes, resource leaks, failure modes, and silent data corruption. Be adversarial. No compliments. Just the problems.

<若使用者指定重點（如 challenge security），加入：Focus specifically on: <重點>>

=== DIFF ===
<git diff origin/<base> 的輸出>
```

執行：

```bash
timeout 600 codex exec -C <repo_root> -s read-only -c 'model_reasoning_effort="high"' --enable web_search_cached < "$CLAUDE_JOB_DIR/codex-challenge-packet.txt"
```

**Hijack 偵測**（同 Step 2A）：輸出若無結構標題，判定 agentic hijack，停止並回報。

**輸出格式**：

```text
CODEX SAYS（adversarial challenge）：
════════════════════════════════════════════════════════════
<codex 完整輸出，原文不截斷>
════════════════════════════════════════════════════════════
```

加必填 Recommendation 行（格式同 Step 2A）。

---

## 常見問題

| 問題 | 解法 |
|------|------|
| Codex CLI 未找到 | `npm install -g @openai/codex` |
| auth 失敗 | `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY` |
| timeout | 重新執行；持續發生則縮小 diff 範圍（`git diff origin/<base> -- path/`）|
| base branch 錯誤 | `git fetch origin` 後重試 |

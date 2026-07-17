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
git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||'
```

**注意**：上面把 fallback 放在 `| sed` 之後（`... || echo "main"`）不可靠——未開 `pipefail`
時 pipeline 退出狀態取自 `sed`（空輸入仍成功），symbolic-ref 失敗時 `|| echo` 不會觸發，base
變成空字串。因此改用**輸出判斷**：若上面**輸出為空**（`origin/HEAD` 未設定），base = `main`。

將取得的 base branch 值記住，後續步驟凡 `<base>` 皆替換為此實際值。

---

## Filesystem Boundary

每個傳給 Codex 的 packet 都必須嵌入此 boundary。**四個敏感路徑前綴**
（`~/.claude/`、`~/.agents/`、`.claude/skills/`、`agents/`）是**強制契約**——
`plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_codex_scripts.py` 對這四路徑斷言；
Step 2A / 2B 的 packet 用**較短的變體**（四路徑逐字保留，周邊措辭可精簡），為權威來源。
完整參考版本：

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

取得 repo root：

```bash
git rev-parse --show-toplevel
```

Fetch base 後算 diff（three-dot，對 merge-base 比對，避免 base 前進時把上游 commit 顯示成反向刪除），寫入暫存檔：

```bash
git fetch origin <base>
```

```bash
git diff origin/<base>...HEAD > "$CLAUDE_JOB_DIR/codex-review-diff.patch"
```

**空 diff gate**：若 `codex-review-diff.patch` 為空（`test -s` 為假），停止並告知使用者：
「空 diff，無可審查內容——確認 branch 有相對 `<base>` 的改動，或 `git fetch origin <base>` 後重試。」
不可繼續——空 diff 會讓下方 Pass/Fail gate 假性回 PASS。

用 Write tool 把**靜態 prompt 前綴**（不含 diff）寫入 `$CLAUDE_JOB_DIR/codex-review-packet.txt`。
**diff 不經 Write tool**——要 LLM 逐字複述整份 diff 會 token 爆量、截斷或幻覺，破壞「Review ONLY
the diff provided」契約。前綴內容（`## Summary` / `## Findings` / `## Verdict` 三標題是明確契約，
下方 Hijack 偵測即以此為 anchor）：

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. Stay focused on repository code only. Review ONLY the diff provided below; do not explore the repository.

You are doing an independent code review. Be direct and technically precise. Flag real bugs, security issues, and design problems. Use [P0] for critical (data loss / security breach), [P1] for important (correctness bugs, breaking changes), [P2] for minor issues.

Structure your output EXACTLY with these three markdown headings, in order:
## Summary
<1-2 sentence overall assessment>
## Findings
<[P0]/[P1]/[P2]-tagged items; write "None" if no issues>
## Verdict
<PASS or FAIL>

<使用者提供的額外指示，若有>

=== DIFF ===
```

再用 bash redirection 把 diff 接到 packet 末端（不經 LLM）：

```bash
cat "$CLAUDE_JOB_DIR/codex-review-diff.patch" >> "$CLAUDE_JOB_DIR/codex-review-packet.txt"
```

執行（`<repo_root>` 替換為 repo root；**不用 `timeout`**——對齊 pr-cycle-deep 的 proven 形式，且
stock macOS 無 `timeout` 內建）：

```bash
codex exec -C "<repo_root>" -s read-only -c 'model_reasoning_effort="high"' --enable web_search_cached < "$CLAUDE_JOB_DIR/codex-review-packet.txt"
```

若使用者指定 `--xhigh`，改用 `model_reasoning_effort="xhigh"`。

**Exit-code gate（先於 hijack 檢查）**：上面 codex exec 若非零退出（auth 失效 / network / 中斷），
停止並告知使用者：「codex exec 失敗（非 hijack）；請確認 `codex login` 或網路後重試。」
**不可把非零退出當成 hijack 處理**——兩者修法不同。

**Hijack 偵測**（僅在 clean exit 後）：輸出若不含 `## Summary`、`## Findings`、`## Verdict` 三個標題
（上方 packet 已明確要求），判定 agentic hijack——停止並告知使用者：「Codex 輸出無結構，可能發生
prompt hijack。請重試，或在 packet 中加強 boundary。」

**Pass/Fail gate**：只看 `## Findings` 區段內**以 `[P0]` 或 `[P1]` 開頭的 finding 條目**，
不可對整份輸出做 substring 比對——否則像「No [P0] or [P1] findings」這種乾淨結果會誤觸 FAIL。

- `## Findings` 內存在以 `[P0]` 或 `[P1]` 開頭的條目 → **GATE: FAIL**
- 無（含 Findings 寫 `None` / 只有 `[P2]`）→ **GATE: PASS**

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

取得 repo root、fetch base、算 diff（three-dot），寫入暫存檔：

```bash
git rev-parse --show-toplevel
```

```bash
git fetch origin <base>
```

```bash
git diff origin/<base>...HEAD > "$CLAUDE_JOB_DIR/codex-challenge-diff.patch"
```

**空 diff gate**：若 `codex-challenge-diff.patch` 為空（`test -s` 為假），停止並告知使用者：
「空 diff，無可審查內容——確認 branch 有相對 `<base>` 的改動，或 `git fetch origin <base>` 後重試。」

用 Write tool 把**靜態對抗 prompt 前綴**（不含 diff）寫入 `$CLAUDE_JOB_DIR/codex-challenge-packet.txt`
（同 Step 2A：diff 不經 Write tool，避免 LLM 逐字複述）：

```text
IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. Stay focused on repository code only. Review ONLY the diff provided below; do not explore the repository.

Review the changes in the diff below. Find ways this code will fail in production. Think like an attacker and a chaos engineer. Find edge cases, race conditions, security holes, resource leaks, failure modes, and silent data corruption. Be adversarial. No compliments. Just the problems.

Structure your output EXACTLY with these three markdown headings, in order:
## Summary
<1-2 sentence adversarial overall assessment>
## Findings
<the problems, each tagged [P0]/[P1]/[P2]; write "None found" if truly clean>
## Verdict
<one line: how many ways this can fail in production>

<若使用者指定重點（如 challenge security），加入：Focus specifically on: <重點>>

=== DIFF ===
```

再用 bash redirection 把 diff 接到 packet 末端（不經 LLM）：

```bash
cat "$CLAUDE_JOB_DIR/codex-challenge-diff.patch" >> "$CLAUDE_JOB_DIR/codex-challenge-packet.txt"
```

執行（`<repo_root>` 替換為 repo root；**不用 `timeout`**——同 Step 2A）：

```bash
codex exec -C "<repo_root>" -s read-only -c 'model_reasoning_effort="high"' --enable web_search_cached < "$CLAUDE_JOB_DIR/codex-challenge-packet.txt"
```

**Exit-code gate（先於 hijack 檢查）**：codex exec 非零退出 → 停止並告知使用者：
「codex exec 失敗（非 hijack）；請確認 `codex login` 或網路後重試。」不可把非零退出當 hijack。

**Hijack 偵測**（同 Step 2A，僅在 clean exit 後）：輸出若不含 `## Summary`、`## Findings`、
`## Verdict` 三個標題（上方 packet 已明確要求），判定 agentic hijack，停止並回報。

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

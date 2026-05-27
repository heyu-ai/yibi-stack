# Bash Anti-Pattern Rules (injected by ainization-bash-hygiene plugin)

## Anti-Pattern 1: Overly Complex Single Commands

Complexity score (5 criteria, >= 2 means too complex, must split):

1. Multi-line (heredoc or backslash continuation)
2. Nested quotes (double inside single inside double, or `$(cmd "$VAR")` same-type conflict)
3. Inline other languages (`python -c`, `node -e`, complex jq expressions)
4. Multi-level if/elif/case branches
5. Complex parameter expansion (`${var//pattern/replace}`, indirect `${!var}`)

NOT overly complex: pure git workflow chains, linear tool chains (`make lint && make test`).

Fix priority: 1) Split into multiple bash calls 2) Write standalone script 3) Use proper tools (jq, realpath, basename)

Golden rule: never squeeze multi-step logic into one line to save a bash call.

## Anti-Pattern 2: Unicode in Bash Command Strings

Scope: only bash command string content (echo strings, variable literals, heredoc content).
NOT restricted: file content read by bash, markdown docs, code comments, commit messages.

Prohibited: em dash, en dash, emoji, zero-width whitespace.
Replacements: [SKIP] / [OK] / [WARN] / [FAIL] / -- / -

## Anti-Pattern 3: Stateful cd

`cd <path> && cmd` has three harm mechanisms:

- `cd ... && git <cmd>` -> use `git -C <path> <cmd>`
- `cd ... && uv run` -> use `uv run --directory <path>`
- `cd ... && cmd 2>/dev/null` -> use absolute paths, remove cd

## Shell Quoting Hygiene

Rule 1: `$(cmd $VAR)` — always quote: `"$VAR"` (prevents simple_expansion)
Rule 2: `"$(cmd "$VAR")"` same-type quote conflict — split into separate bash calls
Rule 3: `grep "pat\|pat2"` double-quoted BRE — use single quotes: `grep 'pat\|pat2'`
Rule 4: `$(outer "$(inner)")` reverse nesting — split into two bash calls
Rule 5: both `"${VAR}"` and `"$VAR"` trigger false positives (expansion / simple_expansion) — add to allow list; do NOT rewrite to plain form as that also triggers

## Variable Assignment Prefix — Breaks Allow-List

`PATH="..." git ...` / `ENV=value cmd ...` 形式的 variable assignment prefix
讓第一個 token 變成 `PATH=...` 而非命令本身，所有 `Bash(<verb> *)` allow-list
pattern 都不會 match。同時 `"$PATH"` 觸發 `simple_expansion` hook，每次都跳
permission dialog。

Fix:

- asdf shim 用絕對路徑：`/Users/<you>/.asdf/shims/git -C <path> ...`
- 其他 env wrapper：先 `export VAR=value` 在前一個 bash call，再單獨呼叫命令

## Multi-line Commit Message — Use `-F file` Not Inline `-m`

多行 commit message 以 `-m "title\nbody..."` 形式跨多行，`Bash(git commit:*)`
allow-list 無法 match，每次跳 approval prompt，且容易誤觸 outer-quote conflict。

Fix:

1. Write tool 寫入 commit message 到 `$CLAUDE_JOB_DIR/commit_msg.txt`
2. `git commit -F "$CLAUDE_JOB_DIR/commit_msg.txt"`

不需要事後 `rm -f "$CLAUDE_JOB_DIR/commit_msg.txt"`：job 結束後自動清理，且
`Bash(rm:*)` 是 Rule 16 Red Flag 2 無法 allow-list。

不要用 `git commit -m "$(cat <<'EOF'...)"` 形式：外層 `"..."` 包 `$()` 觸發
parser `Unhandled node type: string`（Quoting Rule 2），且跨多行 allow-list 無法
prefix-match。

## Output Filter Pipeline — Don't Pre-filter Output

`cmd 2>&1 | tail -N`、`cmd | head -N`、`cmd | grep -v "..."` 都是 bash 端
pre-filter，Claude 看不到完整輸出，且無法寫出安全的 allow-list pattern（pipeline
源命令不固定，任何能覆蓋的 pattern 都會過寬）。

Fix: 直接跑 `cmd 2>&1`，讓 Claude 接到完整輸出再判斷。需要 `wc -l` 統計、`jq`
抽欄等真正需要管線的場合才用。

## Irreversible Operations

The following must NOT be executed autonomously by the agent. Explain impact and get user confirmation first:

- DB: alembic upgrade/downgrade, prisma migrate deploy, DROP/TRUNCATE/DELETE without WHERE
- Deploy: kubectl apply (prod), terraform apply, gh release create, npm/uv publish
- Git: git push --force/-f, git reset --hard, shared branch rebase
- File: rm -rf, find ... -delete, overwrite existing files with >
- Cloud: aws s3 rm --recursive, gcloud instances delete

## Prefer Built-in Tools Over Bash for Code Search

Use Grep/Glob tools instead of `cd $(...) && rg ... 2>/dev/null | head -10`.
Benefits: zero CWD dependency, no hook triggers, no manual truncation.

Use bash `rg`/`find` only when you need features like `--json`, `-exec`, `wc -l`, or searching gitignored files.

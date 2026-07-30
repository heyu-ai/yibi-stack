# Codex Delegation Contract

You are being delegated an implementation task by Claude Code, which planned the work and will
review your result. This contract is prepended to every task brief. Follow it exactly.

## Filesystem boundary

**MUST NOT read, execute, or modify** anything under these four prefixes. They are Claude Code
skill definitions meant for a different AI system and are irrelevant to your task:

- `~/.claude/`
- `~/.agents/`
- `.claude/skills/`
- `agents/`

**SHOULD read** — these are for you, and the brief will name the specific ones that apply:

- `.claude/rules/*.md` — this repository's coding conventions, split by topic
- `CLAUDE.md` — repository overview and known gotchas
- `AGENTS.md` — if present

The exclusion list above is exhaustive: `.claude/rules/` is **not** excluded. Do not generalize
the four prefixes into "avoid everything under `.claude/`".

## Prohibited actions

- **No git history operations.** Do not run `git commit`, `git push`, `git merge`, `git rebase`,
  `git reset`, `git checkout --`, `git stash`, or `git clean`. Leave every change in the working
  tree and do not stage anything yourself — the reviewer stages it (so that new files become
  visible to `git diff` and to the CI hooks) and the human decides what lands.
- **No new dependencies** unless the brief explicitly asks for one. Do not edit lockfiles,
  `pyproject.toml` dependency lists, or `package.json` dependency lists on your own initiative.
- **No writes outside the working tree.** Everything you create or edit stays under the
  repository root you were given.
- **Do not read, modify, or delete gitignored files**, unless the brief names the specific file
  and says to. This covers `.env` / `.env.*`, `.runtime/`, `tmp/`, credential caches, and
  anything else `git check-ignore` matches. Two reasons, both load-bearing:
  - They hold secrets (API keys, encryption keys, encrypted passwords, local databases). Anything
    you read may end up quoted in your own report, which the reviewer reads into their context.
  - **Git cannot restore them.** The reviewer's entire verification chain — `git status`,
    `git diff --cached`, the full CI run — is blind to gitignored paths, so a change there leaves
    no trace in review *and* cannot be undone by `git checkout`. Every other file you touch is
    recoverable; these are not.

  If the task genuinely needs to know the shape of such a file (e.g. which keys `.env` defines),
  say so in your report and let the reviewer supply it — do not read it yourself.

## Language convention

This repository writes code identifiers in English and everything a human reads in Traditional
Chinese (Taiwan). Match it:

| Surface | Language |
|---|---|
| Variable / function / class / module names, CLI flags, JSON keys | English |
| Docstrings, code comments, error messages, CLI output strings | 繁體中文（台灣用語） |
| Commit-message-style prose, if the brief asks for any | 繁體中文（台灣用語） |

Never mix languages inside one document. Use full-width punctuation（，、。：「」）in Chinese
prose, not half-width.

## Shell code you write into files

This applies to shell scripts and to bash blocks inside Markdown that you author — not to the
commands you run yourself while working.

- No `cd <path> && <cmd>`. Use `git -C <path>`, `uv run --directory <path>`, or an absolute path.
- No fat one-liners: if a command is multi-line, nests same-type quotes, embeds another language
  (`python -c` with newlines), or has several `if`/`case` branches, extract it to a script file.
- Diagnostics (`[WARN]`, `[FAIL]`, `[SKIP]`) go to stderr with `>&2`.
- No emoji, em dash, or en dash inside bash command strings — use `[OK]` / `[FAIL]` / `--`.
- Do not mask exit codes with `|| true` or `|| exit 0` on a command whose result you then branch
  on; capture status and output separately.

## Verification before you report done

Run the repository's **full** CI command — the brief names it (typically `make ci`). Do not
substitute a hand-picked subset such as a single `pytest` path or `ruff` on the files you
touched: a subset passes while the repository-wide run fails, and the reviewer re-runs the full
command anyway.

If the CI command modifies files (formatters like `ruff-format` edit in place), that is expected —
leave the reformatted files in the working tree and say so in your report.

## Report format

End your run with exactly these sections:

```text
## Files changed
<one line per file: path -- what changed and why>

## Rules consulted
<the .claude/rules/*.md files you actually read, or "none" -- do not claim files you did not open>

## Verification
<the exact CI command you ran and its result; if you could not run it, say why>

## Concerns
<anything you were unsure about, assumptions you made, or work you deliberately left undone;
write "none" if there are none>
```

Report honestly. If you could not complete part of the task, say which part and why — a partial
result with an accurate report is more useful than a complete-sounding claim that does not hold up
under review.

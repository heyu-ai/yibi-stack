---
globs: skills/**
---
# SKILL.md Authoring Guide

## Frontmatter (Required)

```yaml
---
name: <skill-name>        # kebab-case, must match directory name
type: exec                # exec | tool | know
scope: global             # global | project (required; missing causes make install to fail)
description: <one-line description with trigger keywords — keep in Chinese for trigger-word matching>
---
```

### scope Selection Guide

| scope | Criteria |
|-------|----------|
| `global` | Pure methodology, or steps that run in any git repo (knowledge skills, general tools) |
| `project` | Steps require `uv run python -m tasks.*`, `.runtime/*.json` profiles, or repo-specific resources |

**Important**: `make install` only installs skills with `scope: global` by default.
A missing `scope:` field causes install to fail with exit 1 and an error message; it must be added.

If a skill's implementation lives in this repo but is semantically useful cross-project
(e.g. mycelium, local-port-manager), resolve the repo path at the start of
the execution steps and set scope to `global`:

```bash
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
```

`scripts/resolve-skill-repo` (symlinked to `~/.agents/bin/resolve-skill-repo` by
`make install`) prints the repo's absolute path on stdout and a `[FAIL]` diagnostic on
stderr. It takes no argument.

The caller does **not** re-validate the path — the script already fails loudly on both
"cannot resolve" and "resolved to the wrong repo", so a `-z` / `-d` gate at the call site is
dead code (and a `-d` gate re-asserts the very existence-only check this rule forbids).
The caller's one `echo` covers a different case the script cannot report on its own: when
the **script itself is missing** (`make install` never ran) the shell fails with a bare
`No such file or directory` and there is no resolver alive to print guidance. Keep that
`[FAIL]` line so the failure names its own fix.

**Bootstrapping dependency — `make install` is required after pulling this repo.** Because
every call site goes through `~/.agents/bin/resolve-skill-repo`, a checkout that is pulled but
not re-installed has skills calling a resolver that does not exist yet, and they fail until
`make install` runs. This is a deliberate, accepted trade-off, decided when the resolver landed:

- The failure is **loud and self-describing** (`[FAIL] ... 請在 yibi-stack 目錄執行 make install`),
  never a silent wrong answer — which is the whole point of retiring the config.json lookup, where
  the *failure mode was silence*.
- The alternative — giving each in-repo script its own fallback copy of the symlink-resolution
  preamble — would re-scatter the exact logic this rule consolidates into one implementation, and
  every copy is a place for the file-symlink trap below to be re-introduced.

"pull → `make install`" is already the standing requirement for this repo's skills (see the
CLAUDE.md gotcha on installed skills going stale); the resolver makes it enforced rather than
merely advisable.

### Never locate this repo via `~/.agents/config.json`

**Do not read `skill_repo` (or `skill_repos[...]`) from `~/.agents/config.json` to find this
repo.** That file is shared across multiple skill repos (yibi-stack, ainization-skill) whose
`make install` runs co-write it, so the flat `skill_repo` key holds whatever the *last*
installer wrote. An existence-only gate cannot catch this: the wrong repo also exists.

This is not hypothetical. Measured on a live machine during the PR #221 follow-up:

```console
$ python3 -c '...print(c.get("skill_repos", {}).get("yibi-stack") or c.get("skill_repo"))'
/Users/<you>/Workspace/github/ainization-skill     # wrong repo
$ test -d /Users/<you>/Workspace/github/ainization-skill && echo PASSES
PASSES                                             # [ -d ] gate lets it through
$ test -d /Users/<you>/Workspace/github/ainization-skill/tasks || echo "no tasks/"
no tasks/                                          # every `uv run --directory` caller breaks
```

The `skill_repos["yibi-stack"]` map added for issue #197 does **not** rescue this: the map is
not guaranteed to exist (the machine above had no `skill_repos` key at all), so a map-first
resolver silently falls through to the clobbered flat key. Map-first narrows the window; it
does not close it.

`resolve-skill-repo` closes it by **self-locating**: it derives the repo from its own file
location (`BASH_SOURCE` → resolve symlink chain → `git rev-parse --show-toplevel`), so the
answer is always "the checkout that installed this script" — no shared mutable state is
consulted. It then verifies **identity, not mere existence** (`tasks/mycelium` must be
present; plain `tasks/` does not discriminate — the sibling repo has one too).

### `make install` must run from the main repo, never from a worktree

Self-locating is what makes a worktree install dangerous, and the danger is a direct
consequence of the property that makes the resolver correct: it faithfully resolves to
**the checkout that installed it**. Install from `.claude/worktrees/<name>/` and every
global symlink points into that worktree; once the branch merges and `/clean-merged`
removes it, the symlinks dangle and every skill dies.

**Keep "the guard is the first recipe line" as a literal, testable invariant** — do not relax it
to "the guard precedes the first *mutation*". A reviewer proposed moving each target's
`[ -z "$(SKILL)" ]` usage check above the guard, so that forgetting `SKILL=` inside a worktree
reports the usage error rather than the (longer) worktree error. Declined, deliberately: the
usage check mutates nothing today, but "guard first" is checkable by a test that anyone can read,
while "guard before the first mutation" requires every future editor to correctly classify their
own line — and the cost of one wrong classification is the silent global-state corruption this
whole gate exists to prevent. The UX gain is also thin: a caller inside a worktree must fix that
first regardless of the missing argument.

**Guard every target that writes global state individually — a prerequisite chain is not a
gate.** `install-all` lists `install` before `install-scheduler`, but `make -j` runs
prerequisites **in parallel**, so the scheduler can finish writing a worktree path into its
LaunchAgent plist before `install`'s guard aborts the build. The same applies to
`install-handover-hooks`, which embeds the repo path into `~/.claude/settings.json` hook
commands. Neither goes through a symlink — both self-locate in Python from `__file__` — so the
symlink-shaped reasoning does not cover them; what they share is "writes the repo path into
machine-level state", and that is the property to guard on.

Nothing in the resolver can detect this — by construction:

- The identity gate passes: a worktree is a **complete checkout**, so `tasks/mycelium` is there.
- The Makefile's post-install gate (`resolved == $(CURDIR)`) passes: inside a worktree those
  two **are** equal. That gate catches "points at another checkout"; it cannot catch "points at
  a checkout that is about to be deleted".

This is also a **regression risk introduced by retiring config.json**, and it must not be
re-litigated as "the old way was safer": the old lookup was rewritten by `register_skill_repo.py`
on *every* `make install`, so a moved or deleted checkout self-corrected on the next run. A
symlink does not self-correct. The resolver traded a silent-wrong-answer failure mode for one
that needs an explicit up-front gate — which is `scripts/assert_not_worktree.sh`, wired as the
**first recipe line** of every target that writes machine-level state (first, because those
targets write global symlinks before they reach the resolver step — failing late leaves
`~/.claude/skills/` already polluted). The authoritative list is `GUARDED_TARGETS` in
`scripts/tests/test_assert_not_worktree.py`, which the tests enumerate — do not re-list the
targets here; an enumeration copied into prose is one more claim that decays silently (this
paragraph said "four targets" for three PRs after the count became seven).

Detection is `--git-dir != --git-common-dir` (in a worktree the former is
`<main>/.git/worktrees/<name>`, the latter `<main>/.git`; in the main repo they are equal).
Do **not** substring-match `.claude/worktrees` — a worktree may be created at any path.

**A fail-open must name the single condition it forgives, never "the call failed"** — and then
check that the condition it names is actually single. This one bit twice, one level apart:

1. The guard's non-git pass-through is deliberate (an unpacked zip cannot be a worktree), but the
   first implementation expressed it as "if `git rev-parse` fails, exit 0", silently forgiving a
   much larger set: git older than 2.31 (`--path-format` unknown), dubious ownership under
   `sudo make install`, permission errors, git missing from `PATH`, an unreadable directory. Each
   made the gate cease to exist with no warning. All three mob-review voices flagged it.
2. Narrowing it to "git's stderr says `not a git repository`" looked exact — but **git says the
   same sentence for two different conditions**. A linked worktree whose admin dir is gone
   (pruned, or the main repo moved/re-cloned) reports `fatal: not a git repository: (null)`, so
   the narrowed match still waved through a directory that is unmistakably a worktree *and*
   already doomed — precisely what the gate exists to catch. Measured, not theorised:
   `rm -rf <main>/.git/worktrees/<name>` and `mv <main> <elsewhere>` both reproduce it.

   The disambiguator is the filesystem, not the message: the legitimate case (unpacked zip) has
   **no `.git` at all**. A `.git` that exists while git denies the repo means broken, not absent.
3. `[ ! -e "$DIR/.git" ]` then looked exact, and was not either: **`-e` follows symlinks**, so a
   *dangling* `.git` symlink (link present, target gone) satisfies `! -e` and fail-opened again.
   Reproduced on a real worktree whose `.git` was replaced by a dangling link. The predicate has
   to be `[ ! -e "$DIR/.git" ] && [ ! -L "$DIR/.git" ]` — `-L` is what asks "does the entry
   itself exist".

4. `[ ! -e ] && [ ! -L ]` on `$DIR` was still not it: `$DIR` can be a **subdirectory** of the
   broken worktree, where no `.git` lives — it sits at the worktree root. Blocked at the root,
   fail-open one level down. The predicate has to walk ancestors.

Four rounds, one shape: **each time the fail-open was narrowed, the new condition still covered
more than its name suggested.** When you write a fail-open, do not stop at naming the condition —
enumerate the states that satisfy the predicate you actually typed, and probe each. Reading it as
prose is how all four survived review.

**Then the fix for the fail-open grew its own fail-opens — twice, in shapes already fixed
elsewhere in the same file.** Round 5 added a "is this path a registered worktree?" check on the
pass path; round 6 found it (a) skipped itself entirely when `git worktree list` failed, because
it was written as `if REGISTERED=$(...); then …; fi` with `exit 0` below, and (b) compared `$DIR`
by **equality** with each worktree root, so a **subdirectory** walked straight past it. Both are
verbatim repeats: (a) is the round-1 "command failed → pass" shape, (b) is the round-4 "the
marker is at the root, not at `$DIR`" shape that the ancestor walk twelve lines away exists to
solve. Two reviewers named the repeat explicitly.

The generalizable rule: **after fixing a class of bug, grep your own new code for that class
before shipping it.** Recency does not inoculate — the round-5 code was written *by the author
of the round-4 fix, hours later*. Fixing a bug creates new code, and new code is where the same
bug goes next. Concretely, for a gate: every new `if cmd; then check; fi` needs "what happens
when `cmd` fails?", and every new path comparison needs "what if the input is *under* this path?"

**The documented residual is a claim too, and it decays with each fix.** State the limit
explicitly — but re-probe it every time the predicate changes, because a stale residual note is
worse than none: it tells the next reader (and reviewer) that a hole is known and accepted when
in fact it has moved. This rule was itself learned twice on the same PR, which is the point:

- Round 2's note said "only outright `.git` deletion is undetectable". By round 4 that was false
  twice over — the dangling-symlink and subdirectory cases both slipped past while the note
  claimed otherwise, and a reviewer caught the contradiction between code and note before
  catching the code.
- The note was then rewritten to say an in-tree worktree with a deleted `.git` "passes safely,
  and that is fine". Round 5 added a registration check that **blocks exactly that case** — and
  the note still claimed the old behavior until round 7, when a reviewer flagged the code/doc
  contradiction. The lesson had already been written into this very file by then. Writing the
  rule does not execute it.

The honest residual, re-probed: a worktree whose `.git` is deleted outright **and** which lives
outside the main repo's tree — there it is byte-identical to an unpacked zip. In-tree cases are
caught by the `git worktree list` registration check.

Operationally: treat a residual note like a test. When you change the predicate, the note is part
of the diff — if you did not re-run the scenario it describes, you do not know whether it is still
true.

**Do not run mutation tests on a shared worktree file while a review agent is reading it.**
Mutation testing edits the real file in place; a reviewer dispatched against that path will read
whatever state the file happens to be in. On this PR a reviewer read the script mid-mutation, got
one **false clean result**, and had to flag the race instead of reviewing. The global CLAUDE.md
already records this incident in the opposite direction (a verification subagent editing the file
the lead was reading) — it is symmetric, and the lead is not exempt. Sequence them: finish the
review round, collect every report, *then* mutate. If you must do both, mutate a copy outside the
worktree. Corollary for reviewers: pin any report on a mutable file to a SHA.

**An error message's hint must share the predicate of the branch it explains.** The guard's
"this repo is broken — pruned admin dir? main repo moved?" hint was gated only on "`.git`
exists", not on "git actually said *not a git repository*". So any other git failure inside a
directory that has a `.git` printed a confident, fabricated cause — reproduced against a
perfectly **healthy main repo** with a shimmed dubious-ownership error. Fail-closed was right;
naming a cause it had not established was not. This is the same rule as the `dirname` fallback
above, one level in: that fallback pointed at a possibly-wrong *directory*, this hint at a
possibly-wrong *reason*.

Because git localises its messages, any such match must pin `LC_ALL=C`, or it silently misses on
a non-English machine and starts blocking legitimate installs instead.

**Clear `CDPATH` before using `cd` to normalize a path.** POSIX has `cd` search `CDPATH` whenever
the target's first component is neither `.` nor `..` — which is exactly what git returns
(`.git`). On a hit, `cd` also **prints the destination to stdout**, so a `$(cd … && pwd -P)`
capture silently gains a second line. Measured on this repo's guard. It was not yet exploitable
there, but only because of which paths git happens to emit relative vs absolute — not a property
worth resting a safety gate on. `export CDPATH=` removes the dependency.

**Under `set -e` + `pipefail`, a bare `X=$(cmd | awk …)` kills the script and makes any fallback
below it dead code.** The guard resolved the main repo that way with a `dirname` fallback
underneath; when `git worktree list` failed, the script died at that line — exit 128, **no output
at all** — after it had already decided the directory was a worktree, so the `[FAIL]` never
printed and the fallback was unreachable. Wrap it in `if !`. Relatedly, do not let `awk` `exit`
early in such a pipeline: the producer gets SIGPIPE and `pipefail` turns a successful command
into a failure. Use a flag (`!seen`) and consume the whole stream.

**Normalizing git paths: use `cd`+`pwd -P`, not `--path-format=absolute`.** Two traps, both
measured on this repo during PR #234's review:

- `--path-format=absolute` needs git >= 2.31 (2021). Using it puts the gate's correctness on a
  version floor this repo does not otherwise require (rule 13 already documents caring about
  macOS < Ventura toolchains). `(cd "$dir" && cd "$raw" && pwd -P)` is portable and
  format-independent.
- Comparing the **raw** `rev-parse` outputs (the obvious way to avoid `--path-format`) is wrong:
  the two flags do not answer in the same spelling. From a main-repo **subdirectory**,
  `--git-dir` returns an absolute path while `--git-common-dir` returns `../.git`; from a
  **symlinked** path, `--git-dir` returns the *physical* path while a relative `--git-common-dir`
  resolves *logically*. Either asymmetry makes the two compare unequal and **falsely blocks a
  legitimate main-repo install**. `pwd -P` (physical, not logical) collapses both into one
  namespace. macOS's own `/var` → `/private/var` symlink is enough to trigger this.

**Report the main repo from `git worktree list --porcelain`, not `dirname` of the common dir.**
Its first `worktree` entry is authoritative. The common dir's parent is not necessarily the main
work tree (`git clone --separate-git-dir`, submodules), so `dirname` can print a `cd` target that
does not exist — an error message that misdirects is worse than a terse one.

**And when the authoritative lookup fails, print no recommendation at all** — do not fall back to
the guess you just rejected. The guard originally kept `dirname` as a fallback under exactly the
comment explaining why `dirname` is wrong; a reviewer caught it by holding the code to the
sentence above. A fallback that re-introduces the defect its own comment documents is worse than
having no fallback: say "could not determine the main repo" and let the operator look.

**Any new `git` call added to the resolver family must clear inherited git env vars.** This
is a shared trap, not a per-script detail: `GIT_DIR` / `GIT_WORK_TREE` / `GIT_COMMON_DIR`
outrank `git -C`, so git answers about *that* repo and ignores the `-C` directory entirely.
Both `resolve-skill-repo` (PR #233) and `assert_not_worktree.sh` therefore route every call
through `env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE git`. Measured
on the guard before it was hardened: with `GIT_DIR=<main>/.git` set, it flipped from `exit 1`
to `exit 0` inside a worktree — the gate silently ceased to exist. This path is routine, not
exotic: git sets `GIT_DIR` while running hooks, and this repo leans heavily on pre-commit.

The guard **fails loud rather than auto-deriving** the main repo via `--git-common-dir`, even
though that would "just work" for the user. Auto-deriving would install the *main repo's*
checkout while the user is looking at their worktree's code — possibly a different branch or
an older commit. That is a silent wrong answer, the exact failure class this whole resolver
design exists to eliminate. A non-git directory (an unpacked zip) is passed through, not
blocked: it cannot be a worktree, so blocking it would be a pure regression.

`scripts/resolve-skill-repo` is the single implementation — do not inline a copy of its
logic into a SKILL.md. If you need this in a script that already lives in the repo, that
script can self-locate directly instead of shelling out (see
`plugins/pr-flow/skills/pr-control-log/scripts/bootstrap.sh` for the in-script form).

**Gotcha — `pwd -P` does not resolve a *file* symlink.** The in-script form
`SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)` only works when the symlink is
on a **directory** in the path (as with `~/.claude/skills/<name>` → `<repo>/skills/<name>`).
`resolve-skill-repo` is exposed as a **file** symlink under `~/.agents/bin/`, where that form
silently returns `~/.agents/bin` instead of the real directory — no error, just a wrong
answer. It therefore walks the symlink chain with `readlink` in a loop (macOS has no
`readlink -f`). Copy the right form for your symlink shape; verify by executing through the
symlink, not just directly.

**Note (error handling form)**: `cmd || { echo '[FAIL]' >&2; exit 1; }` contains a `'` quote
inside `{}`, triggering the "brace with quote character" confirmation dialog.
Always use `if ! cmd; then echo '[FAIL]' >&2; exit 1; fi` instead (the canonical form above
already uses this).

### A gate belongs at every entrance, and the tool that documents an entrance owns it

PR #234 wired the guard into 7 make targets and recorded the residual honestly: "the guard lives
in the Makefile, so calling the Python module directly bypasses it." Issue #237 closed it. Two
things are worth keeping from how that went:

**The "unrealistic" bypass was in our own help text.** The residual was defensible only if nobody
calls the module directly. But `tasks/scheduler/cli.py`'s `setup` command *prints*
`uv run python -m tasks.scheduler install` as the user's next step. The unguarded entrance was not
hypothetical — it was the documented one. Before accepting "nobody invokes it that way", grep for
the invocation in your own `--help`, `echo`s, SKILL.md, and README; a tool that teaches a path owns
that path.

**Guard the sink, and find all of them before choosing the altitude.** The issue named two
entry points; the repo had five. `insight install-hook` and `recap install-hook` build the same
`Path(__file__).resolve().parents[2]` command string into `~/.claude/settings.json` and have **no
make target at all** — the most exposed sinks were the ones nobody listed, precisely because the
Makefile inventory was the search index. The property to enumerate on is not "which CLI did the
issue mention" but **"what writes a repo path into state that outlives the checkout"**. Grep the
class (`parents[` / `PROJECT_ROOT` reaching a `~/…` write), not the ticket.

Three altitudes, and why the entry point wins here:

| Altitude | Verdict |
|----------|---------|
| Path source (`_paths.py`) | **No** — `PROJECT_ROOT` is imported by `status` / `tick` / tests; an import-time gate breaks read-only work inside a worktree, which is legitimate |
| Library install function | **No** — its destination is injectable (tests pass `settings_path=tmp`); gating it means either breaking every test or inventing a test-only bypass |
| Process entry point (CLI command / `main()`) | **Yes** — where install intent is expressed *and* where the real machine-level destination is chosen |

Residual, stated so it can be re-probed: importing an install function directly in Python still
bypasses this. That is an in-repo API consumer, not the documented surface — but if a future caller
appears, the guard moves down with it.

### A shared helper's message is part of its interface — a hardcoded caller idiom becomes a lie

`assert_not_worktree.sh` took `<make-target-name>` and printed `不可執行 make ${TARGET}` plus
`cd <main> && make ${TARGET}`. Correct while make was the only caller. The moment Python called it,
every message became a fabricated command: "不可執行 **make** uv run python -m tasks.scheduler
install", and a `cd … && make uv run python …` that fails on copy-paste. The detection was
caller-agnostic; the **message** silently was not.

The fix is the seam, not the string: the script now takes a `<recovery-command>` — the complete
command, program name included — and never prefixes anything. Callers own their idiom
(`"make install"`, `"uv run python -m tasks.mycelium insight install-hook"`). Its rationale line
was equally caller-specific ("symlink 會指向不存在的路徑，所有 skill 失效") and now names the
whole class it guards: symlinks, LaunchAgent plist, and settings.json hooks.

This is the same principle the script already enforced three times against *itself* — a misleading
message is worse than a terse one — applied one level out: **when a second caller arrives, re-read
every string the helper emits and ask which caller it was written for.** Reusing battle-tested
detection does not mean the prose around it transfers.

Pin it with a test, not a convention: `ANW-DT-016` asserts every Makefile call site passes a
command that **names its own target** (`"make <target>…"`), so dropping the prefix — or copying a
guard line to a new target and forgetting to change it — fails loudly instead of shipping a hint
that is uncopyable or points at the wrong target.

### Skill scope 與 plugin agent 依賴一致性

This repo distributes capabilities through two independent channels:

- **`make install`** symlinks every repo-root `skills/*/SKILL.md` whose frontmatter is
  `scope: global` into `~/.agents/skills/` — globally, across all projects. It carries the
  **SKILL.md only**, never the plugin's `agents/`.
- **`claude plugin install <name>@<marketplace>`** carries the whole plugin: skills **and**
  agents **and** commands.

A `scope: global` skill that dispatches a **same-repo plugin agent** (e.g.
`subagent_type: sdd:qa-test-designer`) therefore breaks in any project that has the skill
(via `make install`) but not the plugin: the agent is simply absent, and the skill either
hard-stops or silently degrades.

**Rule**: a `scope: global` skill MUST NOT dispatch an agent owned by one of this repo's own
plugins. Such a skill must be **plugin-only** — remove its repo-root `skills/<name>` symlink
and set `scope: project`, so it ships through `claude plugin install` together with its agents.
`scripts/lint_skill_scope.py` enforces this at commit time: it reads the own-plugin names from
`.claude-plugin/marketplace.json` and fails when a `scope: global` skill dispatches one of them
(detection keys on the `subagent_type:` / `subagent_type=` token, so prose mentions do not fire).

**External plugin agents are exempt.** When a global skill dispatches an agent from an *external*
plugin (e.g. `pr-review-toolkit:code-reviewer` from `claude-plugins-official`), demotion cannot
make that external plugin travel with the skill. Keep the skill `scope: global` but add a runtime
not-available gate (`[WARN]` + a fallback such as the built-in `/code-review` skill) and document
the plugin install requirement in the SKILL.md. The lint exempts external namespaces for this reason.

**Incident**: `spectra-amplifier` (a `scope: global` knowledge skill) dispatched `sdd:*` agents in
Step 1c/2a. Run in a project without the sdd plugin, the agents were absent and the skill silently
degraded to inline generation. Fix: demoted to plugin-only (symlink removed, `scope: project`) and
gave its `[FAIL] Stop` gates the explicit
`claude plugin install sdd@yibi-stack` install command.

### Trigger Coverage: direct / indirect / negative

The `description` field is the only trigger surface a skill has. Authors reliably test that it
fires on the obvious phrasing (`direct`) but rarely check the other two axes — and the missing
one, `negative`, is exactly what causes over-triggering (a skill hijacking a prompt that belongs
to a sibling). Before finalizing any `description`, self-check all three prompt classes:

| Class | Question the author must answer | What it protects |
|-------|--------------------------------|------------------|
| **direct** | Does a prompt using the literal trigger keywords fire this skill? | baseline recall |
| **indirect** | Does a paraphrase / synonym of the intent still fire it (without naming the keyword)? | recall breadth — catches under-triggering |
| **negative** | Is there a nearby prompt that must NOT fire this skill — especially one owned by a **sibling skill**? | precision — catches over-triggering |

The `negative` axis is the one this repo has never required, and it is the most valuable: it
forces the author to name the sibling skill whose territory they must not invade, and to keep
the two `description` fields from colliding.

**Worked example — the known over-trigger families.** These clusters share heavy keyword overlap,
so each member's `description` must carry an explicit negative boundary against its siblings:

- **PR lifecycle** — `pr-cycle-deep` / `pr-cycle-fast` / `pr-review-cycle`. This family already
  models the fix: each `description` ends by redirecting the out-of-scope prompt to the right
  sibling (e.g. pr-cycle-deep's `小型 PR 或快速 lifecycle 請改用 /pr-cycle-fast`;
  `純 PR review 不需完整 lifecycle 請改用 /pr-review-cycle`). That redirect clause **is** a
  negative-trigger declaration — copy this pattern.
- **Retro** — `pr-retrospective` plus the thin `/pr-retro` command wrapper (same trigger surface,
  much thinner frontmatter). A prompt about a *single* lesson should route here, not into a PR
  lifecycle skill.
- **Harness** — `harness-eval` (full 11-dimension sweep) vs `harness-eval-focus` (deep-dive on one
  dimension). "評估 repo" → the former; "D2 hook 問題" → the latter. Neither should steal the other.
- **TDD** — `tdd-kentbeck`'s `description` ends with `即使用戶只說「幫我寫這個功能」…也應觸發`,
  which widens its trigger to *any* "build this feature" phrasing. That sentence is a **cautionary
  example**: it is precisely the kind of unbounded clause a `negative` self-check should flag,
  because it makes the skill claim prompts that belong to plain implementation work. `flutter-tdd`
  (Flutter-specific) and `ci-triage` (CI failure diagnosis, not test authorship) are adjacent
  skills whose boundaries against `tdd-kentbeck` must stay explicit.

**Quantified detection is planned, not yet available.** A `scripts/lint_skill_overlap.py` that
measures pairwise `description` keyword overlap and flags over-trigger risk is tracked under
issue #186 (path B) and does **not** exist yet — do not cite it as an existing gate. Until it
lands, this three-class self-check is a manual authoring discipline. When it is built, model it on
`scripts/lint_skill_scope.py`: docstring-as-spec with an exit-code table, regex-based frontmatter
parsing (no YAML dependency), and a `[FAIL]`/`[OK]` message that points back to this section.

## Frontmatter — `effort` (Optional, added 2026-05)

Claude Code v2.1.133+ supports specifying effort in skill / slash command frontmatter,
**overriding the caller's model effort**:

```yaml
---
name: <skill-name>
type: exec
scope: global
effort: medium     # optional; low | medium | high
description: ...
---
```

### When to Use `effort` Frontmatter

| Scenario | Recommendation |
|----------|---------------|
| Skill is a "heavy batch" (large downloads, long scans, deep spec expansion) | Pin `effort: medium` or `high` to avoid accidental triggering in a low-effort session |
| Skill is a "quick summary" type | Pin `effort: low` to save tokens |
| Skill behaves similarly across effort levels | Leave unset; follow the caller |

### Relationship to the `${CLAUDE_EFFORT}` Block in SKILL.md Body

Frontmatter `effort` is the **override** final value for the caller's effort;
the `${CLAUDE_EFFORT}` table in the SKILL.md body defines **the execution strategy at that effort level**.
The two work together:

- No frontmatter `effort` + body has `${CLAUDE_EFFORT}` table → dynamically routes based on caller
- Frontmatter `effort: medium` + body has `${CLAUDE_EFFORT}` table → always takes the medium row

### Runtime Gotchas for `${CLAUDE_EFFORT}`

- **`CLAUDE_EFFORT=normal` is the hook default**: hooks use `${CLAUDE_EFFORT:-normal}`;
  a SKILL.md effort table's fallback note must cover both unset AND `normal`
  (both default to full execution — "not-low" behavior, equivalent to `medium`/`high`).
  CC 2.1.133+ makes `$CLAUDE_EFFORT` a real env var in Bash tool / hook scripts
  (read directly; `:-normal` is for pre-2.1.133 compat).
- **Effort fallback is risk judgment, not convention**: general tools default to `medium`;
  spec-expansion / deep-review tools may pin `high`
  because missing spec coverage costs more than doing extra work.
- **`${CLAUDE_EFFORT}` does not expand in static SKILL.md**: the agent reads it
  as a literal string. To get the actual value, use `echo "${CLAUDE_EFFORT:-normal}"`.
  Hook scripts (bash, CC 2.1.133+) can read `$CLAUDE_EFFORT` directly as an env var
  — no `echo` subprocess needed.

## Frontmatter — Additional Keys (Optional, Claude Code v2.1.186)

Claude Code v2.1.186 added several usable frontmatter keys and made key names
**case- and separator-insensitive** (`display-name`, `display_name`, and `displayName` are
all equivalent; kebab / snake / camel all work):

```yaml
---
name: <skill-name>
type: exec
scope: global
display-name: Gmail Billing Scan     # override the display name (defaults to name)
default-enabled: false               # skill not enabled by default; loads only on explicit call / schedule
fallback: <skill-name-or-behavior>   # fallback when the primary skill is unavailable
metadata:                            # arbitrary metadata; readable by the agent
  owner: howie
  domain: finance
description: ...
---
```

| Key | Purpose |
|-----|---------|
| `display-name` | Overrides the skill's display name in UI / lists (does not affect `name` trigger matching) |
| `default-enabled` | `false` keeps the skill disabled by default, avoiding accidental long-batch triggering in a high-effort session |
| `fallback` | Fallback (skill name or behavior) when the primary skill is unavailable |
| `metadata.*` | Any custom key/value, for the agent to read or classify by |

**Broken frontmatter no longer disappears silently** (v2.1.186): when the YAML frontmatter is
malformed, the skill **body is still loaded** (metadata treated as empty) for easier debugging,
instead of the whole skill vanishing from the list. When a skill triggers but misbehaves
(description trigger words stop working, `effort` not applied), check the frontmatter for a
YAML syntax error first.

**Adopting `default-enabled: false` requires confirming the local version semantics first**:
it changes whether a skill loads by default — a behavior change, not just display. Before
applying it to heavy scheduled skills (`gmail-billing`, `icf-global-news-digest`, etc.),
confirm the local build is ≥ v2.1.186 via `claude --version` and verify empirically that the
skill still loads on schedule / explicit call.

## Exec Skill Standard 4-Step Template

```markdown
## Steps

### Step 1 — Environment Check
Confirm you are in the git repo root and required tools are available:
- `uv --version` OK
- Confirm `.env` exists

### Step 2 — Config Check
Confirm `.runtime/<config>.json` exists; ask the user to confirm key parameters:
- Profile: {{profile_name}}

### Step 3 — Execute
uv run python -m tasks.<module> <command> --profile {{profile_name}}

### Step 4 — Report Results
Report: success count, failed items, output path.
```

## `{{value}}` Placeholder

Parameters that require user confirmation use double braces: `{{profile_name}}`, `{{date}}`.

## FAQ Table

Append a FAQ at the end of each exec skill:

```markdown
## FAQ

| Issue | Fix |
|-------|-----|
| Config file not found | Run the `setup` subcommand to create the default config |
| API 403 error | Check whether the token in `.env` has expired |
```

## Knowledge Skill (type: know)

- Contains only methodology guidance; no Python execution steps
- May have multiple sections (e.g. Core Loop, Anti-patterns)
- Put rich trigger keywords in the `description` field

## Update the Index

After creating or modifying a skill, update the index table in `skills/README.md`.

`skills/README.md` has two tables under the "Global Skills" section:
"Executable/Tool (exec/tool)" and "Knowledge (know)".
`scope: project` exec skills belong to a third "Repo-Specific" table and are out of scope here.
**Classification is based on the `type` field in the SKILL.md frontmatter, not how the skill feels**:

| frontmatter `type` | Target table |
|--------------------|-------------|
| `exec` or `tool` | Executable/Tool |
| `know` | Knowledge (methodology) |

Common mistake: a `type: know` skill is placed in the tool table because it "feels executable"
(e.g. `bump-version`).
Before editing the README, confirm the type with (run from repo root):

```bash
grep -m1 '^type:' skills/<name>/SKILL.md
```

## Reference Template

`skills/_template/SKILL.md.tpl` is the canonical format reference.

## Decision Table and Prose Consistency

A decision table (mode table) must be self-contained: it cannot rely on prose outside the table
to describe exceptional behavior.
When an agent reads a SKILL.md, it executes by table row first; explanatory paragraphs outside
the table are easily skipped.

Correct approach:

- Add a guard row to the table (e.g. "any tool BINARY_OK+NOT_AUTHED → run stop flow first,
  do not enter count calculation")
- Or explicitly annotate applicable conditions in the action column of the matching row
  (e.g. "0 (all NOT_FOUND, no auth failures)")

Anti-pattern: prose says "stop when state X is detected", but the `count=0` row in the table
says "redirect terminate" — the agent follows the table and the prose intent is completely overridden.

## FAQ Fix Command Format

Fix commands in FAQ tables must meet three requirements:

1. **Use real variable names**: do not use placeholder literals like `KEY`;
   write actual names like `CODEX_API_KEY` / `GEMINI_API_KEY`
2. **Shell-hygiene-safe syntax**: use parameter expansion `"${VAR# }"` to strip leading spaces;
   do not use `$(echo $VAR)` subshell (does not trim in zsh; also triggers rule 13 quoting hygiene hook)
3. **Cross-shell compatible**: commands must work correctly in both zsh (macOS default) and bash

## Table Description Column — Single Responsibility

The description column of a Markdown table should contain only **functional description**;
do not repeat information from other columns (e.g. the Install column).

Common mistake: appending the install path in the description column
(e.g. `— no package.json, installed as global skill`).
The Install column already carries the install command; duplicating it in the description creates
a double-maintenance burden when the install method changes, and is inconsistent with other rows.

## Hook Descriptions Must Be Verified Against the Actual Script (PR #303 lesson)

When describing hook behavior in CLAUDE.md or SKILL.md, **always Read the hook script itself**;
do not write from memory or stale documentation.

Common mistake: description says "runs ruff format on .py files after Write/Edit" — but the
actual script only covers `backend/**/*.py`, and also runs `ruff check` (lint),
`tsc --noEmit` (frontend), and `terraform fmt -check` (infra).

Correct approach:

1. Use the Read tool to open `.claude/hooks/<hook-name>.sh` (or the actual script path)
2. Check the path guard (e.g. `*backend*`, `*frontend*`) to confirm which file types are actually affected
3. List all tool invocations line by line, scoped to actual coverage

```markdown
<!-- Wrong: written from memory / guessing -->
**Hook side-effects** -- automatically runs `ruff format` on `.py` files

<!-- Correct: verified against script, full coverage listed -->
**Hook side-effects** -- `post-edit-check.sh` runs automatically after Write/Edit/MultiEdit:
- `backend/**/*.py`: `ruff format` + `ruff check` (per-file)
- `frontend/**/*.{ts,tsx}`: `tsc --noEmit` (project-wide type check)
- `*.tf`: `terraform fmt -check`
```

The Claude voice in mob review found the mismatch after reading the script; Gemini R1 reported
"accurate (low confidence)" and only agreed on the fix after seeing Claude's findings in R2.
Description accuracy cannot rely on reviewer cross-checking — verify at authoring time.

## Cross-doc Cite Must Paste the Original Quote, Not a Summary from Memory (PR #415 lesson)

When a rule / doc / SKILL.md cites "another authoritative source" (another rule file, another
repo's document, an official API spec), **paste the original quote or an exact section reference;
do not paraphrase from memory**.
Memory paraphrases silently introduce errors in direction / active-passive voice / scope, and
first-round reviewers typically miss them because they only verify that the cited source exists,
not that the cited content supports the argument.

Typical failure pattern:

- `13-bash-anti-patterns.md` "exec wrapper penetrates deny rule (2026-05)" section
  Original: "Claude Code deny rules now see through `env` / `sudo` / `watch` ...
  do not assume a wrapper bypasses a deny rule" — meaning **deny rule is stronger, sees through wrapper**
- A new rule's first draft quoted this as: "the PATH= env-wrapper pattern **can penetrate deny rules**"
  — meaning flipped to **wrapper is stronger, bypasses deny rule**; active/passive reversed,
  **argument is the opposite of the source**
- First-round code-reviewer confirmed "source file exists + section name matches" and passed;
  second-round comment-analyzer caught the reversal by comparing against the original quote

How to avoid:

```markdown
<!-- Wrong: paraphrased from memory; active/passive easily inverted -->
Per yibi-stack 13-bash-anti-patterns.md "exec wrapper penetrates deny rule" section,
PATH= can also penetrate deny rules.

<!-- Correct: paste original quote; direction is self-evident -->
yibi-stack `.claude/rules/13-bash-anti-patterns.md` original:
> Claude Code deny rules now see through `env` / `sudo` / `watch` / `ionice` / `setsid`:
> ... do not assume a wrapper bypasses a deny rule.

From the original: **deny rule** blocks **wrapper**; wrapper cannot bypass deny rule.
```

Criteria for when to paste vs. summarize:

| Citation type | Paste or summarize? |
|---------------|---------------------|
| Direction (X attacks Y / Y attacks X; who is active / passive) | **Must paste** original; read direction yourself |
| Condition / scope (do Y when X) | **Must paste** condition original; avoid dropping the premise |
| Conclusion (result is Z) | May summarize, but the "because..." premise paragraph before the conclusion must be pasted |
| Tool / concept introduction | May summarize |

Cross-doc cites must verify **both ends** independently:

1. **Citation target**: file / section actually exists (path correct, not drifted)
2. **Citation content**: original actually supports your argument (direction / condition / scope aligned)

Verifying only the first end lets **dangling references** through
(link is correct but content is inverted).
Reviewer agent prompts should explicitly require "verify both ends of every cross-ref";
otherwise a single-source reviewer will miss inversion / mis-paraphrase errors.

Relationship to "Hook Descriptions Must Be Verified Against the Actual Script": both belong to
the cross-doc / cross-artifact verification discipline — hook docs must match the script,
rule cites must match the source, rule-to-spec relationships must match the source spec.
Verify at authoring time; do not assume a reviewer will catch it.

**Comment-analyzer catches direction errors that code-reviewer misses**: in PR #107, an Output
Filter section cited Red Flag 5 as the rationale for avoiding output filter pipelines. The real
reason is that pipeline sources vary at runtime (the source command is not fixed), making any
allow-list pattern necessarily too broad. Code-reviewer passed the citation (source file exists,
section name plausible); comment-analyzer caught the direction error by reading what Red Flag 5
actually says. **Both ends of every cross-ref must be independently verified** — target path AND
cited content alignment. Checking only the path is insufficient.

## Cross-Repo Citation: Doc Body Must Be Self-Contained; Lineage Goes in Commit Message

When codifying a lesson / incident from another repo into a doc / skill / rule, **do not embed
cross-repo source pointers like "Source: `<other-repo>` PR #`<N>` retro" in the doc body**.
Downstream readers may not have access to the source repo; the pointer is a dead link.
Even with access, switching repos and digging through retros costs ~10x more than reading the
doc itself.

Correct approach:

1. **Doc body**: a reproducible summary of the original incident (self-contained, with enough
   context that the reader can understand the lesson without leaving this repo).
2. **Commit message**: detailed lineage ("derived from `<repo>` PR #`<N>` retro" + handover ID + date).
3. **PR description**: same as commit message, plus motivation for why this lesson was ported cross-repo.

Evidence: yibi-stack PR #36 (pr-test-analyzer FAQ) — first version appended
"Source: openab_workspace PR #73 retro." at the end of the FAQ row.
code-reviewer NIT-1 and comment-analyzer Important #2 both flagged it: yibi-stack readers
have no access to openab_workspace, so the pointer is a dead link.
The fix removed the source pointer from the doc body, moved it to commit message + PR description,
and rewrote the FAQ row to be fully self-contained using generic helper names
(no longer tied to openab_workspace's `require_kubectl_context`).

Relationship to "Cross-doc Cite" (above): both are cross-doc writing hygiene, but on different axes —
Cross-doc Cite requires **pasting the original when citing** to avoid direction errors;
this section requires **the doc body to remain self-contained after citing** to avoid dead links.
In practice, follow both: first paste the original to verify direction, then naturally integrate
the verified content into this repo's narrative — leave no cross-repo pointers.

## Retro / Lesson-Routing Skills Must Name a Concrete Destination for Next Steps

Any skill that produces follow-up actions from retro / review results
(`/pr-retro`, various `*-cycle`, `*-review` skills) must not write vague language like
"consider", "maybe", "decide later" in the "next steps" section —
**verb is vague + destination is absent**.

Evidence: after yibi-stack PR #36 retro (handover `c88c0e9e`), the agent used a 4-option
AskUserQuestion (A/B/C/D) to route three testing-discipline lessons to concrete destinations
(each option mapped to an actual rule file + section name);
the user chose A and the lesson landed within one round (this PR is that landing).
Counter-example: if the follow-up only says "consider writing the lesson into documentation",
the user needs another "where?" round trip — retro landing rate drops by an order of magnitude.

Correct approach (at skill design time):

```markdown
<!-- Wrong: vague verb + no destination -->
- [ ] Consider writing the lesson into documentation

<!-- Correct: explicit destination + verb -->
- [ ] Write to `.claude/rules/15-irreversible-operations.md` Category 3 Recovery section (git workflow recovery)
- [ ] Write to `~/.claude/CLAUDE.md` cross-project personal preferences section
- [ ] Write to `<repo>/CLAUDE.md` Gotchas section (repo-specific)
- [ ] Do not document; mycelium handover only (one-off / non-recurring lesson)
```

Each option's "destination file + section" should already have been computed by the skill itself
(class maps to routing table), so the user sees actionable paths in AskUserQuestion,
not abstract suggestions.

Source practice: `/pr-retro` Step 5 Lesson Classifier (pr-retrospective SKILL.md) uses this pattern.

## Inserting a New Blockquote After an Existing One Requires Removing the Blank Line (MD028)

When inserting a new blockquote after an existing blockquote block, if there is a blank line
between them, markdownlint triggers **MD028/no-blanks-blockquote** (the blank line is treated
as "a blank line inside the same blockquote").

```markdown
<!-- Wrong: blank line between two blockquotes -->
> Existing text.

> **New execution note**: ...

<!-- Correct: remove blank line; merge into a single continuous blockquote -->
> Existing text.
> **New execution note**: ...
```

Common pitfall: inserting an "execution note" blockquote after a security warning blockquote.
The original `blockquote → blank line → code block` is valid, but changing it to
`blockquote → blank line → blockquote` violates MD028.
This pattern has recurred multiple times in this repo (PR #5, #24, #70).

**Quick validation** (run before committing to avoid CI roundtrips):

```bash
uv run pre-commit run markdownlint-cli2 --files plugins/<plugin>/skills/<name>/SKILL.md
```

## Scripts with Built-in stderr Logging Need a No-Capture Blockquote Hint

The background session harness automatically appends `> $CLAUDE_JOB_DIR/<name>.log 2>&1` to
Bash commands for output isolation and cross-compaction persistence.
For scripts that **already write stderr to an internal log**, this extra capture is redundant
and triggers a `~/.claude/` sensitive file permission dialog
(`$CLAUDE_JOB_DIR` expands to a per-session UUID path; the session-dialog "always allow" option
locks that specific UUID and the prompt reappears next session — see rule 16 **(2) Bash redirect `>`** for `Bash(verb:*)` allow-list patterns,
or **(1) Edit/Write tool** for `Edit(/Users/<you>/.claude/jobs/*)` / `Write(...)` patterns).

**Fix**: add a blockquote execution note before the bash code block to explicitly tell the agent
not to append external capture:

```markdown
> **Execution note**: the script writes stderr to `$REVIEW_DIR/<name>.log`; stdout outputs
> only "<completion message>". **Run directly — do not append `> $CLAUDE_JOB_DIR/foo.log 2>&1`**
> (harness auto-capture is redundant here; see rule 16 **(2) Bash redirect `>`** for `Bash(verb:*)`
> allow-list patterns if the prompt reappears) —
> Read `$REVIEW_DIR/<name>.log` on failure to see the full error.

\`\`\`bash
bash ~/.agents/skills/<skill>/scripts/<name>.sh
\`\`\`
```

**Applies when** the script meets all three conditions:

1. stderr is redirected to a fixed log file path (not stdout)
2. stdout outputs only a single "done" message (no diagnostic output the agent needs to read)
3. Runs in a background session flow (harness automatically appends log capture)

## Spec and SKILL.md behavioral guards must stay in sync

Any guard or exception in SKILL.md — a zero-score condition, a threshold constraint,
a tie-breaking rule — must be reflected in the corresponding spec.md decision table.

If the guard exists only in SKILL.md, the spec cannot be used to cross-check agent
behavior during review; if it exists only in spec.md, the agent never sees it.

**Pattern**: whenever you add a guard to SKILL.md, immediately update spec.md's decision
table (and vice versa). The two documents describe the same contract from different angles:
SKILL.md is the agent's execution interface; spec.md is the verifiable source of truth.

Example from harness-eval D5 (PR #83): in one commit the EG-* sub-item in SKILL.md was
tightened to require "at least 2 distinct EG categories" but spec.md's decision table was
not updated to match. Mob review round 4 caught the divergence and synced spec.md to reflect
the constraint.

The same discipline applies to **script exit-code contracts**: when a SKILL.md documents a
helper script's exit codes (e.g. "exit 1 = MUST/SHOULD findings"), the script's actual exit
paths must match. In PR #150 the SKILL.md row and `amplifier-verify.py` were written in the
same commit yet drifted immediately -- the script exited 0 on SHOULD-only findings. Mob review
caught it; the fix aligned the script to the documented contract. After writing doc + code
together, cross-check both directions: every behavior the doc claims exists in code, and
every exit path in code is documented.

When **deleting** a step or section, grep the document (and its command wrapper) for
references to it before committing. PR #150 removed Step 8a/8b from pr-review-cycle and left
three dangling references in one pass: a "needed for Step 8b" rationale in Step 7, a
"(3 agents)" heading over a 2-row table, and a command description still advertising the
deleted feature.

## MCP Call Failure Gates: Concrete Examples

General rule in `~/.claude/CLAUDE.md`: "Each external call (MCP tool, bash CLI) must have an
explicit `[FAIL]` stop condition with a clear error message."
The following shows the common missing-gate pattern in SKILL.md and the correct form:

```markdown
<!-- Wrong: no failure gate after MCP call; tool error silently continues -->
Call `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`
(`issueId`: `{{jira_issue_key}}`) to get the transition list.

Pick the option closest to "done"...

<!-- Correct: add failure condition immediately after each MCP call -->
Call `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`
(`issueId`: `{{jira_issue_key}}`) to get the transition list.
If the call fails, stop and report the error to the user.

Pick the option closest to "done"...
```

**Scope**: all MCP tool calls, including read-only queries (`get*`, `list*`, `search*`) —
a query failure does not mean "no results"; it may be an auth error or connection issue.
Without a gate, the agent continues with empty results and downstream steps silently drift.

**Parallel call failure gates**: when multiple MCP calls are dispatched simultaneously,
each call's failure must be reported independently:

```markdown
<!-- Wrong: dispatched in parallel with no per-call failure condition stated -->
Send in parallel:
- `mcp__...__transitionJiraIssue`
- `mcp__...__addCommentToJiraIssue`

<!-- Correct: explicitly state that either failure must be reported -->
Send in parallel (no dependency); **either failure must be reported
and must not be silently ignored**:
- `mcp__...__transitionJiraIssue`
- `mcp__...__addCommentToJiraIssue`
```

## MD013 Line-Length Validation for Translation PRs

Chinese prose translated to English consistently produces longer lines
(~30 CJK characters → 60+ English characters), frequently exceeding the MD013 200-character
limit. Translation PRs tend to accumulate many MD013 violations that are invisible until CI runs.

**Run this after translating, before committing**:

```bash
uv run pre-commit run markdownlint-cli2 --files plugins/<plugin>/skills/<name>/SKILL.md
```

Preferred line-break positions (in priority order):

1. After a period (`.`)
2. After a semicolon (`;`) or dash (`—` / `--`)
3. Before a conjunction (`and`, `or`, `when`, `if`)
4. Before an opening parenthesis

MD013 exempts table rows and code block lines (`tables: false`, `code_blocks: false`) —
only pure prose lines need to stay within 200 characters.

## Dual-Source Document Ownership (PR #112 lesson)

When two files both need to reflect the same methodology content
(e.g. a `SKILL.md` human entry and an `agent.md` programmatic entry both referencing the same technique list),
only **one file is the owner** that defines the canonical format and column names.
The other file must be explicitly labelled as a compressed summary — not a copy to sync.

**Wrong pattern**: both files declare themselves the source of truth and instruct maintainers to "sync the inline copy."
A maintainer following this instruction will overwrite the correct format with the wrong one.

**Correct pattern**:

- Owner file: defines canonical column headers, format, and technique names
- Summary file: explicitly states "this is a condensed summary optimized for in-context use;
  when technique semantics change, re-summarize this section — do NOT copy-paste from the owner file"

**Real incident (PR #112)**: `methodology.md` defined Coverage Analysis with "Expected Coverage Item" as the first column;
`qa-test-designer.md` (the file that actually produced output) correctly used "Scenario Slug."
Both files claimed to be the source of truth. A mob review Critical finding caught the divergence.
Fix: `methodology.md` was updated to use "Scenario Slug"; the sync instruction was changed to "re-summarize."

**Preflight: confirm the two paths are not a symlink before applying this doctrine.** This
doctrine applies only to two **genuinely duplicated, independently-maintained** files. Before
labelling one an owner and the other a summary, run `ls -la` (or `test -L`) on both paths: if one
is a symlink to the other (e.g. `skills/pr-retrospective` → `plugins/pr-flow/skills/pr-retrospective`),
there is a **single physical file** on disk — editing either path edits the same bytes, so both
stay in sync automatically and an owner/summary annotation is redundant and misleading. This is
"single source of truth, two access paths," not dual-source ownership.

**Real incident (PR #188)**: issue #185 instructed the author to "sync both versions" of the
pr-retrospective SKILL.md per this doctrine. An `ls -la` showed `skills/pr-retrospective` was a
symlink into `plugins/pr-flow/skills/pr-retrospective` — one file, not two — so the edit was made
once and no owner/summary label was added. Trusting the issue's premise blindly would have
produced a redundant annotation on a file that has no second copy to drift from.

## Task Subagent Failure Gates — Three Required Paths (PR #112 lesson)

When a SKILL.md dispatches a Task subagent, the failure gate must cover all three paths.
A gate that only covers path (a) silently produces garbage output on paths (b) and (c).

| Path | Example | Required gate |
|------|---------|---------------|
| (a) Subagent not available | plugin not installed | `If sdd:subagent not available: [FAIL] Stop.` |
| (b) Subagent ran but returned `[FAIL]` | all capabilities were `[BLOCKED]` | check output prefix before proceeding to next step |
| (c) Platform error | timeout, context-limit exceeded | catch Task tool failure itself |

**Template** (append after Task tool dispatch block):

```markdown
After receiving output from `sdd:subagent-name`:
- If the Task tool call itself failed (error / empty output):
  `[FAIL] sdd:subagent-name Task failed. Confirm plugin version and retry.`
- If output starts with `[FAIL]`:
  Stop. Surface the exact message to the user. Do not proceed to the next step.
```

Also add a pre-dispatch guard for the "all inputs filtered" case:

```markdown
If all inputs are `[BLOCKED]` (nothing to pass to the subagent):
`[WARN] All capabilities [BLOCKED] — skipping subagent dispatch.`
```

**Real incident (PR #112)**: spectra-amplifier Step 2a only had path (a).
When all capabilities were `[BLOCKED]`, the subagent returned `[FAIL]`,
Step 2b executed unconditionally, and a garbage `testplan.md` was written with no user-visible error.

## Tool Output Fields Must Be Verified Against Actual CLI Output (PR #115 lesson)

When a SKILL.md step instructs the agent to check a specific field in a tool's output
(e.g. `spectra status`, `gh pr checks`, `jq .some_field`), **verify the field exists
in the actual CLI output before writing**. Non-existent fields cause silent failures:
the agent finds nothing and either always-PASSes or always-FAILs with no error message.

Correct approach: run the tool locally with representative input and confirm the exact
field name appears in the output before referencing it in SKILL.md.

Relationship to "Hook Descriptions Must Be Verified Against the Actual Script": both belong to
the same verification-before-authoring discipline — hook docs must match the script,
SKILL.md field references must match the tool's actual output schema.

## Blanket Claims and Reader-Run Commands Must Be Empirically Probed Before Authoring (PR #200 lesson)

Two authoring habits that a self-review will miss but a reader (or a reviewer) will hit:

1. **A generalization ("any X", "always", "every") must be checked against its counter-examples,
   not just the one case you observed.** Writing a rule from a single reproduction tempts you to
   state the widest claim; the real boundary is usually narrower and environment-dependent. Before
   writing "any X does Y", spend one command testing the X's you did *not* observe — the boundary
   you find is the rule.
2. **A command the doc tells the reader to run must itself be run on the doc's target platform.**
   A detection/verification snippet that fails on the reader's default toolchain is a silent-failure
   trap: they see no output, conclude "clean", and the helper actually errored.

**Real incident (PR #200)**: a new rule stated a bare `$VAR` followed by "any non-ASCII char"
folds into the variable name under `set -u`. Cross-model mob review (Codex + agy) flagged it as
overgeneralized; a one-loop `bash -c` probe confirmed the truth is narrower — it is UTF-8-locale
*and* `isalnum()`-classification dependent (CJK / full-width / Cyrillic / Greek / accented Latin
fold on macOS, **Hebrew does not**, `LC_ALL=C` folds nothing). The same PR's detection helper was
written as `grep -nP`, which fails on macOS BSD grep (`invalid option -- P`) — inside a rule about
bash portability. Both were caught only because the claim was probed, not read.

Relationship to "Hook Descriptions / Tool Output Fields Must Be Verified": same
verification-before-authoring discipline, extended from "match the artifact you cite" to "probe the
boundary of any claim you generalize, and run any command you tell the reader to run." When a doc
makes a universal claim or ships a runnable snippet, the author — not a downstream reviewer — owns
proving it.

## Tool Exit Codes Must Be Listed in SKILL.md Branch Design (PR #115 lesson)

Any SKILL.md step that calls a shell tool with multiple non-trivial exit codes must
enumerate each exit code as a named outcome. A runbook that only defines PASS/FAIL
collapses distinct states, causing the agent to misroute pending or tool-error conditions.

Example (`gh pr checks`):

```markdown
Exit code semantics:

- **exit 0** — all checks passed → PASS
- **exit 8** — checks still pending/running → PENDING (wait and re-run; do not declare done)
- **exit 1** + structured check data → FAIL (list failing check names)
- **exit 1** + no check data (stderr only) → TOOL ERROR (e.g. auth failure; run `gh auth status`)
```

Before writing a SKILL.md step that calls any CLI tool, check the tool's `--help` or
man page for the full exit code table and add a named branch for each non-zero code.

## Scheduled Skills Must Be Zero-Interaction and Read-Only by Default (Claude Code v2.1.183)

Since Claude Code v2.1.183, deliveries triggered by a **schedule or webhook** are classified as
a **task notification**, not keyboard input. In auto mode a task-notification turn therefore
**cannot approve a pending action and cannot set the session title**. A scheduled skill that
relies on an interactive `approve`/`confirm` step will silently stall (the prompt is never
answerable) or, worse, proceed past an unanswered gate.

Any skill that can be invoked by the scheduler (`.runtime/schedules.json` `skill:` jobs, run via
the ACP Gateway) or by a webhook MUST be authored so that:

1. **Read-only by default.** The default code path performs only reads/analysis and produces a
   report. No mutation happens unless explicitly requested.
2. **Writes are opt-in per task.** Any write — MCP `send`/`post`/`create`/`update`/`delete`,
   file writes, `git push`, `gh pr create`, journal append — runs only when the task definition
   (or the prompt that invoked the skill) explicitly asks for it. Gate writes behind an explicit
   flag/parameter, never behind an interactive confirmation.
3. **No interactive confirmation steps.** Do not use `AskUserQuestion`, `click.confirm`, or any
   "wait for the user to approve" pattern in a scheduled path — there is no one to answer.
4. **Report is the fallback.** When in doubt, the skill emits its findings as a report (log /
   digest file / handover) and stops, rather than taking an irreversible action unattended.

**Primary applicable skill in this repo**: `skills/nightly-agent/SKILL.md`. It runs at 03:00
and can auto-commit / push / `gh pr create`. Note the scope split: the contract above governs the
**skill / agent-invoked path** (ACP Gateway `skill:`/`claude:` job, webhook, auto mode). Its
currently-documented scheduler entry is a **`command` job** — a plain non-interactive subprocess
(`python -m tasks.nightly_agent run`), which is not an agent turn and side-steps the approval
mechanism by design (its safety comes from being non-interactive plus a failing→passing test
gate). The SKILL.md must still state the four rules above so that an unattended **agent-invoked**
run cannot perform unrequested writes.

**Nested `.claude/skills` naming collisions**: since v2.1.178 a nested `.claude/skills`
directory auto-loads when you work in that subtree, and a name that collides with a top-level
skill is surfaced as `<dir>:<name>` (both coexist). When authoring a `description` (the trigger
field), keep trigger keywords distinct enough that a nested-skill collision does not steal or
duplicate the intended trigger.

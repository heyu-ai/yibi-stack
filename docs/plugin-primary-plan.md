# Plugin-Primary Delivery — Implementation Plan (issue #222)

Decision and rationale: [ADR-0004](adr/0004-plugin-primary-packaging.md).
This document is the execution plan only.

**Shape:** 5 PRs, each independently shippable and independently revertable. Phase 0 carries no
architecture dependency and lands first. Phase 1 is a deliberate low-risk canary that proves the
packaging skeleton before anything valuable moves.

| Phase | PR | Scope | Risk | Blocked by |
|---|---|---|---|---|
| 0 | Gap B + housekeeping | locator fix, broken symlink, marketplace drift | low | — |
| 1 | Packaging skeleton (canary) | pyproject, dep purge, `portman` | low | — |
| 2 | mycelium → `mycelium` | 4 of 6 skills | medium | 1 |
| 3 | pr_orchestrator → `pr-orchestrator` | 6 of 6 skills | medium | 1 |
| 4 | Cleanup + honest tracks | delete SKILL_REPO layer, README, scope | low | 2, 3 |

Phases 2 and 3 are independent of each other and may run in parallel once 1 lands.

---

## Phase 0 — Gap B and housekeeping

No dependency on the Gap A ruling. Fixes real, currently-broken behavior.

### 0.1 spectra-amplifier resource locator

`plugins/sdd/skills/spectra-amplifier/SKILL.md:86,757` is dead code:
`SDD_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/sdd}"`. The variable is never set in skill bash, so it
always falls back to a host-nonexistent repo-relative path.

Replace with an ordered chain, **each candidate gated on a capability check** — the presence of
the file actually needed, not mere directory existence. This is the lesson already encoded in
`bootstrap.sh:33` (rule 11/18, PR #215): a directory-existence gate lets a wrong root pass
silently.

Resolution order:

1. `$CLAUDE_PLUGIN_ROOT` — kept first so the skill self-heals if Claude Code ever sets it.
2. The **active** version from `~/.claude/plugins/installed_plugins.json` — authoritative for
   which version is live. Multiple versions legitimately coexist in the cache
   (sdd has 1.2.5 / 1.3.1 / 1.6.0), so this must not guess.
3. `plugins/sdd` — repo-relative, for developing inside the yibi-stack checkout.

Fail loud with the install command if all candidates miss.

> **Do not** version-sort the cache dir with a glob. `cache/yibi-stack/sdd/*/` sorts lexically,
> where `1.10.0 < 1.9.0` — a latent wrong-version bug. `installed_plugins.json` is the single
> source of truth for the active version; read it. Per
> `.claude/rules/13-bash-anti-patterns.md`, a single-line `python3 -c` is the accepted form for
> JSON reads in SKILL.md (precedent: 4 existing SKILL.md files), and `ls | head -1` is banned.

**Chicken-and-egg constraint:** the locator cannot be extracted into a shipped script, because
locating that script is the very problem. It must stay inline bash. Keep it to one resolver block,
defined once and reused at both call sites (:86 and :757).

### 0.2 The broken `spectra-amplifier` symlink — local cruft, **no repo change**

`~/.claude/skills/spectra-amplifier` → `yibi-stack/skills/spectra-amplifier`, a target that no
longer exists (dated May 26, predating the skill's migration into `plugins/sdd/skills/`).

**The obvious fix is wrong.** Adding `skills/spectra-amplifier -> ../plugins/sdd/skills/spectra-amplifier`
looks right by analogy with its siblings, but measurement says otherwise:

| sdd skill | scope | `skills/` symlink? |
|---|---|---|
| event-storming, problem-frames, qa-test-design | `global` | yes |
| **figma-design-sync, spectra-amplifier** | `project` | **no** |

The absence is **consistent and deliberate**: the two `scope: project` sdd skills are intentionally
not symlinked. And the sdd plugin already ships spectra-amplifier — verified at
`~/.claude/plugins/cache/yibi-stack/sdd/1.6.0/skills/spectra-amplifier`. Adding the symlink would
**double-register** the skill (once from the plugin, once from `~/.claude/skills`).

So there is nothing to fix in the repo. The stale symlink is **local machine cruft** from before
the migration, and no repo change can remove a symlink on a user's machine. Fix it locally and
move on:

```bash
rm ~/.claude/skills/spectra-amplifier   # broken symlink; skill now ships via the sdd plugin
```

Recorded here because the issue listed it under 附帶發現 and the intuitive fix is actively harmful.

### 0.3 marketplace / README drift

`plugins/writing/` has both `plugin.json` and `package.json` at v1.7.0 but is **absent from
`.claude-plugin/marketplace.json`** (which lists 7 plugins). README instructs
`claude plugin install writing@yibi-stack` at 6 places (`:94, :104, :153, :238, :248, :297`) — a
command that cannot resolve. Confirmed downstream: `writing` is in neither the plugin cache nor
`installed_plugins.json`.

Add `writing` to `marketplace.json`. (Removing it from README is the alternative, but the plugin
is complete — `plugin.json` v1.8.0 + a working `detect-ai-slop` skill — and is currently reachable
only via the full-install track while being advertised on the plugin-only track.)

While here: `3rd-tools`'s marketplace description claimed "AI slop detection", but `detect-ai-slop`
lives in `writing` and exists nowhere else. `3rd-tools` actually ships agy / codex /
verify-gemini-models. Description corrected to match reality — same doc-vs-code drift class as the
`writing` omission, found by verifying the claim instead of copying it forward.

### 0.4 ~~Remove checked-in `__pycache__`~~ — **not a real problem**

Investigated and dropped. `plugins/sdd/scripts/__pycache__/` and
`plugins/3rd-tools/skills/verify-gemini-models/.venv/` are both **untracked and already
gitignored** (`.gitignore:2`, `:140`); `git ls-files plugins/sdd/scripts/` returns only the 4
real source files. They are local build noise, not committed artifacts.

Kept as a struck-through entry deliberately: an early draft of this plan asserted they were
committed, and that claim is wrong. `[tool.hatch.build.targets.wheel].packages = ["tasks"]`
in Phase 1 remains the correct guard for wheel scope regardless.

### Phase 0 verification

- Simulate a host project: from a directory that is **not** the yibi-stack checkout, run the
  resolver block and confirm it resolves to the cache and finds `check_spec_coverage.py`.
- Mutation-test the capability gate: point the chain at a directory lacking the script and confirm
  it fails loud rather than proceeding. Per `.claude/rules/09-test-conventions.md`, a guard that no
  test drives is zero-coverage; verify the gate by breaking it, not by reading it.
- Confirm `spectra-amplifier` symlink resolves after `make install`.

---

## Phase 1 — Packaging skeleton (canary: `local_port_manager`)

`local_port_manager` is the canary by design: 443 LOC, zero cross-module imports, `click` +
`pydantic` only, no subprocess, and **already home-anchored** at `~/.agents/ports.json` with
injectable paths throughout. It exercises the full packaging path while risking the least.

### 1.1 pyproject

```toml
[project]
name = "yibi-stack"        # was "ainization-skill" — stale fork identity
dependencies = ["click>=8.1", "pydantic>=2.0"]

[project.optional-dependencies]
tokens = ["tiktoken>=0.7"]   # mycelium token budgeting; degrades to len/4 without it

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project.scripts]
portman = "tasks.local_port_manager.cli:cli"

[tool.hatch.build.targets.wheel]
packages = ["tasks"]         # excludes scripts/, plugins/, committed .venv trees
```

**Dependency purge — drop 9 with zero imports:** playwright, python-dotenv, pikepdf, cryptography,
tabula-py, pillow, pytesseract, markdownify. This removes a Java runtime requirement (tabula-py)
and a browser download (playwright) from every `uv sync`.

**`scripts/` is the blocker for the rest.** anthropic, sqlalchemy, psycopg2-binary, requests, and
pdfplumber are used *only* by `scripts/` — a personal ledger toolkit hardcoded to
`localhost:5435/ledgerone`. It must not ship in a public wheel (`packages = ["tasks"]` handles
that), but it still needs its deps for local use. Move them to
`[project.optional-dependencies].ledger`, and **add `pandas` explicitly**: `scripts/compare_billing.py:10`
imports it directly while it is currently satisfied only as a tabula-py transitive — dropping
tabula-py without declaring pandas silently breaks those scripts.

`tiktoken` is used at `tasks/mycelium/lessons_service.py:678` but declared nowhere and absent from
`uv.lock`. It already has an `ImportError` fallback, so it belongs in an extra, not in core.

Regenerate `uv.lock` after the rename (its root package still reads `ainization-skill`).

### 1.2 Wire the canary

- Add the `portman` entry point.
- Rewrite `plugins/util/skills/local-port-manager/SKILL.md:19-22` — delete the config.json resolver
  and `cd "$SKILL_REPO"`; call `portman ...` at all 9 sites.
- Add a fail-loud preflight: `command -v portman` → if absent, print the `uv tool install`
  command and stop.
- Move `service.py:31-46` `BOOTSTRAP_ENTRIES` (hardcodes personal projects `yibi-mvp`,
  `voice-lab`, `coachly`, `coaching365`) out of a to-be-published tool — into config, or drop.

### Phase 1 verification (the decision gate of ADR-0004)

1. `uv build` produces a wheel; inspect it contains `tasks/` and **not** `scripts/` or any `.venv`.
2. On a clean path, `uv tool install git+https://github.com/heyu-ai/yibi-stack` → `portman --help`
   works with no clone present.
3. `make ci` green (full `--all-files`, per CLAUDE.md — not `--files`).
4. Existing 307 LOC of LPM tests still pass unchanged (import path is untouched).

**If step 2 fails on a clean machine, stop and revisit ADR-0004 before Phase 2.**

---

## Phase 2 — mycelium

Covers 4 of 6 skills: `growth/mycelium`, `growth/learn`, `pr-flow/pr-control-log`,
`pr-flow/pr-retrospective`.

- Add `mycelium = "tasks.mycelium.cli:cli"`. **The import path does not change** — all 26 test
  modules and the 12 hardcoded `python -m tasks.mycelium` string literals
  (`insight_hook.py:202`, `recap_hook.py:212`, `cli.py:86-88,125,160`, `account.py:52`,
  `distill_service.py:10`, `insight_hook.py:32`, `recap_hook.py:28`) keep working. Those strings
  should still be rewritten to `mycelium ...` for correctness in generated hook commands, but that
  is cosmetic, not blocking.
- Rewrite the 4 SKILL.md files to call `mycelium ...` directly.
- **Delete both `bootstrap.sh` scripts** and their SKILL.md call sites. This is the end state that
  PRs #215 and #221 anticipated — those were correct local optima under the old architecture.
- Add a version-capability gate (see Cross-cutting below).
- `semantic_index.py:68` loads the `sqlite_vec` SQLite extension at runtime with an FTS5 fallback
  (`:64-65`). Confirm that fallback holds under a pip-installed interpreter — it is not a Python
  import and won't be carried by the wheel.
- `.claude/hooks/{pre-compact-handover,post-compact-handover-back}.sh` import `tasks.mycelium`
  in-process after `cd "$REPO_ROOT"`. These are dev-only, live outside all plugin dirs, and never
  shipped — leave them checkout-bound. Note it explicitly in the PR so it isn't mistaken for an
  oversight.

---

## Phase 3 — pr_orchestrator

Covers the 6th skill: `pr-flow/pr-cycle-fast` (15 call sites).

- **Re-anchor state.** `tasks/_paths.py`'s `PROJECT_ROOT = Path(__file__).resolve().parents[1]` →
  `RUNTIME_DIR` resolves into site-packages under pip install. Three consumers:
  `config.py:12,17-19`, `log.py:9,11`, `dispatcher.py:7,10`. Move to `~/.agents/pr_orchestrator/`
  — the pattern `local_port_manager` already uses and which `config.py:18`'s
  `_ARCHIVE_BASE = Path.home()/".claude"/"pr_orchestrator"` already half-adopts.
- Add `pr-orchestrator = "tasks.pr_orchestrator.cli:cli"`.
- **`dispatcher.py` (77 LOC)** emits Claude-Code subagent spawn manifests containing
  `uv run python -m tasks.pr_orchestrator transition ...` (`:39, :68-71`). Rewrite to the console
  script.
- Rewrite `plugins/pr-flow/skills/pr-cycle-fast/SKILL.md` — all 15 `uv run --directory` sites.
- **Preserve `--repo-root` threading.** `cli.py:177,197` and the tests PROR-ST-030/032/033/034/036/040
  pin `cwd == repo_root` for every git/gh call. Under a console script, cwd is the user's shell —
  a *different* wrong-cwd hazard than the `uv run --directory` one those tests were written for.
  Re-verify by mutation: break the `cwd=` pass-through and confirm a test fails.

---

## Phase 4 — Cleanup and honest tracks

- Delete the `~/.agents/config.json` `skill_repo` / `skill_repos` **readers**:
  `tasks/mycelium/models.py:179-225` (schema + `resolve_skill_repo()`),
  `commands/scripts/handover-read.sh:7`,
  `plugins/3rd-tools/skills/verify-gemini-models/scripts/check_models.py:21`.
  Then retire the writer, `scripts/register_skill_repo.py` (`Makefile:115`).
  Sequence readers-before-writer so no intermediate commit leaves a reader without its key.
- `scope: global` on the 6 skills is now **true**. Verify against README's definition rather than
  assuming.
- README: make the two tracks honest. Plugin-only now works for all 6 skills **given
  `uv tool install`** — document that prerequisite at the point of use, not only in README.
- Consider a `yibi-plugin-root <plugin>` console script to replace Phase 0's inline locator. Now
  viable since the CLI is installed anyway, but it would couple sdd (today pure markdown + a
  `uv run python` script) to the Python install. Evaluate; do not assume.

---

## Cross-cutting concerns

### Version skew is the new failure mode

Path skew becomes version skew: an installed CLI can lag the plugin's SKILL.md. Every migrated
skill needs a preflight that fails loud, in this shape:

```
command -v mycelium  → absent? print `uv tool install git+https://github.com/heyu-ai/yibi-stack`, stop
mycelium --version   → below the minimum this SKILL.md needs? print `uv tool upgrade`, stop
```

This requires the CLI to **expose a version**, which today's `pyproject` version (1.8.0, currently
release-tag-driven) does not surface per-command. Add `--version` in Phase 1 alongside `portman`,
so the pattern is proven on the canary rather than retrofitted across 6 skills.

This is the single most important cross-cutting item: without it, Phase 2/3 trade a loud
path failure for a *silent* behavioral mismatch — strictly worse than today.

### Single-source-of-truth exposure

Per `.claude/rules/18-single-source-of-truth.md`, each phase creates a doc/code contract that
drifts silently:

- SKILL.md's documented minimum version vs. the CLI's actual `--version` → the preflight gate *is*
  the regression test; assert it.
- README's install instructions vs. `marketplace.json` → already drifted once (`writing`). After
  Phase 0, add a check that every plugin README advertises is present in `marketplace.json`.
- `pyproject` version vs. `uv.lock` → bump both in the same commit (existing CLAUDE.md rule).

### Search hygiene

`.claude/worktrees/` holds ~4 stale copies of every file touched here. Repo-wide greps will be ~5×
noisy and can manufacture false "many call sites" impressions. Scope every grep to the main
checkout.

### Out of scope (worth separate issues)

- **`scripts/` is a separate application.** A personal ledger toolkit (HSBC import, billing
  compare, Claude-based categorization) hardcoded to one machine's Postgres, sharing this repo by
  accident of the fork. It holds 5 of the remaining deps. It should probably leave this repo
  entirely; Phase 1 only quarantines it behind an extra.
- **`harness-eval` is not plugin-installable** (README:96) and stays checkout-only.

---
id: "0004"
title: "Plugin-Primary Delivery — Ship tasks/* as an Installable CLI Distribution"
status: accepted
date: 2026-07-14
deciders: [howie]
related:
  issue: 222
  prs:
    - number: 215
      note: "pr-retrospective bootstrap self-locate (merged) — superseded by this ADR's end state"
    - number: 221
      note: "pr-control-log same fix (open) — superseded by this ADR's end state"
---

## Context

This project is delivered **primarily as Claude Code plugins**. `make install` (git clone +
symlink into `~/.claude/skills`) is a local development convenience, not the shipping path.

Issue #222 recorded two structural gaps blocking that premise. Both were re-verified against the
repo before this decision; the findings below are measured, not assumed.

### Gap A — `tasks/*` never ships

Every `.claude-plugin/marketplace.json` entry carries only a `source` path
(`"./plugins/pr-flow"`, marketplace.json:16-70). There is no file-list, include, or exclude
mechanism, so a plugin's payload is exactly its own directory. `tasks/` sits at repo root beside
`plugins/` — outside every plugin — so it can never be reached. Verified: the installed cache
`~/.claude/plugins/cache/yibi-stack/pr-flow/1.6.0/` contains `commands/ skills/ package.json
README.md` and no `tasks/`.

Six skills across three plugins depend on it, all currently marked `scope: global`:

| plugin | skill | module |
|---|---|---|
| pr-flow | pr-cycle-fast | `tasks.pr_orchestrator` |
| pr-flow | pr-control-log | `tasks.mycelium` |
| pr-flow | pr-retrospective | `tasks.mycelium` |
| growth | mycelium | `tasks.mycelium` |
| growth | learn | `tasks.mycelium` |
| util | local-port-manager | `tasks.local_port_manager` |

They resolve a checkout via `~/.agents/config.json`'s `skill_repo` key, then
`uv run --directory "$SKILL_REPO" python -m tasks.X`. That key only exists after clone +
`make install` — directly contradicting plugin-only installation. The failure is already
documented in-repo at `plugins/pr-flow/skills/pr-control-log/SKILL.md:232`.

`.claude/hooks/pre-compact-handover.sh` and `post-compact-handover-back.sh` additionally
import `tasks.mycelium` in-process. They live outside all plugin dirs, so they are a second
unshipped surface with the same assumption.

### Gap B — plugin-shipped resources are unlocatable

`CLAUDE_PLUGIN_ROOT` is set in **hook** context but **not** in skill bash (the agent runs skill
bash via the Bash tool, which carries no plugin context). This is an undocumented platform
limitation, empirically recorded at `plugins/pr-flow/skills/pr-retrospective/SKILL.md:48`.

`plugins/sdd/skills/spectra-amplifier/SKILL.md:86,757` therefore contains permanently dead code:

```bash
SDD_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/sdd}"
```

The variable is never set, so it always falls back to `plugins/sdd` — a repo-relative path that
the same SKILL.md section admits does not exist in host projects.

**Gap B is a different bug from Gap A and has a different fix.** The resource *does* ship:
`~/.claude/plugins/cache/yibi-stack/sdd/1.6.0/scripts/check_spec_coverage.py` exists. Nothing is
missing — only the locator is broken. Gap B is therefore fixable with no architecture ruling.

### Findings that revised the issue's framing

Research for this ADR overturned three assumptions in the issue text:

1. **All three modules are extractable, not just mycelium.** `local_port_manager` (443 LOC, zero
   cross-module imports, already home-anchored at `~/.agents/ports.json`, no subprocess) is
   *cleaner* than mycelium. `pr_orchestrator` (1,470 LOC) was expected to be disqualified by
   "operates on a repo", but its target repo is already a fully threaded `--repo-root` parameter
   with tests (PROR-ST-030/032/033/034/036/040) pinning that behavior — the standalone-CLI shape.
   Its only real blocker is 3 × `from .._paths import RUNTIME_DIR` anchoring state to the checkout.
2. **The true dependency set is `click` + `pydantic`.** Of 15 declared runtime deps, **9 have zero
   imports** (playwright, python-dotenv, pikepdf, cryptography, tabula-py, pillow, pytesseract,
   markdownify — stale residue from the ainization-skill fork). The union across all of `tasks/` is
   two pure-Python wheels, plus `tiktoken` which is already optional-with-fallback at
   `tasks/mycelium/lessons_service.py:678`. The remaining declared deps (anthropic, sqlalchemy,
   psycopg2-binary, requests, pdfplumber) are used **only** by `scripts/`, a personal ledger
   toolkit hardcoded to `localhost:5435/ledgerone` that cannot ship to other users anyway.
3. **The repo is PUBLIC**, so `uv tool install git+https://github.com/heyu-ai/yibi-stack` works
   with no PyPI account, no publish pipeline, and no release-artifact workflow. The issue listed
   "no build/publish flow" as an obstacle; the real requirement is a `[build-system]` +
   `[project.scripts]` stanza.

A fourth point removes the issue's largest stated cost: **extraction does not require renaming the
package.** Keeping the `tasks.` import path and merely adding console-script entry points leaves
all 26 test modules and the 12 hardcoded `python -m tasks.mycelium` string literals untouched.

## Decision

**Ship `tasks/*` as a single installable Python distribution exposing multiple console scripts,
installed via `uv tool install git+https://github.com/heyu-ai/yibi-stack`.**

Skills invoke bare commands (`mycelium ...`, `portman ...`, `pr-orchestrator ...`). The entire
`SKILL_REPO` resolution layer — the `~/.agents/config.json` lookup, the `bootstrap.sh` scripts,
and `uv run --directory` — is deleted.

Granularity: **one distribution, multiple entry points** (not three separate packages). One build
config, one install command. Because the dependency set is two pure-Python wheels, a user
installing for mycelium pays effectively nothing for also receiving `portman` and
`pr-orchestrator`.

The package import path stays `tasks.*`. Only `[build-system]`, `[project.scripts]`, the
dependency list, and the wheel's packaging scope change.

### Rejected alternatives

**Vendor `tasks/` into each plugin directory.** Claude Code has no plugin-dependency mechanism, so
`pr-flow` and `growth` both needing mycelium forces either a duplicated copy or a fourth "shared"
plugin that the other three cannot declare a dependency on. Two mycelium copies drifting
independently is precisely the dual-source failure `.claude/rules/18-single-source-of-truth.md`
exists to forbid — and `.claude/hooks/` would still import a third copy from the checkout.

**Status quo + honest labeling** (flip the 6 skills to `scope: project`, drop the plugin-only
promise from README). Lowest cost and zero risk, and it does fix the *dishonesty* — but it
abandons the plugin-primary premise for exactly the skills that carry the most value. Retained as
the fallback if Phase 1 shows packaging is unexpectedly costly.

**Fix Gap B only, defer Gap A.** Not rejected — **absorbed**. Gap B needs no architecture ruling
and ships first, as Phase 0. It is sequencing, not an alternative.

## Consequences

### Positive

- Plugin-only installation becomes true for all 6 skills; `scope: global` becomes accurate rather
  than aspirational.
- ~60 lines of fragile `SKILL_REPO` resolution disappear across 6 SKILL.md files, plus both
  `bootstrap.sh` scripts and their failure modes.
- The `~/.agents/config.json` `skill_repo` / `skill_repos` key loses its readers. Its
  single-shared-key drift hazard (issues #197, #199) stops mattering.
- Dropping 9 dead deps removes a Java runtime requirement (tabula-py) and a browser download
  (playwright) from `uv sync` for every contributor.
- Version skew becomes visible and fixable (`uv tool upgrade`) instead of silently resolving to
  whatever a stale checkout contains.

### Negative / risks

- **Version skew replaces path skew.** A user's installed CLI can lag the plugin's SKILL.md. Every
  skill must gate on a capability/version check and fail loud. This is a *better* failure than
  today's silent wrong-repo resolution, but it is new.
- **`uv tool install` becomes a prerequisite** for those 6 skills. Consistent with the stated
  premise ("mycelium is a tool the user installs separately"), but it must be documented at the
  point of failure, not only in README.
- **`tasks/_paths.RUNTIME_DIR` must die** as a repo-anchored constant
  (`PROJECT_ROOT = Path(__file__).resolve().parents[1]`). Under pip install it resolves into
  site-packages. `local_port_manager` already demonstrates the target pattern
  (`Path.home() / ".agents"`), and `pr_orchestrator`'s archive path already half-adopted it.
- **`scripts/` must be excluded from the wheel**, or the ledger toolkit's heavy deps leak back in.
- **The dev `.claude/hooks/` in-process imports stay checkout-bound.** Acceptable: those hooks are
  developer tooling in this repo, not shipped artifacts.

### Verification gate

Phase 1 is a canary. If `uv tool install git+https://github.com/heyu-ai/yibi-stack` does not
produce a working `portman` on a clean machine path, the decision is revisited before mycelium or
pr_orchestrator move.

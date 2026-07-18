[MODIFIED] Wave D revision: scenarios are grouped by User Story, titled without changing slugs, expanded to GIVEN/WHEN/THEN, and supplied with the four requested concrete examples.

| US | Requirement |
| --- | --- |
| US-001 | Installable yibi-stack CLI distribution |
| US-001 | Package root and test import stability |
| US-001 | Two-track installation documentation |
| US-002 | Checkout-independent skill execution |
| US-002 | Explicit project targeting |
| US-002 | Stable installed hook binary |
| US-002 | Verify-before-unlink migration |

## ADDED Requirements

### Requirement: Installable yibi-stack CLI distribution

[MODIFIED]

The existing `yibi-stack` distribution SHALL remain the sole Python distribution for Phase A. Installing `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"` from a Git tag SHALL install the existing `tasks` package and SHALL expose `mycelium`, `pr-orchestrator`, and `portman` console scripts. The console scripts SHALL resolve to `tasks.mycelium.cli:cli`, `tasks.pr_orchestrator.cli:cli`, and `tasks.local_port_manager.cli:cli`, respectively. The wheel SHALL continue to exclude `tasks/**/tests/**`, and Phase A SHALL NOT create a separate `mycelium` distribution.

#### Scenario: git-install-exposes-all-console-scripts -- Git tag install exposes all CLIs

[MODIFIED]

**GIVEN** an environment with `uv` and Git access, no yibi-stack checkout, and a valid immutable release tag
**WHEN** the environment installs that tag with the Phase A Git install command
**THEN** `mycelium --help`, `pr-orchestrator --help`, and `portman --help` MUST each exit successfully without importing from a checkout

#### Scenario: distribution-retains-existing-package -- Phase A keeps existing distribution

[MODIFIED]

**GIVEN** the Phase A wheel has been built from the recorded release tag
**WHEN** the wheel metadata and contents are inspected
**THEN** the distribution name MUST be `yibi-stack`, the wheel MUST contain `tasks`, the wheel MUST exclude `tasks/**/tests/**`, and no separate `mycelium` distribution MUST be produced

### Requirement: Package root and test import stability

[ADDED] 此 requirement 從既有 Verify-before-unlink migration 的 compatibility invariant 抽出，normative content 未改變。

The `tasks.mycelium` package root and the import paths of the 26 test files identified by issue #222 SHALL remain unchanged throughout the migration.

#### Scenario: test-import-paths-remain-stable -- Package and test imports stay stable

[MODIFIED]

**GIVEN** the issue #222 inventory contains 26 tests importing through `tasks.mycelium`
**WHEN** Phase A packaging and skill migration changes are complete
**THEN** the mycelium tests identified by issue #222 MUST still import through `tasks.mycelium`, and the package MUST remain rooted at `tasks/mycelium`

### Requirement: Two-track installation documentation

[MODIFIED]

The English and Traditional Chinese README install sections SHALL document plugin installation and CLI installation as two separate, complementary tracks. The CLI track and every migrated SKILL.md failure gate SHALL use only `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"`. Phase A documentation SHALL NOT contain a PyPI install command for mycelium or yibi-stack.

#### Scenario: readme-shows-two-track-install -- README explains both install tracks

[MODIFIED]

**GIVEN** the English and Traditional Chinese README install sections have been updated for Phase A
**WHEN** a user reads either README install section
**THEN** the user MUST find the plugin installation track and the exact Git-tag CLI installation track, with their distinct purposes stated

[ADDED]

##### Example: v1.11.0 two-track commands

**GIVEN** a plugin-only user needs `growth`, `pr-flow`, and `util`, and release tag `v1.11.0` exists
**WHEN** the user reads the English or Traditional Chinese install section
**THEN** the section MUST show a plugin command such as `claude plugin install growth@yibi-stack pr-flow@yibi-stack util@yibi-stack` and the CLI string `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"`, with the two purposes stated separately

#### Scenario: pypi-install-is-not-pre-documented -- Phase A does not advertise PyPI

[MODIFIED]

**GIVEN** README and all six migrated SKILL.md files are in the Phase A documentation scope
**WHEN** those files are searched for mycelium or yibi-stack installation commands
**THEN** the supported command MUST be the exact Git-tag command and no PyPI installation command MUST be present

[ADDED]

##### Example: v1.11.0 is the only CLI install form

**GIVEN** the seven documentation files contain `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"`
**WHEN** they are searched for `pip install yibi-stack`, `pip install mycelium`, `uv tool install yibi-stack`, and Git installs without `@v1.11.0`
**THEN** every prohibited search MUST return zero matches and the exact `v1.11.0` Git-tag string MUST remain present

### Requirement: Checkout-independent skill execution

[MODIFIED]

The six skills `pr-cycle-fast`, `pr-control-log`, `pr-retrospective`, `mycelium`, `learn`, and `local-port-manager` SHALL invoke installed console scripts instead of `uv run ... python -m tasks.*`. Each skill SHALL run `command -v mycelium` before its first tasks-backed operation. If that command fails, the skill SHALL print a `[FAIL]` message containing `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"`, SHALL exit non-zero, and SHALL NOT fall back to a checkout.

#### Scenario: missing-mycelium-fails-before-skill-work -- Missing binary blocks all skill work

[MODIFIED]

**GIVEN** any of the six skills starts in an environment whose PATH does not expose `mycelium`
**WHEN** the skill runs `command -v mycelium` before its first tasks-backed operation
**THEN** the skill MUST stop before that operation, print `[FAIL]` plus the exact Git-tag install command, and MUST NOT attempt `SKILL_REPO`, `uv run`, `uvx`, or `python -m tasks.*`

#### Scenario: six-skills-run-without-checkout -- Six skills use installed commands

[MODIFIED]

**GIVEN** the Git-tag distribution is installed, the six skills are visible through the Claude Code plugin cache, and no yibi-stack checkout exists
**WHEN** each of the six skills starts its representative tasks-backed operation
**THEN** `pr-cycle-fast` MUST reach `pr-orchestrator`, `pr-control-log` and `pr-retrospective` MUST reach their `mycelium` command groups, `mycelium` and `learn` MUST reach their installed `mycelium` command groups, and `local-port-manager` MUST reach `portman`

### Requirement: Explicit project targeting

[MODIFIED]

Every project-sensitive `mycelium` invocation in the six migrated skills SHALL pass `--project <slug>`. `pr-cycle-fast` SHALL pass the target checkout through the existing `pr-orchestrator --repo-root <absolute-path>` interface for commands that access the repository. `portman list` SHALL pass `--project <slug>`, and portman subcommands whose current Click interface represents project as a positional operand SHALL pass that operand explicitly. Global commands that do not expose project scope SHALL NOT receive an invented project option.

#### Scenario: mycelium-commands-receive-project -- Mycelium receives explicit project

[MODIFIED]

**GIVEN** the CLI process cwd is unrelated to the intended target repository
**WHEN** `pr-control-log`, `pr-retrospective`, `mycelium`, or `learn` invokes a project-sensitive installed mycelium command
**THEN** the invocation MUST contain `--project` with the intended project slug and MUST NOT infer that slug from the CLI process cwd

#### Scenario: pr-orchestrator-receives-repo-root -- Orchestrator receives repo root

[MODIFIED]

**GIVEN** `pr-cycle-fast` has resolved an intended checkout whose absolute path differs from the CLI process cwd
**WHEN** it invokes an installed pr-orchestrator command that reads Git or GitHub state
**THEN** the invocation MUST pass the intended checkout as `--repo-root` and MUST NOT infer the checkout from the CLI process cwd

#### Scenario: portman-receives-project -- Portman receives explicit project

[MODIFIED]

**GIVEN** `local-port-manager` has an intended project and the CLI process cwd may name another repository
**WHEN** it invokes a project-scoped portman operation
**THEN** the invocation MUST supply the intended project through `--project` or the command's explicit positional project operand

### Requirement: Stable installed hook binary

[MODIFIED]

Auto-handover hook registration SHALL resolve `mycelium` from PATH at install-hooks time with `shutil.which` or an equivalent `command -v`, normalize the result to an absolute path, and write commands rooted at exactly that path into `~/.claude/settings.json`. The written path SHALL remain fixed after registration. If resolution fails, registration SHALL fail loud with `[FAIL]` and SHALL NOT write an unresolved hook command. The installed CLI SHALL expose hook commands that preserve the existing PreCompact and SessionStart stdin, matcher, system-message, exit-status, and best-effort metrics semantics. Checkout hook wrappers SHALL resolve `mycelium` with `command -v mycelium` when invoked, SHALL fail loud with `[FAIL]` when absent, and SHALL NOT import `tasks.mycelium` in-process. Hook commands SHALL NOT use `uvx`.

#### Scenario: settings-hooks-use-stable-binary -- Settings keep resolved absolute path

[MODIFIED]

**GIVEN** an empty settings file and a fake `mycelium` binary on PATH in a temporary directory
**WHEN** auto-handover hooks are installed
**THEN** both generated hook commands MUST start with an absolute path to the `mycelium` binary that equals the path resolved at install time, MUST name the appropriate installed hook subcommand, and MUST NOT contain a checkout path, `python -m tasks.mycelium`, or `uvx`

#### Scenario: checkout-hook-wrappers-avoid-source-imports -- Wrappers delegate without source imports

[MODIFIED]

**GIVEN** a checkout compatibility hook receives a supported Claude hook payload and a fake `mycelium` binary is on PATH in a temporary directory
**WHEN** either compatibility wrapper handles the payload
**THEN** it MUST delegate to the binary path returned by `command -v mycelium`, preserve the existing observable hook result, and MUST NOT execute an in-process import from `tasks.mycelium`

### Requirement: Verify-before-unlink migration

[MODIFIED]

The six real-checkout skill symlinks and their consumer-side `SKILL_REPO` or `resolve-skill-repo` compatibility logic SHALL remain present until a clean environment with no yibi-stack checkout passes the Git install, console-script, six-skill invocation, explicit-target, and hook checks. A failed or incomplete verification SHALL block cleanup. After the verification passes, the six symlinks and only the resolver logic made obsolete in those six consumers SHALL be removed.

#### Scenario: failed-verification-retains-links -- Failed verification preserves rollback lane

[MODIFIED]

**GIVEN** the six real-checkout skill symlinks and their resolver compatibility lane are still present
**WHEN** any clean-install, CLI, skill-path, explicit-target, or hook verification fails or has not run
**THEN** all six real-checkout skill symlinks and their resolver compatibility lane MUST remain available

[ADDED]

##### Example: v1.11.0 help failure blocks cleanup

**GIVEN** tag `v1.11.0` is installed under clean HOME `/tmp/mycli-clean`, `pr-orchestrator --help` exits `1`, and `/tmp/yibi-stack/skills/pr-cycle-fast` through `/tmp/yibi-stack/skills/local-port-manager` still name the six compatibility symlinks
**WHEN** the verify-before-unlink gate evaluates the recorded CLI results
**THEN** all six symlink paths MUST still exist, resolver strings `SKILL_REPO` and `resolve-skill-repo` MUST remain in their six consumers, and cleanup MUST report a blocked result

#### Scenario: successful-verification-allows-cleanup -- Passing verification permits cleanup

[MODIFIED]

**GIVEN** the six real-checkout skill symlinks and resolver compatibility lane are still present
**WHEN** every required end-to-end verification passes against a recorded Git tag
**THEN** the six real-checkout skill symlinks and obsolete resolver logic in the six consumers MUST be removed without changing the package root or test import paths

[ADDED]

##### Example: v1.11.0 evidence permits six-path cleanup

**GIVEN** tag `v1.11.0` is recorded and MYCLI-ST-001..006, MYCLI-DT-001..004, SMK-001, SMK-002, and SMK-003 all have PASS evidence
**WHEN** cleanup removes `/tmp/yibi-stack/skills/pr-cycle-fast`, `/tmp/yibi-stack/skills/pr-control-log`, `/tmp/yibi-stack/skills/pr-retrospective`, `/tmp/yibi-stack/skills/mycelium`, `/tmp/yibi-stack/skills/learn`, and `/tmp/yibi-stack/skills/local-port-manager`
**THEN** those six paths MUST be absent, the six consumers MUST contain no obsolete resolver string, `tasks/mycelium` MUST still exist, and all 26 tests MUST still import `tasks.mycelium`

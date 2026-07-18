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

The existing `yibi-stack` distribution SHALL remain the sole Python distribution for Phase A. Apply/verification SHALL choose and record one concrete immutable release tag. Installing the exact tag-pinned Git command formed with that recorded release tag SHALL install the existing `tasks` package and SHALL expose `mycelium`, `pr-orchestrator`, and `portman` console scripts. The console scripts SHALL resolve to `tasks.mycelium.cli:cli`, `tasks.pr_orchestrator.cli:cli`, and `tasks.local_port_manager.cli:cli`, respectively. The wheel SHALL continue to exclude `tasks/**/tests/**`, and Phase A SHALL NOT create a separate `mycelium` distribution.

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

The English and Traditional Chinese README install sections SHALL document plugin installation and CLI installation as two separate, complementary tracks. The CLI track and every migrated SKILL.md failure gate SHALL use the same exact tag-pinned Git command containing the recorded release tag. All seven documentation files—the README and six migrated SKILL.md files—SHALL carry that identical recorded-tag command. Phase A documentation SHALL NOT contain a PyPI install command for mycelium or yibi-stack.

#### Scenario: readme-shows-two-track-install -- README explains both install tracks

[MODIFIED]

**GIVEN** the English and Traditional Chinese README install sections have been updated for Phase A
**WHEN** a user reads either README install section
**THEN** the user MUST find the plugin installation track and the exact Git-tag CLI installation track, with their distinct purposes stated

[MODIFIED]

##### Example: illustrative v1.11.0 two-track commands

**GIVEN** a plugin-only user needs `growth`, `pr-flow`, and `util`, and the illustrative recorded release tag is `v1.11.0`
**WHEN** the user reads the English or Traditional Chinese install section
**THEN** the section MUST show a plugin command such as `claude plugin install growth@yibi-stack pr-flow@yibi-stack util@yibi-stack` and the CLI string `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"`, with the two purposes stated separately

#### Scenario: pypi-install-is-not-pre-documented -- Phase A does not advertise PyPI

[MODIFIED]

**GIVEN** README and all six migrated SKILL.md files are in the Phase A documentation scope
**WHEN** those files are searched for mycelium or yibi-stack installation commands
**THEN** the supported command MUST be the exact Git-tag command and no PyPI installation command MUST be present

[MODIFIED]

##### Example: illustrative v1.11.0 consistency check

**GIVEN** the illustrative recorded release tag is `v1.11.0` and the seven documentation files contain `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"`
**WHEN** they are searched for `pip install yibi-stack`, `pip install mycelium`, `uv tool install yibi-stack`, and Git installs that omit the recorded release tag, and their supported install strings are compared
**THEN** every prohibited search MUST return zero matches and all seven supported install strings MUST be identical to the command formed with the recorded release tag

### Requirement: Checkout-independent skill execution

[MODIFIED]

The six skills `pr-cycle-fast`, `pr-control-log`, `pr-retrospective`, `mycelium`, `learn`, and `local-port-manager` SHALL invoke installed console scripts instead of `uv run ... python -m tasks.*`. Before its first tasks-backed operation, each skill SHALL run `command -v` for every console script it actually invokes: `pr-cycle-fast` SHALL preflight `pr-orchestrator` and SHALL also preflight `mycelium` if the selected path invokes it; `pr-control-log`, `pr-retrospective`, `mycelium`, and `learn` SHALL preflight `mycelium`; `local-port-manager` SHALL preflight `portman`. If any required preflight fails, the skill SHALL print a `[FAIL]` message containing the exact tag-pinned Git command formed with the recorded release tag, SHALL exit non-zero, and SHALL NOT fall back to a checkout.

#### Scenario: missing-mycelium-fails-before-skill-work -- Missing required binary blocks skill work

[MODIFIED]

**GIVEN** any of the six skills starts in an environment whose PATH omits a console script that the selected skill path will actually invoke, even if another distribution console script is present
**WHEN** the skill preflights every console script required by that path before its first tasks-backed operation
**THEN** the skill MUST stop before that operation, identify the missing script, print `[FAIL]` plus the exact recorded-tag install command, and MUST NOT attempt `SKILL_REPO`, `uv run`, `uvx`, or `python -m tasks.*`

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

Auto-handover hook registration SHALL resolve `mycelium` from PATH at install-hooks time with `shutil.which` or an equivalent `command -v`, normalize the result to an absolute path, and write commands rooted at exactly that path into `~/.claude/settings.json`. The written command SHALL shell-quote the resolved binary path with `shlex.quote` or an equivalent POSIX-safe encoding, and parsing the command as shell words SHALL yield that absolute path as the first argument. The written path SHALL remain fixed after registration. If resolution fails, registration SHALL fail loud with `[FAIL]` and SHALL NOT write an unresolved hook command. The installed CLI SHALL expose hook commands that preserve the existing PreCompact and SessionStart stdin, matcher, system-message, exit-status, and best-effort metrics semantics. Checkout hook wrappers SHALL resolve `mycelium` with `command -v mycelium` when invoked, SHALL fail loud with `[FAIL]` when absent, and SHALL NOT import `tasks.mycelium` in-process. Hook commands SHALL NOT use `uvx`.

#### Scenario: settings-hooks-use-stable-binary -- Settings keep resolved absolute path

[MODIFIED]

**GIVEN** an empty settings file and a fake `mycelium` binary on PATH in a temporary directory whose name contains a space
**WHEN** auto-handover hooks are installed
**THEN** both generated hook commands MUST shell-quote the resolved absolute path, their first shell-parsed argument MUST equal the path resolved at install time, they MUST name the appropriate installed hook subcommand, and they MUST NOT contain a checkout path, `python -m tasks.mycelium`, or `uvx`

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

[MODIFIED]

##### Example: illustrative v1.11.0 help failure blocks cleanup

**GIVEN** the illustrative recorded tag `v1.11.0` is installed under clean HOME `/tmp/mycli-clean`, `pr-orchestrator --help` exits `1`, and `/tmp/yibi-stack/skills/pr-cycle-fast` through `/tmp/yibi-stack/skills/local-port-manager` still name the six compatibility symlinks
**WHEN** the verify-before-unlink gate evaluates the recorded CLI results
**THEN** all six symlink paths MUST still exist, resolver strings `SKILL_REPO` and `resolve-skill-repo` MUST remain in their six consumers, and cleanup MUST report a blocked result

#### Scenario: successful-verification-allows-cleanup -- Passing verification permits cleanup

[MODIFIED]

**GIVEN** the six real-checkout skill symlinks and resolver compatibility lane are still present
**WHEN** every required end-to-end verification passes against a recorded Git tag
**THEN** the six real-checkout skill symlinks and obsolete resolver logic in the six consumers MUST be removed without changing the package root or test import paths

[MODIFIED]

##### Example: illustrative v1.11.0 evidence permits six-path cleanup

**GIVEN** the illustrative tag `v1.11.0` is recorded and MYCLI-ST-001..006, MYCLI-DT-001..004, SMK-001, SMK-002, and SMK-003 all have PASS evidence
**WHEN** cleanup removes `/tmp/yibi-stack/skills/pr-cycle-fast`, `/tmp/yibi-stack/skills/pr-control-log`, `/tmp/yibi-stack/skills/pr-retrospective`, `/tmp/yibi-stack/skills/mycelium`, `/tmp/yibi-stack/skills/learn`, and `/tmp/yibi-stack/skills/local-port-manager`
**THEN** those six paths MUST be absent, the six consumers MUST contain no obsolete resolver string, `tasks/mycelium` MUST still exist, and all 26 tests MUST still import `tasks.mycelium`

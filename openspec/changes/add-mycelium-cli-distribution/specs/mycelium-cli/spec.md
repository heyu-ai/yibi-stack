## ADDED Requirements

### Requirement: Installable yibi-stack CLI distribution

The existing `yibi-stack` distribution SHALL remain the sole Python distribution for Phase A. Installing `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"` from a Git tag SHALL install the existing `tasks` package and SHALL expose `mycelium`, `pr-orchestrator`, and `portman` console scripts. The console scripts SHALL resolve to `tasks.mycelium.cli:cli`, `tasks.pr_orchestrator.cli:cli`, and `tasks.local_port_manager.cli:cli`, respectively. The wheel SHALL continue to exclude `tasks/**/tests/**`, and Phase A SHALL NOT create a separate `mycelium` distribution.

#### Scenario: git-install-exposes-all-console-scripts

- **WHEN** an environment with no yibi-stack checkout installs a valid release tag with the Phase A Git install command
- **THEN** `mycelium --help`, `pr-orchestrator --help`, and `portman --help` MUST each exit successfully without importing from a checkout

#### Scenario: distribution-retains-existing-package

- **WHEN** the Phase A wheel metadata and contents are inspected
- **THEN** the distribution name MUST be `yibi-stack`, the wheel MUST contain `tasks`, the wheel MUST exclude `tasks/**/tests/**`, and no separate `mycelium` distribution MUST be produced

### Requirement: Checkout-independent skill execution

The six skills `pr-cycle-fast`, `pr-control-log`, `pr-retrospective`, `mycelium`, `learn`, and `local-port-manager` SHALL invoke installed console scripts instead of `uv run ... python -m tasks.*`. Each skill SHALL run `command -v mycelium` before its first tasks-backed operation. If that command fails, the skill SHALL print a `[FAIL]` message containing `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"`, SHALL exit non-zero, and SHALL NOT fall back to a checkout.

#### Scenario: missing-mycelium-fails-before-skill-work

- **WHEN** any of the six skills starts in an environment where `command -v mycelium` fails
- **THEN** the skill MUST stop before its tasks-backed operation, print `[FAIL]` plus the exact Git-tag install command, and MUST NOT attempt `SKILL_REPO`, `uv run`, `uvx`, or `python -m tasks.*`

#### Scenario: six-skills-run-without-checkout

- **WHEN** the Git-tag distribution is installed and no yibi-stack checkout exists
- **THEN** `pr-cycle-fast` MUST reach `pr-orchestrator`, `pr-control-log` and `pr-retrospective` MUST reach their `mycelium` command groups, `mycelium` and `learn` MUST reach their installed `mycelium` command groups, and `local-port-manager` MUST reach `portman`

### Requirement: Explicit project targeting

Every project-sensitive `mycelium` invocation in the six migrated skills SHALL pass `--project <slug>`. `pr-cycle-fast` SHALL pass the target checkout through the existing `pr-orchestrator --repo-root <absolute-path>` interface for commands that access the repository. `portman list` SHALL pass `--project <slug>`, and portman subcommands whose current Click interface represents project as a positional operand SHALL pass that operand explicitly. Global commands that do not expose project scope SHALL NOT receive an invented project option.

#### Scenario: mycelium-commands-receive-project

- **WHEN** `pr-control-log`, `pr-retrospective`, `mycelium`, or `learn` invokes a project-sensitive installed mycelium command from a cwd unrelated to the target repository
- **THEN** the invocation MUST contain `--project` with the intended project slug and MUST NOT infer that slug from the CLI process cwd

#### Scenario: pr-orchestrator-receives-repo-root

- **WHEN** `pr-cycle-fast` invokes an installed pr-orchestrator command that reads Git or GitHub state
- **THEN** the invocation MUST pass the intended checkout as `--repo-root` and MUST NOT infer the checkout from the CLI process cwd

#### Scenario: portman-receives-project

- **WHEN** `local-port-manager` invokes a project-scoped portman operation
- **THEN** the invocation MUST supply the intended project through `--project` or the command's explicit positional project operand

### Requirement: Stable installed hook binary

Auto-handover hook registration SHALL resolve `mycelium` from PATH at install-hooks time with `shutil.which` or an equivalent `command -v`, normalize the result to an absolute path, and write commands rooted at exactly that path into `~/.claude/settings.json`. The written path SHALL remain fixed after registration. If resolution fails, registration SHALL fail loud with `[FAIL]` and SHALL NOT write an unresolved hook command. The installed CLI SHALL expose hook commands that preserve the existing PreCompact and SessionStart stdin, matcher, system-message, exit-status, and best-effort metrics semantics. Checkout hook wrappers SHALL resolve `mycelium` with `command -v mycelium` when invoked, SHALL fail loud with `[FAIL]` when absent, and SHALL NOT import `tasks.mycelium` in-process. Hook commands SHALL NOT use `uvx`.

#### Scenario: settings-hooks-use-stable-binary

- **WHEN** auto-handover hooks are installed into an empty settings file with a fake `mycelium` binary on PATH in a temporary directory
- **THEN** both generated hook commands MUST start with an absolute path to the `mycelium` binary that equals the path resolved at install time, MUST name the appropriate installed hook subcommand, and MUST NOT contain a checkout path, `python -m tasks.mycelium`, or `uvx`

#### Scenario: checkout-hook-wrappers-avoid-source-imports

- **WHEN** either checkout compatibility hook handles a supported Claude hook payload with a fake `mycelium` binary on PATH in a temporary directory
- **THEN** it MUST delegate to the binary path returned by `command -v mycelium`, preserve the existing observable hook result, and MUST NOT execute an in-process import from `tasks.mycelium`

### Requirement: Verify-before-unlink migration

The six real-checkout skill symlinks and their consumer-side `SKILL_REPO` or `resolve-skill-repo` compatibility logic SHALL remain present until a clean environment with no yibi-stack checkout passes the Git install, console-script, six-skill invocation, explicit-target, and hook checks. A failed or incomplete verification SHALL block cleanup. After the verification passes, the six symlinks and only the resolver logic made obsolete in those six consumers SHALL be removed. The `tasks.mycelium` package root and the import paths of the 26 test files identified by issue #222 SHALL remain unchanged throughout the migration.

#### Scenario: test-import-paths-remain-stable

- **WHEN** Phase A packaging and skill migration changes are complete
- **THEN** the mycelium tests identified by issue #222 MUST still import through `tasks.mycelium`, and the package MUST remain rooted at `tasks/mycelium`

#### Scenario: failed-verification-retains-links

- **WHEN** any clean-install, CLI, skill-path, explicit-target, or hook verification fails or has not run
- **THEN** all six real-checkout skill symlinks and their resolver compatibility lane MUST remain available

#### Scenario: successful-verification-allows-cleanup

- **WHEN** every required end-to-end verification passes against a recorded Git tag
- **THEN** the six real-checkout skill symlinks and obsolete resolver logic in the six consumers MUST be removed without changing the package root or test import paths

### Requirement: Two-track installation documentation

The English and Traditional Chinese README install sections SHALL document plugin installation and CLI installation as two separate, complementary tracks. The CLI track and every migrated SKILL.md failure gate SHALL use only `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"`. Phase A documentation SHALL NOT contain a PyPI install command for mycelium or yibi-stack.

#### Scenario: readme-shows-two-track-install

- **WHEN** a user reads either README install section
- **THEN** the user MUST find the plugin installation track and the exact Git-tag CLI installation track, with their distinct purposes stated

#### Scenario: pypi-install-is-not-pre-documented

- **WHEN** README and the six migrated SKILL.md files are searched for mycelium or yibi-stack installation commands
- **THEN** the supported command MUST be the exact Git-tag command and no PyPI installation command MUST be present

## Purpose

Rule files under `.claude/rules/` are always-loaded or path-scoped prose that agents must remember, while a mechanical gate is checked without memory. This capability requires every newly added rule section to either link an existing mechanical gate or declare, from a closed set of reasons, why it cannot be mechanized, so that "write a rule" stops being the default answer to a lesson.

## ADDED Requirements

### Requirement: Added rule sections carry a mechanization declaration

The lint SHALL require every newly added `##` or `###` section in a file matching `.claude/rules/*.md` to contain exactly one mechanization declaration, which is either a gate link `<!-- gate: <path>[::<symbol>] -->` or a gate exemption `<!-- gate: none (reason: <reason>) — <explanation> -->`. A section without any declaration SHALL be reported as missing a declaration. Declaration lines inside fenced code blocks or table rows SHALL NOT count, because those contexts quote the syntax as an example rather than make the claim.

#### Scenario: Section with a valid gate link passes

- **WHEN** a diff adds a `###` section to an existing rule file and the section contains a gate link to an existing eligible file
- **THEN** the lint SHALL report no finding for that section

#### Scenario: Section without a declaration is reported

- **WHEN** a diff adds a `###` section to a rule file and the section contains no gate link and no gate exemption
- **THEN** the lint SHALL report that section by heading as missing a mechanization declaration

#### Scenario: Declaration quoted in a code fence does not count

- **WHEN** a diff adds a section whose only gate declaration appears inside a fenced code block
- **THEN** the lint SHALL treat the section as missing a declaration

#### Scenario: Two declarations in one section are rejected

- **WHEN** a diff adds a section containing both a gate link and a gate exemption
- **THEN** the lint SHALL report the section as having conflicting declarations

### Requirement: A gate link must resolve to an eligible gate

A gate link SHALL resolve only when its path exists in the repository and lies in the closed eligible set: `scripts/`, `.claude/hooks/`, `.pre-commit-config.yaml`, `.github/workflows/`, and any `tests/` directory under `scripts/` or `tasks/`. A path under `.claude/rules/`, any `SKILL.md`, or any other location SHALL NOT be eligible, because pointing a rule at prose is not a mechanical gate. When a link names a `::<symbol>`, the target file content SHALL contain that symbol as a whole word. A link that does not resolve SHALL be an error regardless of enforcement tier.

#### Scenario: Link to a nonexistent path is an error

- **WHEN** a section's gate link names `scripts/does_not_exist.py`
- **THEN** the lint SHALL exit non-zero and name the unresolved path

#### Scenario: Link to another rule file is rejected

- **WHEN** a section's gate link names `.claude/rules/13-bash-anti-patterns.md`
- **THEN** the lint SHALL exit non-zero and state that rule files are not eligible gates

#### Scenario: Link to a missing symbol is an error

- **WHEN** a section's gate link names `scripts/lint_rule_evidence.py::no_such_function` and that file does not contain the word `no_such_function`
- **THEN** the lint SHALL exit non-zero and name the missing symbol

##### Example: eligibility of link targets

| Link target | Result | Notes |
|-------------|--------|-------|
| `scripts/lint_rule_evidence.py::check_rule_evidence` | resolves | file exists, symbol present |
| `.claude/hooks/protect-push.sh` | resolves | hook directory |
| `scripts/tests/test_lint_rule_evidence.py` | resolves | tests under scripts |
| `.claude/rules/17-shell-script-authoring.md` | rejected | prose, not a gate |
| `plugins/growth/skills/pr-retrospective/SKILL.md` | rejected | SKILL.md is not a gate |
| `scripts/missing.py` | error | path does not exist |

### Requirement: Gate exemption reasons form a closed set

A gate exemption SHALL name exactly one reason from the closed set `judgment`, `no-observable-signal`, and `hook-cost`, and SHALL carry a non-empty explanation after the em dash. An explanation consisting only of a placeholder (`TBD`, `TODO`, `N/A`, `none`) or fewer than 12 non-space characters SHALL be rejected. A reason outside the closed set SHALL be rejected; the set has no catch-all value.

#### Scenario: Unknown reason is rejected

- **WHEN** a section declares `<!-- gate: none (reason: other) — because -->`
- **THEN** the lint SHALL report the reason as outside the closed set

#### Scenario: Placeholder explanation is rejected

- **WHEN** a section declares `<!-- gate: none (reason: judgment) — TBD -->`
- **THEN** the lint SHALL report the explanation as a placeholder

#### Scenario: Complete exemption passes

- **WHEN** a section declares `<!-- gate: none (reason: judgment) — requires reading the reviewer prompt for unverified causal claims -->`
- **THEN** the lint SHALL report no finding for that section

### Requirement: Enforcement is tiered by file novelty

A newly added rule file whose sections lack a declaration SHALL produce an error and a non-zero exit. A newly added section in an already-existing rule file that lacks a declaration SHALL produce a warning only. The lint SHALL NOT require declarations on sections that already exist, and SHALL NOT scan unchanged content. A rename of a file into `.claude/rules/` from outside that directory, where the diff carries at least one hunk of its content, SHALL be treated as a new rule file. A pure 100%-similarity rename carries no hunk and is a documented residual, because the diff text then contains no content to inspect.

#### Scenario: New rule file without declarations fails

- **WHEN** a diff adds `.claude/rules/20-new-topic.md` containing one `##` section without a declaration
- **THEN** the lint SHALL exit with code 1

#### Scenario: New section in existing rule file only warns

- **WHEN** a diff adds one undeclared `###` section to `.claude/rules/13-bash-anti-patterns.md`
- **THEN** the lint SHALL print a warning naming the heading and SHALL exit with code 0

#### Scenario: Rename into the rules directory is treated as new

- **WHEN** a diff renames `scripts/notes.md` to `.claude/rules/renamed-in.md` with content hunks and its sections lack declarations
- **THEN** the lint SHALL exit with code 1

#### Scenario: New rule file without any section needs a file-level declaration

- **WHEN** a diff adds a new rule file that contains no `##` or `###` heading and no declaration anywhere in the file
- **THEN** the lint SHALL exit with code 1, because a file without sections would otherwise escape the check

### Requirement: The declaration check is independent of the evidence check

The mechanization check SHALL run in addition to the existing evidence-marker check and SHALL NOT be satisfied by an evidence marker. A section carrying a valid evidence marker but no declaration SHALL still be reported as missing a declaration, and a section carrying a declaration but no evidence marker SHALL still follow the existing evidence-marker tiering. The check SHALL run at both existing execution points, the staged-diff mode and the commit-range mode.

#### Scenario: Evidence marker does not satisfy the declaration

- **WHEN** a diff adds a section containing `(Source: PR #339` and no gate declaration
- **THEN** the lint SHALL report the section as missing a mechanization declaration

#### Scenario: Declaration does not satisfy the evidence marker

- **WHEN** a diff adds a new rule file whose sections carry valid gate links but no evidence marker
- **THEN** the lint SHALL still report the missing evidence marker under the existing evidence rule

### Requirement: The check fails loudly when it cannot verify a link

Resolving a gate link SHALL use the repository root of the checkout being linted. If the repository root cannot be determined, or a path check raises an operating-system error other than the path being absent, the lint SHALL exit with code 2 and a `[FAIL]` message. The lint SHALL NOT treat an unverifiable link as resolved.

#### Scenario: Unreadable repository root exits 2

- **WHEN** link resolution raises an `OSError` that is not "file not found"
- **THEN** the lint SHALL exit with code 2 and SHALL NOT print an all-clear message

### Requirement: Every blocking shape has a committed positive control

For each shape the lint is specified to block, the repository SHALL contain a committed fixture diff that the lint must reject, and a test SHALL assert the rejection through both the pure function and the process entry point `main()`. The blocking shapes are: missing declaration, new file without sections, dangling link, link to a rule file, link to a missing symbol, unknown exemption reason, placeholder explanation, and conflicting declarations. At least one fixture SHALL be derived from a copy of a real rule file with an undeclared section injected, and the test SHALL assert that the injected anchor was applied before asserting the lint reaction.

#### Scenario: Entry point short-circuit turns the controls red

- **WHEN** the lint's `main()` is mutated to return 0 before reading any diff
- **THEN** the fixture tests asserting a non-zero exit SHALL fail

#### Scenario: Injection anchor absent fails the control

- **WHEN** the real-data control cannot find its injection anchor in the copied rule file
- **THEN** the test SHALL fail with an anchor-not-found message rather than pass vacuously

#### Scenario: Each blocking shape has its own fixture

- **WHEN** the fixture directory is enumerated
- **THEN** it SHALL contain at least one rejected-diff fixture for each of the eight blocking shapes, and a test SHALL assert that count

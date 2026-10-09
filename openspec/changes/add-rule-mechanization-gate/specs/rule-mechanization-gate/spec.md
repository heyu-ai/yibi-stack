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

### Requirement: Missing and false declarations are errors in every rule file

A newly added section that lacks a declaration SHALL produce an error and a non-zero exit, whether the rule file is newly added or already exists. A false declaration SHALL produce the same error. There is no warning tier for either. The lint SHALL NOT require declarations on sections that already exist, and SHALL NOT scan unchanged content. A rename of a file into `.claude/rules/` from outside that directory, where the diff carries at least one hunk of its content, SHALL be treated as a new rule file. A pure 100%-similarity rename carries no hunk, so its content cannot be inspected; a pure rename into `.claude/rules/` from outside that directory SHALL therefore produce an error rather than be reported as passing, because an unverifiable file must not count as a verified one. A pure rename that stays inside `.claude/rules/`, or that does not involve `.claude/rules/`, SHALL NOT produce an error.

#### Scenario: New rule file without declarations fails

- **WHEN** a diff adds `.claude/rules/20-new-topic.md` containing one `##` section without a declaration
- **THEN** the lint SHALL exit with code 1

#### Scenario: New section in existing rule file fails

- **WHEN** a diff adds one undeclared `###` section to `.claude/rules/13-bash-anti-patterns.md`
- **THEN** the lint SHALL name the heading in its error output and SHALL exit with code 1

#### Scenario: Declaration outside the heading's hunk is reported missing

- **WHEN** a diff inserts a `###` heading above pre-existing body text that already contains a declaration, so the declaration is not among the added lines of the heading's hunk
- **THEN** the lint SHALL report the section as missing a declaration and SHALL exit with code 1, as a documented conservative over-report

#### Scenario: Rename into the rules directory is treated as new

- **WHEN** a diff renames `scripts/notes.md` to `.claude/rules/renamed-in.md` with content hunks and its sections lack declarations
- **THEN** the lint SHALL exit with code 1

#### Scenario: Pure rename into the rules directory is rejected

- **WHEN** a diff contains `similarity index 100%`, `rename from scripts/notes.md` and `rename to .claude/rules/renamed-pure.md` and no hunk
- **THEN** the lint SHALL exit with code 1 and SHALL name `.claude/rules/renamed-pure.md` in its error output

#### Scenario: Pure rename that stays inside the rules directory is not flagged

- **WHEN** a diff pure-renames `.claude/rules/old.md` to `.claude/rules/new.md`
- **THEN** the lint SHALL report no error for it, because the file already existed in that directory

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

#### Scenario: Pure rename is reported once, by the declaration check

- **WHEN** a diff pure-renames `scripts/notes.md` into `.claude/rules/renamed-pure.md`
- **THEN** the evidence check SHALL report nothing for it and the declaration check SHALL report the single error, so the existing evidence behavior is unchanged and the rename is not reported twice

#### Scenario: Both execution points run the declaration check

- **WHEN** an undeclared new rule file is staged, and separately when it is committed on a branch and the lint runs over the commit range
- **THEN** the lint SHALL exit with code 1 in the staged mode and in the commit-range mode

#### Scenario: Staged mode survives diff.mnemonicPrefix

- **WHEN** the repository has `diff.mnemonicPrefix` set to true and an undeclared new rule file is staged
- **THEN** the lint SHALL still exit with code 1, because the diff it reads SHALL use fixed `a/` and `b/` path prefixes regardless of that setting

### Requirement: The check fails loudly when it cannot verify a link

Resolving a gate link SHALL use the repository root of the checkout being linted. If a path check raises an operating-system error other than the path being absent, the lint SHALL exit with code 2 and a `[FAIL]` message. The repository root is derived from the lint script's own location, so there is no separate root-resolution failure to report. The lint SHALL NOT treat an unverifiable link as resolved.

#### Scenario: Unverifiable gate link exits 2

- **WHEN** link resolution raises an `OSError` that is not "file not found"
- **THEN** the lint SHALL exit with code 2 and SHALL NOT print an all-clear message

### Requirement: Every blocking shape has a committed positive control

For each shape the lint is specified to block, the repository SHALL contain a committed fixture diff that the lint must reject, and a test SHALL assert the rejection through both the pure function and the process entry point `main()`. The blocking shapes are: missing declaration in a new file, missing declaration in an existing file, pure rename into the rules directory, new file without sections, dangling link, link to a rule file, link to a missing symbol, unknown exemption reason, placeholder explanation, and conflicting declarations. At least one fixture SHALL be derived from a copy of a real rule file with an undeclared section injected, and the test SHALL assert that the injected anchor was applied before asserting the lint reaction.

#### Scenario: Entry point short-circuit turns the controls red

- **WHEN** the lint's `main()` is mutated to return 0 before reading any diff
- **THEN** the fixture tests asserting a non-zero exit SHALL fail

#### Scenario: Injection anchor absent fails the control

- **WHEN** the real-data control cannot find its injection anchor in the copied rule file
- **THEN** the test SHALL fail with an anchor-not-found message rather than pass vacuously

#### Scenario: Each blocking shape has its own fixture

- **WHEN** the fixture directory is enumerated
- **THEN** it SHALL contain at least one rejected-diff fixture for each of the ten blocking shapes, and a test SHALL assert that count

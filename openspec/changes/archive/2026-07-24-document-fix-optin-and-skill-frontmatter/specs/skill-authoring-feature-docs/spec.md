## ADDED Requirements

### Requirement: disallowed-tools frontmatter documentation

Rule 11 (.claude/rules/11-skill-authoring.md) SHALL document the disallowed-tools frontmatter key using the official hyphenated key name, covering: accepted value formats (space- or comma-separated string, or a YAML list), runtime semantics (listed tools are removed from Claude's available tool pool while the skill is active; the restriction lifts when the turn ends), and intended use cases (skills with a read-only contract, and autonomous or background skills that must never call interactive tools such as AskUserQuestion). The section SHALL quote the official documentation wording verbatim and SHALL carry a verification stamp naming the source and the date it was checked. The skill template (skills/_template/SKILL.md.tpl) SHALL carry a commented disallowed-tools line in its frontmatter block with a format hint.

#### Scenario: Author consults rule 11 for tool restriction

- **WHEN** a skill author reads the frontmatter sections of rule 11
- **THEN** they find a disallowed-tools section that uses the hyphenated key name, quotes the official documentation, and names at least one concrete use case

#### Scenario: Template exposes the key

- **WHEN** an author copies the skill template frontmatter block
- **THEN** a commented disallowed-tools line with a value-format hint is present

### Requirement: Literal dollar escape documentation

Rule 11 SHALL document the backslash-dollar escape for emitting a literal dollar sign before a digit, ARGUMENTS, or a declared argument name in skill and slash command bodies, quoting the official rule that only a single backslash directly before the token escapes it and that a backslash before any other dollar is left unchanged. Rule 13 (.claude/rules/13-bash-anti-patterns.md) SHALL contain a cross-reference subsection that identifies the mechanism as Markdown-layer substitution (not bash escaping) and points to rule 11 for the full rules. The escape behavior claims SHALL be probed locally before authoring and the probe result stamped with the Claude Code version used.

#### Scenario: Escape semantics stated

- **WHEN** a reader consults the escape documentation in rule 11
- **THEN** it states that only a single backslash directly before the token escapes it, and that a backslash before any other dollar sign is left unchanged

##### Example: escape boundary table

| Written in skill body | Rendered output | Notes |
| --------------------- | --------------- | ----- |
| \$1.00 | $1.00 | single backslash directly before a digit escapes |
| \$ARGUMENTS | $ARGUMENTS | same rule for the ARGUMENTS placeholder |
| \\$1 | two backslashes kept; $1 still expands | only a single backslash directly before the token escapes |
| \$x (x not a digit or declared argument) | \$x unchanged | backslash before any other dollar is left unchanged |

#### Scenario: Rule 13 disambiguates the layer

- **WHEN** a reader searches rule 13 for dollar escaping
- **THEN** they find a subsection stating the escape is Markdown-layer skill-body substitution, distinct from bash quoting, with a cross-reference to rule 11

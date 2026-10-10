## Purpose

Rule files under `.claude/rules/` are always-loaded or path-scoped prose that agents must remember, while a mechanical gate is checked without memory. This capability requires every newly added rule section to either link an existing mechanical gate or declare, from a closed set of reasons, why it cannot be mechanized, so that "write a rule" stops being the default answer to a lesson.

## ADDED Requirements

### Requirement: Added rule sections carry a mechanization declaration

The lint SHALL require every newly added `##` or `###` section in a file matching `.claude/rules/*.md` to contain exactly one mechanization declaration, which is either a gate link `<!-- gate: <path>[::<symbol>] -->` or a gate exemption `<!-- gate: none (reason: <reason>) — <explanation> -->`. A section without any declaration SHALL be reported as missing a declaration. Declaration lines inside fenced code blocks or table rows SHALL NOT count, because those contexts quote the syntax as an example rather than make the claim. Every added section in a hunk SHALL be checked on its own, not only the first or the last one.

The lint SHALL compute sections over the whole post-image of each changed file, not over the changed lines alone: a section runs from its heading to the next `##` or `###` heading, unchanged lines under an added heading belong to it, and fence state is tracked from the start of the file. A line inside a fenced code block (backtick or tilde fence, including a longer outer fence that contains a shorter inner one) SHALL NOT start a section, because a heading in an example is not a section. An added heading SHALL be treated as a retitle of an existing section, not a new section, only when the pre-image contains a removed heading of the same level that is a real heading (not a line inside a fenced code block) and whose body is identical to the added section's body once whitespace is ignored; each removed heading excuses at most one added heading, and a heading whose level or body differs stays a new section. Setext headings and indented headings are intentionally not recognised: `.markdownlint.yaml` sets `default: true`, so MD003 (consistent heading style) rejects a setext heading in an ATX file before this lint runs, and every rule file is ATX.

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

#### Scenario: Heading inside a code fence is not a section

- **WHEN** a diff adds a declared `###` section whose body contains a fenced code block (backtick fence, tilde fence, or a four-backtick fence wrapping a three-backtick one) with `## When to use` and `## Steps` lines inside it
- **THEN** the lint SHALL report no finding, and a `###` heading added after the fence is closed SHALL still be checked as a section

#### Scenario: Retitled heading is not a new section

- **WHEN** a diff removes `### Old Title` and adds `### New Title` over an unchanged body
- **THEN** the lint SHALL report no finding for it, while a second added heading, or an added heading whose level differs from the removed one, or an added heading whose only matching removal is in a different hunk, SHALL still be checked

#### Scenario: Retitle exemption requires an identical body and a real heading

- **WHEN** a diff replaces `### Old Title` and its body with `### New Title` and a different body, or deletes a `### Example` line that sits inside a fenced code block while adding an undeclared `### New Rule`, or only changes the heading text of a legacy section that never had a declaration
- **THEN** the lint SHALL report the first two as new sections missing a declaration (and accept them once declared), and SHALL accept the third, because only a heading whose removed counterpart is a real heading with the same body is a retitle

#### Scenario: Fence state comes from the whole file, not the hunk

- **WHEN** a diff edits the last code block of an existing rule file and adds an undeclared `##` section after it (git aligns the old closing fence into the changed lines), or adds a declared rule file whose fenced example contains `## When to use` and `## Steps`
- **THEN** the lint SHALL report the undeclared section by heading and exit with code 1, and SHALL report no finding for the declared file with the fenced example, because the fence's opening line is read even when it is not part of the change

#### Scenario: Declaration below an inserted heading counts even if not added

- **WHEN** a diff inserts a `##` heading directly above existing body text that already contains an evidence marker and a valid declaration
- **THEN** the lint SHALL exit with code 0, because the declaration is part of the section in the post-image

#### Scenario: Content lines that look like diff headers are content

- **WHEN** an existing rule file gains the line `++ note` followed by an undeclared `## Brand New` section, or a file loses the line `-- "x" y`, or a line `-- "x" y` is replaced by `++ "x" y` so git emits an adjacent `--- "x" y` and `+++ "x" y`
- **THEN** the lint SHALL still report the undeclared section after `++ note`, and SHALL NOT treat the other two as file headers or exit 2, because the hunk's `@@ -a,b +c,d @@` line counts show those lines are still inside the hunk

#### Scenario: Every section in a hunk is checked

- **WHEN** one hunk adds two `###` sections, the first declared and the second not (and, separately, the first not and the second declared)
- **THEN** the lint SHALL report exactly one error, naming the undeclared section, and a committed fixture of this shape SHALL be rejected through both the pure function and `main()`

### Requirement: A gate link must resolve to an eligible gate

A gate link SHALL resolve only when its path exists in the repository as a file (an exact path that names a blob, never a directory) and lies in the closed eligible set: `scripts/`, `.claude/hooks/`, `.pre-commit-config.yaml`, `.github/workflows/`, and any `tests/` directory under `scripts/` or `tasks/`. A path under `.claude/rules/`, any `SKILL.md`, or any other location SHALL NOT be eligible, because pointing a rule at prose is not a mechanical gate. When a link names a `::<symbol>`, the target file content SHALL contain that symbol as a whole word. A link that does not resolve SHALL be an error regardless of enforcement tier.

#### Scenario: Link to a nonexistent path is an error

- **WHEN** a section's gate link names `scripts/does_not_exist.py`
- **THEN** the lint SHALL exit non-zero and name the unresolved path

#### Scenario: Link to another rule file is rejected

- **WHEN** a section's gate link names `.claude/rules/13-bash-anti-patterns.md`
- **THEN** the lint SHALL exit non-zero and state that rule files are not eligible gates

#### Scenario: Link to a missing symbol is an error

- **WHEN** a section's gate link names `scripts/lint_rule_evidence.py::no_such_function` and that file does not contain the word `no_such_function`
- **THEN** the lint SHALL exit non-zero and name the missing symbol

#### Scenario: Link to a directory is treated as absent

- **WHEN** a section's gate link names a directory that exists in the checked tree (for example `scripts/sub`), or a glob such as `scripts/*.py` that would match files
- **THEN** the lint SHALL report the path as not existing, and a path whose name itself contains glob characters (`scripts/x[1].py`) SHALL still resolve to that exact file

#### Scenario: Each eligibility condition is individually enforced

- **WHEN** a link names `scripts/sub/SKILL.md`, `tasks/foo/bar.py` (not under a `tests/` directory), a path containing a backslash under an eligible prefix, or `scripts/lint_rule_evidence.py::rule_evidence` where `rule_evidence` occurs only as the tail of a longer identifier, and every such target exists in the checked tree
- **THEN** the lint SHALL reject each one, so removing any single eligibility condition changes at least one of these outcomes

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

A gate exemption SHALL name exactly one reason from the closed set `judgment`, `no-observable-signal`, and `hook-cost`, and SHALL carry a non-empty explanation after the em dash. An explanation consisting only of a placeholder (`TBD`, `TODO`, `N/A`, `none`) or fewer than 12 non-space characters SHALL be rejected; every placeholder is shorter than 12 characters, so the length rule alone enforces both and no separate placeholder list exists. Whitespace SHALL NOT count toward the length, and surrounding whitespace SHALL NOT raise it. A reason outside the closed set SHALL be rejected; the set has no catch-all value.

#### Scenario: Unknown reason is rejected

- **WHEN** a section declares `<!-- gate: none (reason: other) — because -->`
- **THEN** the lint SHALL report the reason as outside the closed set

#### Scenario: Placeholder explanation is rejected

- **WHEN** a section declares `<!-- gate: none (reason: judgment) — TBD -->`
- **THEN** the lint SHALL report the explanation as a placeholder

#### Scenario: Exemption explanation length boundary

- **WHEN** an exemption explanation has 11 non-space characters, or 12 characters including a space but only 11 non-space ones, or 11 non-space characters padded with surrounding spaces, and (separately) 12 non-space characters with or without an inner space
- **THEN** the lint SHALL reject the first three and accept the last two

#### Scenario: Complete exemption passes

- **WHEN** a section declares `<!-- gate: none (reason: judgment) — requires reading the reviewer prompt for unverified causal claims -->`
- **THEN** the lint SHALL report no finding for that section

### Requirement: Missing and false declarations are errors in every rule file

A newly added section that lacks a declaration SHALL produce an error and a non-zero exit, whether the rule file is newly added or already exists. A false declaration SHALL produce the same error. There is no warning tier for either. The lint SHALL NOT require declarations on sections that already exist, and SHALL NOT scan unchanged content. A rename of a file into `.claude/rules/` from outside that directory, where the diff carries at least one hunk of its content, SHALL be treated as a new rule file. A pure 100%-similarity rename carries no hunk, so its content cannot be inspected; a pure rename into `.claude/rules/` from outside that directory SHALL therefore produce an error rather than be reported as passing, because an unverifiable file must not count as a verified one. A pure rename that stays inside `.claude/rules/`, or that does not involve `.claude/rules/`, SHALL NOT produce an error. The same fail-closed rule SHALL apply to every other shape whose content the diff does not show: a copy without a hunk into `.claude/rules/` (the source need not be outside that directory, because the target is a new file), a rule file, new or existing, that git classifies as binary (`Binary files ... differ`, for example because it contains a NUL byte or because `.gitattributes` marks it `binary` or `-diff`), and an empty new rule file (a `new file mode` block with no `+++` line, which has no place to put a declaration). For a rule file that git reports as binary, the lint SHALL re-read that file alone with `--text` (never every file in the diff, so real binaries elsewhere are not dumped as text); a rule file that still contains a NUL byte SHALL be rejected as not being text, whether or not it declares its sections, and a rule file that git only treated as binary because of an attribute SHALL then be checked like any other text file, neither hidden nor falsely blocked. Each SHALL produce an error that names the path and the reason. A binary or empty file outside `.claude/rules/` SHALL NOT produce an error, and the evidence check's behavior for these shapes SHALL be unchanged (it ignores them, so the same file is not reported twice).

#### Scenario: New rule file without declarations fails

- **WHEN** a diff adds `.claude/rules/20-new-topic.md` containing one `##` section without a declaration
- **THEN** the lint SHALL exit with code 1

#### Scenario: New section in existing rule file fails

- **WHEN** a diff adds one undeclared `###` section to `.claude/rules/13-bash-anti-patterns.md`
- **THEN** the lint SHALL name the heading in its error output and SHALL exit with code 1

#### Scenario: Declaration outside the heading's hunk is reported missing

- **WHEN** a diff that does not carry the whole file (a positional diff file made with `-U0`, or a synthetic one) has a `###` heading in one hunk and the declaration in another hunk
- **THEN** the lint SHALL report the section as missing a declaration and SHALL exit with code 1, as a documented conservative over-report, because sections never span the unseen gap between hunks

#### Scenario: Rename into the rules directory is treated as new

- **WHEN** a diff renames `scripts/notes.md` to `.claude/rules/renamed-in.md` with content hunks and its sections lack declarations
- **THEN** the lint SHALL exit with code 1

#### Scenario: Pure rename into the rules directory is rejected

- **WHEN** a diff contains `similarity index 100%`, `rename from scripts/notes.md` and `rename to .claude/rules/renamed-pure.md` and no hunk
- **THEN** the lint SHALL exit with code 1 and SHALL name `.claude/rules/renamed-pure.md` in its error output

#### Scenario: Pure rename that stays inside the rules directory is not flagged

- **WHEN** a diff pure-renames `.claude/rules/old.md` to `.claude/rules/new.md`
- **THEN** the lint SHALL report no error for it, because the file already existed in that directory

#### Scenario: Copy into the rules directory is rejected

- **WHEN** git reports a copy into `.claude/rules/` with `copy from`/`copy to` lines and no hunk (including a copy whose source is also under `.claude/rules/`), and separately when `diff.renames` is set to `copies` and a file is copied into `.claude/rules/` while its source is modified in the same change
- **THEN** the lint SHALL exit with code 1 for the hunk-less copy, and for the `diff.renames=copies` case SHALL read the copy as an ordinary new file (the lint passes `-M` explicitly): an undeclared copy is reported by section heading and a declared copy passes

#### Scenario: Binary new rule file is rejected

- **WHEN** a new `.claude/rules/*.md` file containing a NUL byte is staged, and separately when it is committed and the lint runs over the range
- **THEN** the lint SHALL exit with code 1 in both modes and the error SHALL name the path and say the file is binary

#### Scenario: Rule file containing a NUL byte is rejected

- **WHEN** an existing rule file gains a NUL byte together with an undeclared new section, or together with a fully declared one
- **THEN** the lint SHALL exit with code 1 in both cases and the error SHALL mention the NUL byte, so a binary classification cannot hide a new section and a complete declaration cannot excuse a non-text file

#### Scenario: A binary attribute does not hide or falsely block a rule file

- **WHEN** `.gitattributes` marks `.claude/rules/*.md` as `binary` (or `-diff`) and an existing rule file gains an undeclared section, and separately a declared one, and separately a real binary file is changed elsewhere in the same diff
- **THEN** the lint SHALL exit with code 1 for the undeclared section, exit with code 0 for the declared one and for the unrelated binary file

#### Scenario: Empty new rule file is rejected

- **WHEN** an empty new `.claude/rules/*.md` file is staged, and separately when it is committed and the lint runs over the range
- **THEN** the lint SHALL exit with code 1 in both modes and the error SHALL name the path and say the file is empty

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

### Requirement: Gate links are resolved against the content being committed or reviewed

Resolving a gate link SHALL use the repository root of the checkout being linted, and SHALL read the content that the diff describes rather than whatever happens to be on disk. In the staged mode the lint SHALL read the link target from the tree that `git write-tree` builds from the index, which is exactly what `git commit` will commit (an intent-to-add entry created by `git add -N` is not in it, while a legitimately staged empty file is); in the commit-range mode it SHALL read it from the tree of the requested `--head`; in the positional diff-file mode, which carries no git context, it SHALL read the working tree, and this SHALL be documented behavior. A target that exists only as an untracked file on disk does not exist in the commit, so a link to it SHALL be reported as dangling; a target that is staged (or present at the head) but absent from disk SHALL resolve.

#### Scenario: Staged mode reads gate links from the index

- **WHEN** a rule section is staged with a gate link to `scripts/new_gate.py::gate` and the script exists only as an untracked file on disk
- **THEN** the lint SHALL exit with code 1 and name the path; once the script is staged it SHALL pass, it SHALL still pass when the working-tree copy no longer contains the symbol or no longer exists, because the index copy is what is checked

#### Scenario: Intent-to-add gate is not an existing gate

- **WHEN** a rule section links to `scripts/gate.py`, and the script was registered with `git add -N` (or is entirely untracked), and separately was added with a normal `git add`, and separately is a legitimately staged empty file
- **THEN** the lint SHALL exit with code 1 for the intent-to-add and untracked cases and exit with code 0 for the normally staged one and the staged empty file

#### Scenario: Range mode reads gate links from the head

- **WHEN** the lint runs over `--base`/`--head` where the head commit contains both the rule and the gate script while the checked-out working tree has neither, and separately where the head lacks the script while the checked-out tree has it
- **THEN** the lint SHALL exit with code 0 for the first and with code 1 for the second

#### Scenario: Range mode sees the same post-image as staged mode

- **WHEN** a commit contains a rule file with a NUL byte and an undeclared section, a rule file whose edited last code block slides the old closing fence into the diff before an undeclared section, and a rule file whose fenced `### Example` is replaced by an undeclared `### New Rule`, and the lint runs over `--base`/`--head` (each shape also on its own)
- **THEN** the lint SHALL exit with code 1 for the combined commit and for each shape separately, the same verdicts as in staged mode

#### Scenario: Diff file mode reads gate links from the working tree

- **WHEN** the lint is given a diff file whose section links to `scripts/new_gate.py`
- **THEN** the lint SHALL resolve the link against the working tree: exit code 1 while the file is absent and 0 once it exists

### Requirement: The check fails loudly when it cannot verify a link

If a path check raises an operating-system error other than the path being absent, or the git command used to read the index or the head fails (an unresolvable revision, a git error, an unmerged index entry), the lint SHALL exit with code 2 and a `[FAIL]` message (in the staged mode that includes `git write-tree` failing on an unmerged index). Only "no such path" is an answer; every other failure means the link could not be verified. The repository root is derived from the lint script's own location, so there is no separate root-resolution failure to report. The lint SHALL NOT treat an unverifiable link as resolved.

#### Scenario: Unverifiable gate link exits 2

- **WHEN** link resolution raises an `OSError` that is not "file not found"
- **THEN** the lint SHALL exit with code 2 and SHALL NOT print an all-clear message

#### Scenario: Git failure while reading a gate exits 2

- **WHEN** the git command that reads a gate from the index or from the head fails, or the gate's index entry is unmerged
- **THEN** the lint SHALL exit with code 2 with a `[FAIL]` message and SHALL NOT print an all-clear message

### Requirement: The lint reads git output independently of user configuration

The diff the lint parses SHALL NOT depend on the user's git configuration. The lint SHALL invoke git with `core.quotePath=false`, `--no-color`, `--no-ext-diff`, `--no-textconv`, an explicit `-M`, fixed `a/` and `b/` path prefixes, and `--unified=1000000` so that each changed file appears as a single hunk carrying its whole post-image and pre-image. The diff SHALL be read as bytes and decoded so that bytes which are not valid UTF-8 are preserved (`surrogateescape`) rather than raising, and messages that name such a path SHALL still print. Paths that git still wraps in C-style quotes (those containing a tab, a double quote, a backslash or an invalid UTF-8 byte, and any non-ASCII path in a diff file produced with the default `core.quotePath`) SHALL be decoded (`\ooo` octal bytes interpreted as UTF-8, `\"`, `\\`, `\t`, `\n` and the other C escapes) before any path is matched. A quoted path whose quoting is malformed (an unterminated quote, an unknown escape, an incomplete octal escape) SHALL make the lint exit with code 2 with a `[FAIL]` message instead of being skipped, because a path that cannot be read cannot be shown not to be a rule file. A well-formed quoted path whose decoded bytes are not valid UTF-8 is not malformed: it SHALL be preserved and checked like any other path. `-M` is used rather than `--no-renames` because disabling rename detection would turn an in-directory pure rename into an undeclared new file.

#### Scenario: Non-ASCII and special-character paths are checked

- **WHEN** an undeclared new rule file named `規則.md`, `a"b.md` or `tab<TAB>name.md` is staged, committed and checked over a range, or a CJK-named file is `git mv`-ed into `.claude/rules/`, or a diff file contains git's default-quoted path
- **THEN** the lint SHALL exit with code 1 in each case and print the real file name, while the same file name with a complete declaration passes

#### Scenario: Undecodable quoted path exits 2

- **WHEN** a diff header contains a quoted path whose quoting cannot be decoded (`"b/unterminated`, `"b/bad\qescape.md"`, `"b/\35.md"`)
- **THEN** the lint SHALL exit with code 2 with a `[FAIL]` message and SHALL NOT print an all-clear message

#### Scenario: Non-UTF-8 input neither crashes nor bypasses

- **WHEN** an unrelated file with non-UTF-8 content (`caf\xe9`) is staged, and separately a rule file whose name is not valid UTF-8 (`.claude/rules/\xff\xfe.md`) is staged without a declaration, and separately a diff file contains the well-formed quoted path `"b/.claude/rules/\377\376.md"` without a declaration
- **THEN** the lint SHALL exit with code 0 for the unrelated file, and SHALL exit with code 1 for the two undeclared non-UTF-8-named rule files without raising `UnicodeEncodeError` while printing the message

#### Scenario: User diff configuration cannot hide a change

- **WHEN** the repository sets `color.ui=always`, or `diff.external`, or a textconv driver for `*.md`, and an undeclared new rule file is staged
- **THEN** the lint SHALL still exit with code 1, and a declared rule file under the same configuration SHALL pass

### Requirement: Every blocking shape has a committed positive control

For each shape the lint is specified to block, the repository SHALL contain a committed fixture diff that the lint must reject, and a test SHALL assert the rejection through both the pure function and the process entry point `main()`. The blocking shapes are: missing declaration in a new file, missing declaration in an existing file, pure rename into the rules directory, new file without sections, dangling link, link to a rule file, link to a missing symbol, unknown exemption reason, placeholder explanation, conflicting declarations, an undeclared section after a declared one in the same hunk, a new rule file whose path git quotes, a binary new rule file, an empty new rule file, and a hunk-less copy into the rules directory. The binary, empty, copy and quoted-path fixtures SHALL be real git output, not hand-written approximations. At least one fixture SHALL be derived from a copy of a real rule file with an undeclared section injected, and the test SHALL assert that the injected anchor was applied before asserting the lint reaction.

#### Scenario: Entry point short-circuit turns the controls red

- **WHEN** the lint's `main()` is mutated to return 0 before reading any diff
- **THEN** the fixture tests asserting a non-zero exit SHALL fail

#### Scenario: Injection anchor absent fails the control

- **WHEN** the real-data control cannot find its injection anchor in the copied rule file
- **THEN** the test SHALL fail with an anchor-not-found message rather than pass vacuously

#### Scenario: Each blocking shape has its own fixture

- **WHEN** the fixture directory is enumerated
- **THEN** it SHALL contain at least one rejected-diff fixture for each of the fifteen blocking shapes, and a test SHALL assert that set

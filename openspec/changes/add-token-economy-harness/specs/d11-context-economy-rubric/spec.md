## ADDED Requirements

### Requirement: scan_context_economy quantifies always-on budget and disclosure ratio

The `scan_context_economy()` function SHALL return a `MechanicalFinding` with `dimension="D11"`
and `max_score=5`, composed of two independently-scored sub-items: an always-on budget sub-item
(0–3 pts) and a progressive-disclosure ratio sub-item (0–2 pts).

The always-on set SHALL consist of the root `CLAUDE.md` plus every `.claude/rules/*.md` file that
does NOT contain a `glob:` frontmatter key. Files with a `glob:` frontmatter key are path-scoped
and SHALL be excluded from the always-on set.

The budget sub-item SHALL be scored by the total character count of the always-on set:

| Always-on chars | Budget sub-item | Label |
|-----------------|-----------------|-------|
| ≤ 20,000 | 3 | lean |
| 20,001 – 50,000 | 2 | moderate |
| 50,001 – 100,000 | 1 | heavy |
| > 100,000 | 0 | excessive |

The disclosure ratio SHALL be `(glob-scoped rules + scoped skills) / (total rules + total skills)`,
where a scoped skill is a `SKILL.md` whose frontmatter contains any of `allowed-tools`,
`allowed_tools`, `glob`, `files`, or `paths`. The ratio sub-item SHALL be scored:

| Ratio | Ratio sub-item |
|-------|----------------|
| ≥ 0.5 | 2 |
| 0.2 – 0.49 | 1 |
| < 0.2 | 0 |

When the denominator (total rules + total skills) is 0, the ratio sub-item SHALL be 2 (no
disclosure targets exist; the repo is not penalised).

The always-on file paths SHALL be returned in `extra["always_on_files"]` and the path-scoped file
paths in `extra["scoped_files"]` (both relative to `target_dir`). The largest always-on files
SHALL be placed in `semantic_targets`. The character-to-token estimate (if shown) SHALL appear
only in `findings` text and SHALL be labelled as an approximation; it SHALL NOT affect the score.

This sub-item is budget-shaped: a larger always-on set SHALL NOT increase the score.

#### Scenario: excessive always-on context scores zero on the budget sub-item

- **WHEN** the always-on set (root `CLAUDE.md` + non-`glob:` rules) totals more than 100,000 characters
- **THEN** the always-on budget sub-item is 0

#### Scenario: lean always-on context scores full budget points

- **WHEN** the always-on set totals 20,000 characters or fewer
- **THEN** the always-on budget sub-item is 3

#### Scenario: glob-scoped rule is excluded from the always-on set

- **WHEN** a `.claude/rules/*.md` file contains a `glob:` frontmatter key
- **THEN** that file does NOT appear in `extra["always_on_files"]`
- **AND** it is counted in the disclosure ratio numerator

#### Scenario: ratio sub-item full credit when no disclosure targets exist

- **WHEN** the repo has no rules and no skills (denominator 0)
- **THEN** the disclosure ratio sub-item is 2

##### Example: always-on budget boundary (boundary value analysis)

| Always-on chars | Budget sub-item |
|-----------------|-----------------|
| 20,000 | 3 (boundary — last lean value) |
| 20,001 | 2 (boundary — first moderate value) |
| 100,000 | 1 (boundary — last heavy value) |
| 100,001 | 0 (boundary — first excessive value) |

##### Example: disclosure ratio (decision table)

| glob rules | scoped skills | total rules | total skills | ratio | sub-item |
|-----------|---------------|-------------|--------------|-------|----------|
| 0 | 0 | 14 | 25 | 0.00 | 0 |
| 2 | 1 | 5 | 4 | 0.33 | 1 |
| 3 | 2 | 5 | 5 | 0.50 | 2 |
| 0 | 0 | 0 | 0 | n/a | 2 (denominator-0 guard) |

### Requirement: D11 semantic rubric scores context right-sizing and effort relativity

The D11 semantic rubric SHALL award up to 3 points across two independently-scored sub-items.

- **Context right-sizing** (2 pts): The agent SHALL read the largest always-on files from
  `semantic_targets` and judge whether their content earns always-on placement, or could instead
  be progressively disclosed (moved to an on-demand skill/doc, or scoped with `glob:`). Award 2 pts
  when most always-on content is justified; 1 pt when a meaningful portion could be moved; 0 pts
  when large always-on content (e.g. extensive how-to material) clearly belongs in on-demand docs.
- **Effort relativity** (1 pt): The agent SHALL check whether heavy skills' `effort:` frontmatter
  level matches their actual body size / cost. Award 1 pt when effort levels are appropriate or no
  heavy skills exist; 0 pts when there is a clear mismatch (e.g. a large deep-scan skill with no
  `effort:` set, or a trivial skill pinned to `effort: high`).

This rubric SHALL be limited to budget / disclosure economy. It SHALL NOT score content quality or
rule deduplication (owned by D7) nor CLAUDE.md line count / freshness (owned by D1).

#### Scenario: full semantic score when context is well right-sized

- **WHEN** always-on files contain only content that must be always present, and heavy skills have
  appropriate `effort:` levels
- **THEN** the D11 semantic score is 3 (2+1)

#### Scenario: partial score when large always-on content could be progressively disclosed

- **WHEN** a large always-on rule contains extensive path-specific how-to content that could be
  scoped with `glob:` or moved to an on-demand skill, while effort levels are appropriate
- **THEN** the D11 semantic score is 1 (0+1)

#### Scenario: D11 semantic stays within its responsibility boundary

- **WHEN** the agent observes that two rules duplicate content
- **THEN** the D11 semantic score is NOT reduced for duplication (that concern is scored by D7)

### Requirement: D11 TODO includes context-pruning recommendation when mechanical score is below threshold

When the D11 mechanical score (budget sub-item + ratio sub-item, max 5) is less than 3, the Step 4
TODO output SHALL include a context-pruning recommendation entry using the following format:

```
[D11, medium-effort, high-impact] always-on context 過肥（~<chars> 字元、約 <tokens> tokens，近似估計）
  - 將 always-on rule 改為 path-scoped：在 frontmatter 加 glob: 限定生效路徑
  - 將大段內容移至按需載入的 skill/doc，降低每回合 always-on 預算
```

The token figure SHALL be labelled as an approximation. The recommendation SHALL NOT appear when
the D11 mechanical score is 3 or above.

#### Scenario: pruning recommendation triggered for heavy always-on context

- **WHEN** the D11 mechanical score is 0 (excessive budget and ratio < 0.2)
- **THEN** the TODO list includes the context-pruning recommendation labelling tokens as approximate

#### Scenario: no pruning recommendation for lean context

- **WHEN** the D11 mechanical score is 3 or above
- **THEN** the TODO list does NOT include a context-pruning recommendation entry

##### Example: threshold boundary (boundary value analysis)

| Budget sub-item | Ratio sub-item | D11 mechanical | pruning TODO shown |
|-----------------|----------------|----------------|--------------------|
| 0 | 0 | 0 | yes |
| 1 | 1 | 2 | yes (boundary — last triggering value) |
| 1 | 2 | 3 | no (boundary — first non-triggering value) |
| 3 | 2 | 5 | no |

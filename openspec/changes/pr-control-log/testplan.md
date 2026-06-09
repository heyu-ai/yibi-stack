# Test Plan: pr-control-log

## TC Table

| TC-ID | Scenario Slug | Test Purpose | Technique | Risk | Test Data | Expected Result |
|-------|--------------|--------------|-----------|------|-----------|-----------------|
| CTL-DB-001 | idempotent-db-init | init_db() safe to call multiple times | EP | M | Call init_db() twice on same in-memory DB | No error; schema unchanged after second call |
| CTL-DB-002 | optional-fields-null | Optional fields default to NULL when omitted | EP | M | Insert entry with only required fields | Row exists; optional columns are NULL |
| CTL-DB-003 | reject-entry-not-written | Rejected entry is not persisted | HP | H | Submit entry then reject in calibration | DB row count unchanged after rejection |
| CTL-DB-004 | zero-entries-after-all-rejected | Output reflects zero when all entries rejected | EP | M | Reject all draft entries | CLI outputs count=0; DB is empty |
| CTL-VL-001 | invalid-category-rejected | Entry with invalid category is rejected | EP | H | category="UNKNOWN_CAT" | ValidationError raised; entry not written |
| CTL-VL-002 | infer-required-fields-present | All inferred entries contain required fields | EP | H | PR with agent commits present | Each entry has non-null category, summary, user_requested |
| CTL-VL-003 | write-minimal-entry | CLI writes single entry with required fields only | HP | M | Minimal payload: category, summary, user_requested | Entry persisted; optional fields NULL |
| CTL-VL-004 | write-entry-with-all-optional-fields | CLI writes entry with all 11 fields | HP | M | Full payload with all 11 audit fields populated | Entry persisted with all 11 fields intact |
| CTL-ST-001 | infer-autonomous-decision | Agent infers autonomous_decision from git log | HP | H | Git log with agent-authored commit | At least one entry with category=autonomous_decision |
| CTL-ST-002 | infer-multiple-categories | Agent infers entries across multiple categories | HP | H | Git log with commits of mixed intent | Entries covering >= 2 distinct categories |
| CTL-ST-003 | infer-no-agent-commits | No entries inferred when PR has no agent actions | EG | M | Git log with only human-authored commits | Inferred entry list is empty |
| CTL-ST-004 | approve-on-first-round | Developer approves draft without corrections | HP | M | Draft with 2 entries; user input: approve | Both entries written; calibration ends at round 1 |
| CTL-ST-005 | modify-summary-then-approve | Developer corrects summary in round 2 | State Transition | H | Round 1: reject with correction; Round 2: approve | Updated summary persisted; original summary discarded |
| CTL-ST-006 | exactly-three-rounds | Calibration completes on the 3rd round | State Transition | H | Reject round 1 & 2; approve round 3 | Entries written after round 3; no prompt for finalize/abort |
| CTL-ST-007 | exceed-three-rounds-prompt | System asks finalize or abort after 3 rounds | State Transition | H | Reject rounds 1-3 | CLI outputs finalize-or-abort prompt |
| CTL-ST-008 | calibration-abort | Developer chooses abort after exceeding limit | State Transition | H | Reject rounds 1-3; user input: abort | No entries written; CLI exits cleanly |
| CTL-ST-009 | add-entry-during-calibration | Developer adds new entry not in original draft | State Transition | M | Round 2: add extra entry then approve | All entries (original + added) persisted |
| CTL-ST-010 | artifact-created-at-correct-path | Artifact file exists at expected path | HP | M | Run capture for PR #42 | File exists at .runtime/control-logs/pr-42.md |
| CTL-ST-011 | artifact-contains-all-sections | Artifact includes sections 0-11 in order | HP | H | Run capture, read output file | Sections 0 through 11 present and in sequence |
| CTL-ST-012 | artifact-path-uses-pr-number | Different PRs produce distinct artifact files | EP | M | Run capture for PR #1 and PR #2 | pr-1.md and pr-2.md are distinct files |
| CTL-ST-013 | count-matches-written-entries | Output count equals persisted row count | HP | H | Write 3 entries, approve all | CLI outputs "3 entries written"; DB has 3 rows |
| CTL-ST-014 | stats-happy-path | Normal statistics output with entries present | HP | H | DB with 10 entries of mixed category | 4 metrics + total_entries all present and non-null |
| CTL-ST-015 | stats-by-category | One row per category in grouped output | HP | M | Entries spanning 3 categories | Output has exactly 3 rows; one per category |
| CTL-ST-016 | stats-by-project | One row per project in grouped output | HP | M | Entries spanning 2 projects | Output has exactly 2 rows; one per project |
| CTL-DT-001 | advice-no-rules | No advice when all metrics within thresholds | BVA | M | autonomy_ratio=0.30, deviation_ratio=0.20, verification_score=0.60, repeat_ops<3 | Output: "目前無建議" |
| CTL-DT-002 | advice-r1-triggers | R1 fires when autonomy_ratio exceeds 30% | BVA | H | autonomy_ratio=0.31 (above threshold) | R1 advice present in output |
| CTL-DT-003 | advice-r1-at-boundary | R1 does not fire at exactly 30% | BVA | H | autonomy_ratio=0.30 (at threshold) | R1 advice absent |
| CTL-DT-004 | advice-r2-triggers | R2 fires when deviation_ratio exceeds 20% | BVA | H | deviation_ratio=0.21 (above threshold) | R2 advice present in output |
| CTL-DT-005 | advice-r2-at-boundary | R2 does not fire at exactly 20% | BVA | H | deviation_ratio=0.20 (at threshold) | R2 advice absent |
| CTL-DT-006 | advice-r3-triggers | R3 fires when same irreversible_op repeats 3+ times | BVA | H | irreversible_op="git push --force" repeated 3 times | R3 advice present in output |
| CTL-DT-007 | advice-r3-none-when-no-irreversible | R3 does not trigger when count is low | BVA | M | irreversible_op pattern repeated 2 times | R3 advice absent |
| CTL-DT-008 | advice-r4-triggers | R4 fires when verification_score falls below 60% | BVA | H | verification_score=0.59 (below threshold) | R4 advice present in output |
| CTL-DT-009 | advice-r4-at-boundary | R4 does not fire at exactly 60% | BVA | H | verification_score=0.60 (at threshold) | R4 advice absent |
| CTL-DT-010 | advice-multi-rule | Multiple rules trigger simultaneously | BVA | H | autonomy_ratio=0.35, deviation_ratio=0.25, verification_score=0.50 | R1, R2, R4 all present in output |
| CTL-DT-011 | advice-insufficient-data | Fewer than 3 entries suppresses all rules | EP | H | DB with 2 entries; any ratio breaching threshold | Output contains data-insufficiency note; no R1-R4 |
| CTL-DT-012 | stats-division-by-zero-autonomy | autonomy_ratio is None when denominator is zero | EG | H | DB with 0 total entries | autonomy_ratio=None (or N/A in text output) |
| CTL-DT-013 | stats-division-by-zero-verification | verification_score is None when no verification entries | EG | H | DB with entries but none with verification category | verification_score=None |
| CTL-DT-014 | stats-empty-window | No entries in the time window | EG | M | DB with entries outside requested window | total_entries=0; all ratios None |
| CTL-DT-015 | stats-by-category-empty | No entries with grouping flag applied | EG | M | DB is empty; --by category | Output is empty table or "no data" message |
| CTL-EG-001 | artifact-not-committed | Artifact path is gitignored | EG | H | Check .gitignore for .runtime/control-logs/ | Pattern present in .gitignore; git status shows untracked (not staged) |
| CTL-CV-001 | stats-json-output | JSON flag produces machine-parseable output | HP | M | Run stats --json | Output is valid JSON; contains keys: autonomy_ratio, deviation_ratio, verification_score, total_entries |
| SMK-001 | write-and-count | End-to-end: write 1 entry, confirm count=1 | HP | H | Minimal entry; approve immediately | Exit 0; DB has 1 row; CLI prints count=1 |
| SMK-002 | stats-smoke | End-to-end: run stats on populated DB | HP | H | DB with 5 approved entries | Exit 0; 4 metrics present; no crash |

---

## Coverage Analysis

| Scenario Slug | Capability | TC-ID(s) | Status |
|--------------|------------|----------|--------|
| infer-autonomous-decision | control-log-capture | CTL-ST-001 | ✓ |
| infer-multiple-categories | control-log-capture | CTL-ST-002 | ✓ |
| infer-required-fields-present | control-log-capture | CTL-VL-002 | ✓ |
| infer-no-agent-commits | control-log-capture | CTL-ST-003 | ✓ |
| write-minimal-entry | control-log-capture | CTL-VL-003 | ✓ |
| write-entry-with-all-optional-fields | control-log-capture | CTL-VL-004 | ✓ |
| optional-fields-null | control-log-capture | CTL-DB-002 | ✓ |
| invalid-category-rejected | control-log-capture | CTL-VL-001 | ✓ |
| idempotent-db-init | control-log-capture | CTL-DB-001 | ✓ |
| approve-on-first-round | control-log-capture | CTL-ST-004 | ✓ |
| reject-entry-not-written | control-log-capture | CTL-DB-003 | ✓ |
| modify-summary-then-approve | control-log-capture | CTL-ST-005 | ✓ |
| exactly-three-rounds | control-log-capture | CTL-ST-006 | ✓ |
| exceed-three-rounds-prompt | control-log-capture | CTL-ST-007 | ✓ |
| calibration-abort | control-log-capture | CTL-ST-008 | ✓ |
| add-entry-during-calibration | control-log-capture | CTL-ST-009 | ✓ |
| artifact-created-at-correct-path | control-log-capture | CTL-ST-010 | ✓ |
| artifact-contains-all-sections | control-log-capture | CTL-ST-011 | ✓ |
| artifact-not-committed | control-log-capture | CTL-EG-001 | ✓ |
| artifact-path-uses-pr-number | control-log-capture | CTL-ST-012 | ✓ |
| count-matches-written-entries | control-log-capture | CTL-ST-013 | ✓ |
| zero-entries-after-all-rejected | control-log-capture | CTL-DB-004 | ✓ |
| stats-happy-path | control-log-analytics | CTL-ST-014, SMK-002 | ✓ |
| stats-json-output | control-log-analytics | CTL-CV-001 | ✓ |
| stats-division-by-zero-autonomy | control-log-analytics | CTL-DT-012 | ✓ |
| stats-division-by-zero-verification | control-log-analytics | CTL-DT-013 | ✓ |
| stats-empty-window | control-log-analytics | CTL-DT-014 | ✓ |
| stats-by-category | control-log-analytics | CTL-ST-015 | ✓ |
| stats-by-project | control-log-analytics | CTL-ST-016 | ✓ |
| stats-by-category-empty | control-log-analytics | CTL-DT-015 | ✓ |
| advice-r1-triggers | control-log-analytics | CTL-DT-002, CTL-DT-003 | ✓ |
| advice-r2-triggers | control-log-analytics | CTL-DT-004, CTL-DT-005 | ✓ |
| advice-r3-triggers | control-log-analytics | CTL-DT-006 | ✓ |
| advice-r4-triggers | control-log-analytics | CTL-DT-008, CTL-DT-009 | ✓ |
| advice-no-rules | control-log-analytics | CTL-DT-001 | ✓ |
| advice-multi-rule | control-log-analytics | CTL-DT-010 | ✓ |
| advice-insufficient-data | control-log-analytics | CTL-DT-011 | ✓ |
| advice-r3-none-when-no-irreversible | control-log-analytics | CTL-DT-007 | ✓ |

### Acceptance Criteria Coverage

| AC-ID | TC-ID(s) | Status |
|-------|----------|--------|
| AC-001-1 | CTL-ST-001, CTL-ST-002 | ✓ |
| AC-001-2 | CTL-VL-002 | ✓ |
| AC-001-3 | CTL-DB-003 | ✓ |
| AC-001-4 | CTL-ST-013 | ✓ |
| AC-002-1 | CTL-ST-005, CTL-ST-006 | ✓ |
| AC-002-2 | CTL-ST-007, CTL-ST-008 | ✓ |
| AC-002-3 | CTL-ST-011 | ✓ |
| AC-002-4 | CTL-EG-001 | ✓ |
| AC-003-1 | CTL-ST-014 | ✓ |
| AC-003-2 | CTL-CV-001 | ✓ |
| AC-003-3 | CTL-DT-012, CTL-DT-013 | ✓ |
| AC-003-4 | CTL-ST-015 | ✓ |
| AC-003-5 | CTL-ST-016 | ✓ |
| AC-004-1 | CTL-DT-002, CTL-DT-003 | ✓ |
| AC-004-2 | CTL-DT-004, CTL-DT-005 | ✓ |
| AC-004-3 | CTL-DT-006, CTL-DT-007 | ✓ |
| AC-004-4 | CTL-DT-008, CTL-DT-009 | ✓ |
| AC-004-5 | CTL-DT-001 | ✓ |
| AC-004-6 | CTL-DT-011 | ✓ |

---

## pytest Trace

```python
class TestControlLogDB:
    def test_ctl_db_001_idempotent_db_init(self) -> None:
        """CTL-DB-001: idempotent-db-init"""

    def test_ctl_db_002_optional_fields_null(self) -> None:
        """CTL-DB-002: optional-fields-null"""

    def test_ctl_db_003_reject_entry_not_written(self) -> None:
        """CTL-DB-003: reject-entry-not-written"""

    def test_ctl_db_004_zero_entries_after_all_rejected(self) -> None:
        """CTL-DB-004: zero-entries-after-all-rejected"""


class TestControlLogValidation:
    def test_ctl_vl_001_invalid_category_rejected(self) -> None:
        """CTL-VL-001: invalid-category-rejected"""

    def test_ctl_vl_002_infer_required_fields_present(self) -> None:
        """CTL-VL-002: infer-required-fields-present"""

    def test_ctl_vl_003_write_minimal_entry(self) -> None:
        """CTL-VL-003: write-minimal-entry"""

    def test_ctl_vl_004_write_entry_with_all_optional_fields(self) -> None:
        """CTL-VL-004: write-entry-with-all-optional-fields"""


class TestControlLogService:
    def test_ctl_st_001_infer_autonomous_decision(self) -> None:
        """CTL-ST-001: infer-autonomous-decision"""

    def test_ctl_st_002_infer_multiple_categories(self) -> None:
        """CTL-ST-002: infer-multiple-categories"""

    def test_ctl_st_003_infer_no_agent_commits(self) -> None:
        """CTL-ST-003: infer-no-agent-commits"""

    def test_ctl_st_004_approve_on_first_round(self) -> None:
        """CTL-ST-004: approve-on-first-round"""

    def test_ctl_st_005_modify_summary_then_approve(self) -> None:
        """CTL-ST-005: modify-summary-then-approve"""

    def test_ctl_st_006_exactly_three_rounds(self) -> None:
        """CTL-ST-006: exactly-three-rounds"""

    def test_ctl_st_007_exceed_three_rounds_prompt(self) -> None:
        """CTL-ST-007: exceed-three-rounds-prompt"""

    def test_ctl_st_008_calibration_abort(self) -> None:
        """CTL-ST-008: calibration-abort"""

    def test_ctl_st_009_add_entry_during_calibration(self) -> None:
        """CTL-ST-009: add-entry-during-calibration"""

    def test_ctl_st_010_artifact_created_at_correct_path(self) -> None:
        """CTL-ST-010: artifact-created-at-correct-path"""

    def test_ctl_st_011_artifact_contains_all_sections(self) -> None:
        """CTL-ST-011: artifact-contains-all-sections"""

    def test_ctl_st_012_artifact_path_uses_pr_number(self) -> None:
        """CTL-ST-012: artifact-path-uses-pr-number"""

    def test_ctl_st_013_count_matches_written_entries(self) -> None:
        """CTL-ST-013: count-matches-written-entries"""

    def test_ctl_st_014_stats_happy_path(self) -> None:
        """CTL-ST-014: stats-happy-path"""

    def test_ctl_st_015_stats_by_category(self) -> None:
        """CTL-ST-015: stats-by-category"""

    def test_ctl_st_016_stats_by_project(self) -> None:
        """CTL-ST-016: stats-by-project"""


class TestControlLogDecisionTable:
    def test_ctl_dt_001_advice_no_rules(self) -> None:
        """CTL-DT-001: advice-no-rules"""

    def test_ctl_dt_002_advice_r1_triggers(self) -> None:
        """CTL-DT-002: advice-r1-triggers"""

    def test_ctl_dt_003_advice_r1_at_boundary(self) -> None:
        """CTL-DT-003: advice-r1-at-boundary"""

    def test_ctl_dt_004_advice_r2_triggers(self) -> None:
        """CTL-DT-004: advice-r2-triggers"""

    def test_ctl_dt_005_advice_r2_at_boundary(self) -> None:
        """CTL-DT-005: advice-r2-at-boundary"""

    def test_ctl_dt_006_advice_r3_triggers(self) -> None:
        """CTL-DT-006: advice-r3-triggers"""

    def test_ctl_dt_007_advice_r3_none_when_no_irreversible(self) -> None:
        """CTL-DT-007: advice-r3-none-when-no-irreversible"""

    def test_ctl_dt_008_advice_r4_triggers(self) -> None:
        """CTL-DT-008: advice-r4-triggers"""

    def test_ctl_dt_009_advice_r4_at_boundary(self) -> None:
        """CTL-DT-009: advice-r4-at-boundary"""

    def test_ctl_dt_010_advice_multi_rule(self) -> None:
        """CTL-DT-010: advice-multi-rule"""

    def test_ctl_dt_011_advice_insufficient_data(self) -> None:
        """CTL-DT-011: advice-insufficient-data"""

    def test_ctl_dt_012_stats_division_by_zero_autonomy(self) -> None:
        """CTL-DT-012: stats-division-by-zero-autonomy"""

    def test_ctl_dt_013_stats_division_by_zero_verification(self) -> None:
        """CTL-DT-013: stats-division-by-zero-verification"""

    def test_ctl_dt_014_stats_empty_window(self) -> None:
        """CTL-DT-014: stats-empty-window"""

    def test_ctl_dt_015_stats_by_category_empty(self) -> None:
        """CTL-DT-015: stats-by-category-empty"""


class TestControlLogEdgeCases:
    def test_ctl_eg_001_artifact_not_committed(self) -> None:
        """CTL-EG-001: artifact-not-committed"""


class TestControlLogConversion:
    def test_ctl_cv_001_stats_json_output(self) -> None:
        """CTL-CV-001: stats-json-output"""


class TestControlLogSmoke:
    def test_smk_001_write_and_count(self) -> None:
        """SMK-001: write-and-count"""

    def test_smk_002_stats_smoke(self) -> None:
        """SMK-002: stats-smoke"""
```

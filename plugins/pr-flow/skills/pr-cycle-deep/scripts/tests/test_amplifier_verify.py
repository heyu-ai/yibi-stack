"""Tests for plugins/pr-flow/skills/pr-cycle-deep/scripts/amplifier-verify.py.

Locks the TC-ID parser so it accepts BOTH testplan conventions:
  3-part  PREFIX-CATEGORY-NUMBER  (YIBI-NFC-001, FBAUTH-UNIT-01)
  2-part  PREFIX-CAT+NUMBER       (FBAUTH-U01, FBAUTH-I12, SMK-001)

Regression: a 2-part testplan (e.g. change 0032's FBAUTH-U01) previously made
parse_tc_table return zero rows, so amplifier-verify exited 2 with a spurious
"no TC table" against a perfectly valid testplan.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "amplifier-verify.py"
_spec = importlib.util.spec_from_file_location("amplifier_verify", _SCRIPT)
amplifier_verify = importlib.util.module_from_spec(_spec)
# Register before exec so the module's @dataclass decorators can resolve
# sys.modules[cls.__module__] during class creation.
sys.modules["amplifier_verify"] = amplifier_verify
_spec.loader.exec_module(amplifier_verify)


def test_tc_id_regex_accepts_two_part_ids():
    rx = amplifier_verify._TC_ID_RE
    for tc in ("FBAUTH-U01", "FBAUTH-I12", "FBAUTH-W04", "SMK-001"):
        m = rx.search(tc)
        assert m is not None and m.group(0) == tc, tc


def test_tc_id_regex_still_accepts_three_part_ids():
    rx = amplifier_verify._TC_ID_RE
    for tc in ("YIBI-NFC-001", "FBAUTH-UNIT-01"):
        m = rx.search(tc)
        assert m is not None and m.group(0) == tc, tc


def test_parse_tc_table_two_part_ids():
    testplan = """\
## 1. TC Table

| TC-ID | Scenario Slug | Test Purpose |
|-------|--------------|-------------|
| FBAUTH-U01 | exchange-valid | verify claims |
| FBAUTH-I12 | lazy-backfill | backfill row |
| SMK-001 | smk-happy-path | endpoint alive |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["FBAUTH-U01", "FBAUTH-I12", "SMK-001"]
    assert rows[0].slug == "exchange-valid"


def test_parse_tc_table_three_part_ids():
    testplan = """\
## 1. TC Table

| TC-ID | Scenario Slug | Test Purpose |
|-------|--------------|-------------|
| YIBI-NFC-001 | bind-device | bind |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["YIBI-NFC-001"]

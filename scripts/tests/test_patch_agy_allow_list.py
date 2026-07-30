"""PATCHAGY-DT-* tests for scripts/patch_agy_allow_list.py.

Covers the migration logic AC-3 depends on (PR #367 mob review Important — this
migration had zero test coverage despite mutating a user's global settings.json).
scripts/ is not a package, so the module is loaded by path via importlib.
"""

import importlib.util
import json
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parent.parent / "patch_agy_allow_list.py"
_spec = importlib.util.spec_from_file_location("patch_agy_allow_list", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
patch_agy_allow_list = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch_agy_allow_list)


def _write_settings(tmp_path: Path, allow: list[str]) -> Path:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"permissions": {"allow": allow}}, indent=2), encoding="utf-8"
    )
    return settings_path


def _read_allow(settings_path: Path) -> list[str]:
    return json.loads(settings_path.read_text(encoding="utf-8"))["permissions"]["allow"]


def test_patchagy_dt_001_fresh_install_adds_all_five_entries(tmp_path: Path) -> None:
    """PATCHAGY-DT-001: an empty allow list gets all 5 new entries, nothing to remove."""
    settings_path = _write_settings(tmp_path, [])

    patch_agy_allow_list.main(settings_path=settings_path)

    allow = _read_allow(settings_path)
    for entry in patch_agy_allow_list.ENTRIES_TO_ADD:
        assert entry in allow
    assert len(allow) == len(patch_agy_allow_list.ENTRIES_TO_ADD)


def test_patchagy_dt_002_pre_migration_install_removes_old_adds_new(tmp_path: Path) -> None:
    """PATCHAGY-DT-002: a pre-split install's broad grant and stale path are both removed."""
    settings_path = _write_settings(
        tmp_path,
        [
            "Bash(agy:*)",
            "Bash(bash /Users/x/.agents/skills/agy/scripts/run.sh:*)",
            "Bash(unrelated:*)",
        ],
    )

    patch_agy_allow_list.main(settings_path=settings_path)

    allow = _read_allow(settings_path)
    for old_entry in patch_agy_allow_list.ENTRIES_TO_REMOVE:
        assert old_entry not in allow
    assert "Bash(unrelated:*)" in allow, "unrelated entries must survive the migration"
    for entry in patch_agy_allow_list.ENTRIES_TO_ADD:
        assert entry in allow


def test_patchagy_dt_003_duplicate_broad_grant_all_removed(tmp_path: Path) -> None:
    """PATCHAGY-DT-003: regression test for the fixed allow.remove() first-occurrence bug.

    PR #367 mob review Critical: `allow.remove(entry)` only removes the first match, so a
    settings.json with a duplicated `Bash(agy:*)` used to leave one copy behind while the
    script printed a false "[OK] Removed" line.
    """
    settings_path = _write_settings(tmp_path, ["Bash(agy:*)", "Bash(agy:*)", "Bash(keep-me)"])

    patch_agy_allow_list.main(settings_path=settings_path)

    allow = _read_allow(settings_path)
    assert "Bash(agy:*)" not in allow, "every occurrence of the broad grant must be removed"
    assert "Bash(keep-me)" in allow


def test_patchagy_dt_004_already_migrated_install_is_a_noop(tmp_path: Path) -> None:
    """PATCHAGY-DT-004: re-running against an already-migrated settings.json changes nothing."""
    settings_path = _write_settings(tmp_path, list(patch_agy_allow_list.ENTRIES_TO_ADD))
    before = settings_path.read_text(encoding="utf-8")

    patch_agy_allow_list.main(settings_path=settings_path)

    assert settings_path.read_text(encoding="utf-8") == before


def test_patchagy_dt_005_missing_settings_file_fails_loud(tmp_path: Path) -> None:
    """PATCHAGY-DT-005: a missing settings.json exits non-zero with a [FAIL] message."""
    missing_path = tmp_path / "does-not-exist.json"

    try:
        patch_agy_allow_list.main(settings_path=missing_path)
        raise AssertionError("expected SystemExit for a missing settings file")
    except SystemExit as e:
        assert e.code == 1

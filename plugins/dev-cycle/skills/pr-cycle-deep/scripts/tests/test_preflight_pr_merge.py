"""PRM：真實 pre-merge script 的 draft／live state 拒絕與讀回。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "preflight-pr-merge.sh"


def _run(
    tmp_path: Path, metadata: object, *, api_exit: int = 0
) -> subprocess.CompletedProcess[str]:
    response = tmp_path / "response.json"
    response.write_text(json.dumps(metadata), encoding="utf-8")
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" != pr ] || [ "$2" != view ] || [ "$3" != 7 ]; then exit 99; fi\n'
        'case "$*" in *isDraft*) ;; *) exit 98 ;; esac\n'
        'cat "$PR_RESPONSE"\n'
        'exit "$PR_EXIT"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return subprocess.run(
        ["bash", str(GATE), "7"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "PR_RESPONSE": str(response),
            "PR_EXIT": str(api_exit),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _metadata(**updates: object) -> dict[str, object]:
    return {
        "number": 7,
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "isDraft": False,
        **updates,
    }


def test_draft_clean_pr_blocks_until_live_readback_is_ready(tmp_path: Path) -> None:
    """PRM-ST-001: CLEAN 不代表非 draft；明確 ready 後仍須重新讀回才放行。"""
    draft = _run(tmp_path, _metadata(isDraft=True))
    assert draft.returncode == 3
    assert "[STOP]" in draft.stderr and "draft" in draft.stderr
    still_draft = _run(tmp_path, _metadata(isDraft=True))
    assert still_draft.returncode == 3
    ready = _run(tmp_path, _metadata())
    assert ready.returncode == 0, ready.stderr
    assert json.loads(ready.stdout)["isDraft"] is False


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"state": "MERGED", "isDraft": True}, 2),
        ({"state": "CLOSED"}, 2),
        ({"mergeable": "CONFLICTING"}, 4),
        ({"mergeStateStatus": "BEHIND"}, 4),
        ({"mergeStateStatus": "DIRTY"}, 4),
        ({"mergeable": "UNKNOWN", "mergeStateStatus": "UNKNOWN"}, 0),
        ({"mergeable": "unexpected"}, 1),
        ({"mergeable": None}, 1),
        ({"mergeStateStatus": "unexpected"}, 1),
        ({"mergeStateStatus": None}, 1),
        ({"isDraft": "false"}, 1),
        ({"isDraft": None}, 1),
        ({"number": 8}, 1),
        ({"state": "unknown"}, 1),
    ],
)
def test_gate_routes_live_state_and_rejects_malformed_metadata(
    tmp_path: Path, updates: dict[str, object], expected: int
) -> None:
    """PRM-DT-001: state 優先於 draft；API 型別錯誤不得當作 ready。"""
    assert _run(tmp_path, _metadata(**updates)).returncode == expected


def test_api_failure_does_not_use_even_valid_output(tmp_path: Path) -> None:
    """PRM-EG-001: API exit 非零不採用看似正常的 JSON。"""
    result = _run(tmp_path, _metadata(), api_exit=7)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "[FAIL]" in result.stderr


@pytest.mark.parametrize("missing", ["state", "isDraft", "mergeable", "mergeStateStatus"])
def test_missing_live_field_fails_closed(tmp_path: Path, missing: str) -> None:
    metadata = _metadata()
    del metadata[missing]
    result = _run(tmp_path, metadata)
    assert result.returncode == 1
    assert result.stdout == ""

"""RCP：真實 Git 與 CLI 下的 early checkpoint／resume 安全轉移。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "review_checkpoint.py"


def _case(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    root.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    for args in [
        ["init", "-q"],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "seed",
        ],
    ]:
        subprocess.run(
            ["git", *args], cwd=root, env=env, check=True, capture_output=True, timeout=20
        )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()
    response = tmp_path / "response.json"
    response.write_text(
        json.dumps({"number": 7, "state": "OPEN", "baseRefName": "main", "headRefOid": head})
    )
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\ncat "$PR_RESPONSE"\n')
    gh.chmod(0o755)
    env.update({"PATH": f"{tmp_path}{os.pathsep}{env['PATH']}", "PR_RESPONSE": str(response)})
    return root, env


def _run(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--pr", "7"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _ok(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _evidence(root: Path, head: str, result: str = "unchecked") -> None:
    (root / ".pr-review/red-first.md").write_text(
        f"<!-- red-first:{head} -->\nPR: 7\n"
        f"[WARN] red-first: no checker\nRED_FIRST_RESULT={result}\n"
    )


def test_interrupted_before_red_first_resumes_at_exact_next_step(tmp_path: Path) -> None:
    """RCP-ST-001: Step 1.7 前中斷後不要求尚不存在的 final 或 red-first。"""
    root, env = _case(tmp_path)
    _ok(_run(root, env, "start"))
    for step in ("Step 1.5", "Step 1.6", "Step 1.7"):
        if step != "Step 1.5":
            _ok(_run(root, env, "advance", "--next", step))
        resumed = _ok(_run(root, env, "resume"))
        assert resumed["next"] == step
        assert resumed["red_first"] == "not-run"
        assert not (root / ".pr-review/final.md").exists()
        assert not (root / ".pr-review/red-first.md").exists()


@pytest.mark.parametrize(
    "mutation", ["remote-head", "checkout-head", "wrong-pr", "wrong-base", "bad-json"]
)
def test_resume_never_adopts_changed_or_corrupt_identity(tmp_path: Path, mutation: str) -> None:
    """RCP-EG-001: identity 改變或不可解析時 fail closed，不覆寫 checkpoint。"""
    root, env = _case(tmp_path)
    state = _ok(_run(root, env, "start"))
    path = root / ".pr-review/state.md"
    if mutation == "remote-head":
        metadata = json.loads(Path(env["PR_RESPONSE"]).read_text())
        metadata["headRefOid"] = "a" * 40
        Path(env["PR_RESPONSE"]).write_text(json.dumps(metadata))
    elif mutation == "checkout-head":
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-qm",
                "moved",
            ],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            timeout=20,
        )
    else:
        if mutation == "wrong-pr":
            state["pr"] = 8
        if mutation == "wrong-base":
            state["base"] = "other"
        path.write_text("not JSON" if mutation == "bad-json" else json.dumps(state))
    before = path.read_bytes()
    result = _run(root, env, "resume")
    assert result.returncode == 2
    assert "[FAIL]" in result.stderr
    assert result.stdout == ""
    assert path.read_bytes() == before


def test_later_resume_preserves_unchecked_and_cannot_substitute_archived_final(
    tmp_path: Path,
) -> None:
    """RCP-ST-002: later resume 要有效證據；舊 final 與未裁決 disputed 不能繞過 Step 5。"""
    root, env = _case(tmp_path)
    state = _ok(_run(root, env, "start"))
    path = root / ".pr-review/state.md"
    state["next"] = "Step 3"
    path.write_text(json.dumps(state))
    assert _run(root, env, "resume").returncode == 2
    _evidence(root, state["head"])
    resumed = _ok(_run(root, env, "resume"))
    assert resumed["next"] == "Step 3" and resumed["red_first"] == "unchecked"
    outcomes = tmp_path / "voices.json"
    outcomes.write_text(
        json.dumps(
            {
                "claude": {"status": "success"},
                "codex": {"status": "success"},
                "gemini": {"status": "not-selected"},
            }
        )
    )
    _ok(_run(root, env, "voices", "--input", str(outcomes)))
    state = json.loads(path.read_text())
    state["next"] = "Step 6"
    path.write_text(json.dumps(state))
    (root / ".pr-review/final.prev.md").write_text("# Old final\n")
    assert _ok(_run(root, env, "resume"))["next"] == "Step 5"
    (root / ".pr-review/final.md").write_text("# Current final\n")
    state["disputed"] = [{"id": "finding-1", "ruling": None}]
    path.write_text(json.dumps(state))
    assert _ok(_run(root, env, "resume"))["next"] == "Step 5"
    state["disputed"][0]["ruling"] = "fix"
    path.write_text(json.dumps(state))
    assert _ok(_run(root, env, "resume"))["next"] == "Step 6"
    _evidence(root, state["head"], "error")
    assert _run(root, env, "resume").returncode == 2


def test_advance_cannot_skip_early_steps(tmp_path: Path) -> None:
    """RCP-DT-001: Step 1.5 不能直接跳到 reviewer dispatch。"""
    root, env = _case(tmp_path)
    _ok(_run(root, env, "start"))
    assert _run(root, env, "advance", "--next", "Step 3").returncode == 2
    assert _ok(_run(root, env, "resume"))["next"] == "Step 1.5"


def test_all_external_voices_failed_requires_explicit_current_round_approval(
    tmp_path: Path,
) -> None:
    """RCP-ST-003: 額度與 502 失敗不等於 mob；裁決不能沿用到另一輪。"""
    root, env = _case(tmp_path)
    state = _ok(_run(root, env, "start"))
    path = root / ".pr-review/state.md"
    state["next"] = "Step 3"
    path.write_text(json.dumps(state))
    _evidence(root, state["head"])
    source = tmp_path / "outcomes.json"
    source.write_text(
        json.dumps(
            {
                "claude": {"status": "success"},
                "codex": {"status": "unavailable", "reason": "usage limit"},
                "gemini": {"status": "unavailable", "reason": "HTTP 502"},
            }
        )
    )
    args = ("voices", "--input", str(source))
    blocked = _run(root, env, *args)
    assert blocked.returncode == 3
    result = json.loads(blocked.stdout)
    assert result["mode"] == "claude-only"
    assert result["active_voices"] == ["claude"]
    assert result["voice_failures"] == {"codex": "usage limit", "gemini": "HTTP 502"}
    assert "no cross-model family review" in result["voice_summary"]
    assert _run(root, env, "advance", "--next", "Step 5").returncode == 2
    approved = _ok(_run(root, env, *args, "--allow-claude-only"))
    assert approved["claude_only_approved"] is True
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    assert _ok(_run(root, env, "resume"))["voice_summary"] == approved["voice_summary"]
    state = json.loads(path.read_text())
    state.update(next="Step 3", review_round=2)
    path.write_text(json.dumps(state))
    assert _run(root, env, *args, "--round", "2").returncode == 3
    assert json.loads(path.read_text())["claude_only_approved"] is False


@pytest.mark.parametrize("external", ["codex", "gemini"])
def test_surviving_external_voice_reports_two_not_cached_three(
    tmp_path: Path, external: str
) -> None:
    """RCP-DT-002: 真實成功 2 家就是 2-voice，失敗原因不得遺失。"""
    root, env = _case(tmp_path)
    _ok(_run(root, env, "start"))
    source = tmp_path / "outcomes.json"
    data = {
        "claude": {"status": "success"},
        "codex": {"status": "unavailable", "reason": "quota"},
        "gemini": {"status": "unavailable", "reason": "502"},
    }
    data[external] = {"status": "success"}
    source.write_text(json.dumps(data))
    result = _ok(_run(root, env, "voices", "--input", str(source)))
    assert result["mode"] == "2-voice-mob"
    assert set(result["active_voices"]) == {"claude", external}
    assert "2/3" in result["voice_summary"]
    assert result["claude_only_approved"] is False


def test_read_only_voice_report_does_not_create_lifecycle_checkpoint(tmp_path: Path) -> None:
    """RCP-EG-002: review-only 可產審查報告，但不建立可進入 fix 的 state.md。"""
    root, env = _case(tmp_path)
    (root / ".pr-review").mkdir()
    source = tmp_path / "outcomes.json"
    source.write_text(
        json.dumps(
            {
                "claude": {"status": "success"},
                "codex": {"status": "success"},
                "gemini": {"status": "success"},
            }
        )
    )
    result = _ok(_run(root, env, "voices", "--input", str(source), "--read-only"))
    assert result["mode"] == "3-voice-full-mob"
    assert not (root / ".pr-review/state.md").exists()
    report = json.loads((root / ".pr-review/voice-status.json").read_text())
    assert report["active_voices"] == ["claude", "codex", "gemini"]

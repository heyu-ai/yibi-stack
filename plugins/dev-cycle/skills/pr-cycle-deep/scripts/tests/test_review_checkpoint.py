"""真實 CLI／Git checkpoint 行為；只替換外部 gh 邊界。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "review_checkpoint.py"
URL = "https://github.com/owner/project/pull/7"


def _git(root: Path, env: dict[str, str], *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True, timeout=20
    ).stdout.strip()


def _case(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    root.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    _git(root, env, "init", "-q")
    _git(
        root,
        env,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "seed",
    )
    response = tmp_path / "response.json"
    response.write_text(
        json.dumps(
            {
                "number": 7,
                "url": URL,
                "state": "OPEN",
                "baseRefName": "main",
                "headRefOid": _git(root, env, "rev-parse", "HEAD"),
            }
        )
    )
    checks = tmp_path / "checks.json"
    checks.write_text(json.dumps([{"name": "ci", "bucket": "pass"}]))
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/sh\nif [ "$1" != pr ]; then exit 99; fi\n'
        'case "$2" in\nview) cat "$PR_RESPONSE" ;;\n'
        'checks) cat "$PR_CHECKS" ;;\n*) exit 98 ;;\nesac\n'
    )
    gh.chmod(0o755)
    env.update(
        {
            "PATH": f"{tmp_path}{os.pathsep}{env['PATH']}",
            "PR_RESPONSE": str(response),
            "PR_CHECKS": str(checks),
        }
    )
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


def _state(root: Path) -> dict:
    return json.loads((root / ".pr-review/state.md").read_text())


def _metadata(env: dict[str, str], **updates: object) -> None:
    path = Path(env["PR_RESPONSE"])
    path.write_text(json.dumps({**json.loads(path.read_text()), **updates}))


def _evidence(root: Path, head: str, result: str = "unchecked") -> None:
    (root / ".pr-review/red-first.md").write_text(
        f"<!-- red-first:{head} -->\nPR: 7\n"
        f"[WARN] red-first: no checker\nRED_FIRST_RESULT={result}\n"
    )


def _review_boundary(root: Path, env: dict[str, str]) -> dict:
    state = _ok(_run(root, env, "start"))
    for step in ("Step 1.6", "Step 1.7"):
        _ok(_run(root, env, "advance", "--next", step))
    _evidence(root, state["head"])
    for step in ("Step 2", "Step 3"):
        _ok(_run(root, env, "advance", "--next", step))
    return state


def _outcomes(
    root: Path,
    env: dict[str, str],
    *,
    statuses: dict | None = None,
    phase: str = "r1",
    read_only: bool = False,
) -> Path:
    flags = ("--read-only",) if read_only else ()
    attempt = _ok(_run(root, env, "begin-attempt", "--phase", phase, *flags))["identity"]
    outcomes = {
        "claude": {"status": "success"},
        "codex": {"status": "success"},
        "gemini": {"status": "not-selected"},
    }
    outcomes.update(statuses or {})
    for name, item in outcomes.items():
        if item["status"] == "success":
            path = root / ".pr-review" / f"{name}-{phase}.md"
            header = (
                "<!-- review-evidence:"
                + json.dumps({**attempt, "voice": name}, sort_keys=True)
                + " -->\n"
            )
            body = (
                f"Review scope: {attempt['pr_url']} head={attempt['head']} "
                f"pass={attempt['review_round']} phase={phase} attempt={attempt['attempt']}\n"
                f"## {'Summary' if phase == 'r1' else 'Cross-review verdict'}\n"
                f"Reviewed {attempt['head']} with current attempt {attempt['attempt']} by {name}.\n"
                + (
                    "## Findings\nNone.\n## Verdict\n- LGTM\n"
                    if phase == "r1"
                    else "## Per-finding response\nAll reviewed.\n"
                    "## New findings (missed in R1)\nNone.\n"
                    "## Withdrawals (R1 items I'm retracting)\nNone.\n## Final verdict\n- LGTM\n"
                )
            )
            path.write_text(header + body)
            item.update(report=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    source = root / ".pr-review" / f"outcomes-{phase}.json"
    source.write_text(json.dumps({"identity": attempt, "outcomes": outcomes}))
    return source


def _voices(root: Path, env: dict[str, str], **kwargs: object) -> dict:
    source = _outcomes(root, env, **kwargs)
    flags = ("--read-only",) if kwargs.get("read_only") else ()
    return _ok(
        _run(
            root,
            env,
            "voices",
            "--phase",
            str(kwargs.get("phase", "r1")),
            "--input",
            str(source),
            *flags,
        )
    )


def _aggregate(
    root: Path, env: dict[str, str], *, blocking: bool = False, disputed: list | None = None
) -> dict:
    resumed = _ok(_run(root, env, "resume"))
    marker = (
        "<!-- checkpoint-final:" + json.dumps(resumed["final_identity"], sort_keys=True) + " -->\n"
    )
    (root / ".pr-review/final.md").write_text(
        marker
        + "# Final\nCurrent review synthesis; blockers and disputes are explicitly recorded.\n"
    )
    if not _state(root).get("baseline"):
        _ok(_run(root, env, "baseline"))
    source = root / ".pr-review/aggregation.json"
    source.write_text(json.dumps({"blocking": blocking, "disputed": disputed or []}))
    return _ok(_run(root, env, "checkpoint", "--input", str(source)))


def _late(
    root: Path, env: dict[str, str], *, blocking: bool = False, disputed: list | None = None
) -> dict:
    _review_boundary(root, env)
    _voices(root, env)
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    return _aggregate(root, env, blocking=blocking, disputed=disputed)


def _route(root: Path, env: dict[str, str], target: str) -> dict:
    for step in ("Step 5b", "Step 5c", target):
        result = _ok(_run(root, env, "advance", "--next", step))
    return result


def _move(root: Path, env: dict[str, str]) -> str:
    _git(
        root,
        env,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "fix",
    )
    head = _git(root, env, "rev-parse", "HEAD")
    _metadata(env, headRefOid=head)
    return head


def _unchanged_failure(
    root: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    path = root / ".pr-review/state.md"
    before = path.read_bytes()
    result = _run(root, env, *args)
    assert result.returncode == 2, result.stdout
    assert path.read_bytes() == before
    return result


def test_early_threshold_and_original_capture(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    state = _ok(_run(root, env, "start"))
    for step in ("Step 1.5", "Step 1.6", "Step 1.7"):
        if step != "Step 1.5":
            _ok(_run(root, env, "advance", "--next", step))
        assert _ok(_run(root, env, "resume"))["red_first"] == "not-run"
    _unchanged_failure(root, env, "advance", "--next", "Step 2")
    _evidence(root, state["head"])
    _ok(_run(root, env, "advance", "--next", "Step 2"))
    result = _ok(_run(root, env, "resume"))
    assert result["red_first"] == "unchecked" and result["captured_head"] == state["head"]
    _evidence(root, "b" * 40)
    _unchanged_failure(root, env, "resume")


@pytest.mark.parametrize(
    "mutation",
    [
        "remote-head",
        "checkout-head",
        "synchronized-head",
        "repo",
        "pr",
        "base",
        "bad-json",
        "schema",
        "legacy",
    ],
)
def test_identity_changes_reject_without_rewriting(tmp_path: Path, mutation: str) -> None:
    root, env = _case(tmp_path)
    state = _ok(_run(root, env, "start"))
    path = root / ".pr-review/state.md"
    if mutation == "remote-head":
        _metadata(env, headRefOid="a" * 40)
    elif mutation in ("checkout-head", "synchronized-head"):
        _move(root, env)
        if mutation == "checkout-head":
            _metadata(env, headRefOid=state["head"])
    elif mutation == "repo":
        env["GH_REPO"] = "different/project"
        _metadata(env, url="https://github.com/different/project/pull/7")
    elif mutation == "base":
        _metadata(env, baseRefName="elsewhere")
    elif mutation == "pr":
        state["pr"] = 8
        path.write_text(json.dumps(state))
    elif mutation == "schema":
        state["schema_version"] = 2
        path.write_text(json.dumps(state))
    else:
        path.write_text("not-json" if mutation == "bad-json" else "pr: 7\nnext: Step 6\n")
    result = _unchanged_failure(root, env, "resume")
    assert "[FAIL]" in result.stderr
    if mutation in ("schema", "legacy", "bad-json"):
        assert "--resume" in result.stderr


@pytest.mark.parametrize(
    "action",
    [
        "advance",
        "begin-attempt",
        "voices",
        "verify-voices",
        "configure-ci",
        "baseline",
        "checkpoint",
        "post-fix",
        "new-pass",
        "human-review",
        "ci",
    ],
)
def test_every_action_checks_canonical_repository(tmp_path: Path, action: str) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    _metadata(env, url="https://github.com/owner/other/pull/7")
    _unchanged_failure(root, env, action)


def test_explicit_repo_must_match_url(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    assert _run(root, env, "start", "--repo", "owner/other").returncode == 2
    assert not (root / ".pr-review/state.md").exists()
    assert _ok(_run(root, env, "start", "--repo", "owner/project"))["pr_url"] == URL


@pytest.mark.parametrize("target", ["Step 3", "Step 5a", "Step 8", "Step 10", "Step 11"])
def test_arbitrary_step_jumps_rejected(tmp_path: Path, target: str) -> None:
    root, env = _case(tmp_path)
    _ok(_run(root, env, "start"))
    _unchanged_failure(root, env, "advance", "--next", target)


def test_step4_requires_current_voices_and_step5a_current_final(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    _unchanged_failure(root, env, "advance", "--next", "Step 4")
    _voices(root, env)
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    _unchanged_failure(root, env, "advance", "--next", "Step 5a")
    source = root / ".pr-review/aggregation.json"
    source.write_text(json.dumps({"blocking": False, "disputed": []}))
    _ok(_run(root, env, "baseline"))
    (root / ".pr-review/final.prev.md").write_text("old final\n")
    _unchanged_failure(root, env, "checkpoint", "--input", str(source))
    _aggregate(root, env)
    (root / ".pr-review/final.md").unlink()
    assert _ok(_run(root, env, "resume"))["next"] == "Step 5"
    _unchanged_failure(root, env, "advance", "--next", "Step 5b")
    _aggregate(root, env)
    assert _ok(_run(root, env, "resume"))["next"] == "Step 5a"


@pytest.mark.parametrize(
    "mutation", ["outcome", "report", "status-publication", "approval", "head", "pass"]
)
def test_consumers_revalidate_outcome_report_and_approval(tmp_path: Path, mutation: str) -> None:
    root, env = _case(tmp_path)
    _late(root, env)
    state = _state(root)
    if mutation == "outcome":
        source = Path(state["voice_decisions"]["r1"]["source"])
        payload = json.loads(source.read_text())
        payload["outcomes"]["codex"] = {
            "status": "unavailable",
            "reason": "quota changed after decision",
        }
        source.write_text(json.dumps(payload))
    elif mutation == "report":
        (root / ".pr-review/codex-r1.md").write_text("old/stale replacement\n")
    elif mutation == "status-publication":
        (root / ".pr-review/voice-status.json").write_text("{}")
    else:
        if mutation == "head":
            state["voice_decisions"]["r1"]["identity"]["head"] = "a" * 40
        elif mutation == "pass":
            state["review_round"] = 2
        else:
            state["voice_decisions"]["r1"]["active_voices"] = ["claude"]
            state["voice_decisions"]["r1"]["claude_only_approved"] = True
        (root / ".pr-review/state.md").write_text(json.dumps(state))
    _unchanged_failure(root, env, "resume")
    _unchanged_failure(root, env, "advance", "--next", "Step 5b")


@pytest.mark.parametrize("target", ["Step 4", "Step 5"])
def test_changed_latest_outcome_cannot_advance_from_step3(tmp_path: Path, target: str) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    _voices(root, env)
    source = root / ".pr-review/outcomes-r1.json"
    payload = json.loads(source.read_text())
    payload["outcomes"]["codex"] = {"status": "unavailable", "reason": "quota after saved decision"}
    source.write_text(json.dumps(payload))
    _unchanged_failure(root, env, "advance", "--next", target)


def test_exhaustion_stops_until_explicit_bound_approval_and_retry_invalidates(
    tmp_path: Path,
) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    source = _outcomes(
        root,
        env,
        statuses={
            "codex": {"status": "unavailable", "reason": "usage limit"},
            "gemini": {"status": "unavailable", "reason": "HTTP 502"},
        },
    )
    result = _run(root, env, "voices", "--input", str(source))
    assert result.returncode == 3
    status = json.loads(result.stdout)
    assert status["mode"] == "claude-only" and status["voice_failures"] == {
        "codex": "usage limit",
        "gemini": "HTTP 502",
    }
    _unchanged_failure(root, env, "advance", "--next", "Step 5")
    assert _ok(_run(root, env, "voices", "--input", str(source), "--allow-claude-only"))[
        "claude_only_approved"
    ]
    _ok(_run(root, env, "begin-attempt"))
    assert _state(root)["voice_decisions"] == {}
    assert _state(root)["voice_history"][0]["voice_failures"]["gemini"] == "HTTP 502"
    _unchanged_failure(root, env, "voices", "--input", str(source), "--allow-claude-only")
    _unchanged_failure(root, env, "advance", "--next", "Step 5")


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "missing-reason",
        "claude-failed",
        "static-outcomes",
        "wrong-report-head",
        "report-hash",
        "partial-report",
        "old-body-restamp",
    ],
)
def test_creation_provenance_rejects_invalid_or_restamped_success(
    tmp_path: Path, mutation: str
) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    if mutation == "old-body-restamp":
        first = _outcomes(root, env)
        old = json.loads(first.read_text())
        _ok(_run(root, env, "voices", "--input", str(first)))
        current = _ok(_run(root, env, "begin-attempt"))["identity"]
        old["identity"] = current
        for name in ("claude", "codex"):
            path = Path(old["outcomes"][name]["report"])
            body = path.read_text().split("\n", 1)[1]
            body = (
                f"Review scope: {current['pr_url']} head={current['head']} "
                f"pass={current['review_round']} phase=r1 attempt={current['attempt']}\n"
                + body.split("\n", 1)[1]
            )
            path.write_text(
                "<!-- review-evidence:" + json.dumps({**current, "voice": name}) + " -->\n" + body
            )
            old["outcomes"][name]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        first.write_text(json.dumps(old))
        source = first
    else:
        source = _outcomes(root, env)
        payload = json.loads(source.read_text())
        if mutation == "status":
            payload["outcomes"]["codex"]["status"] = "cached-auth-ok"
        elif mutation == "missing-reason":
            payload["outcomes"]["codex"] = {"status": "unavailable", "reason": " "}
        elif mutation == "claude-failed":
            payload["outcomes"]["claude"] = {"status": "unavailable", "reason": "review failed"}
        elif mutation == "static-outcomes":
            payload = payload["outcomes"]
        elif mutation == "report-hash":
            payload["outcomes"]["codex"]["sha256"] = "0" * 64
        elif mutation == "partial-report":
            path = Path(payload["outcomes"]["codex"]["report"])
            path.write_bytes(path.read_bytes().split(b"\n", 1)[0] + b"\n")
            payload["outcomes"]["codex"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif mutation == "wrong-report-head":
            path = Path(payload["outcomes"]["codex"]["report"])
            raw = path.read_text().replace(payload["identity"]["head"], "b" * 40)
            path.write_text(raw)
            payload["outcomes"]["codex"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        source.write_text(json.dumps(payload))
    _unchanged_failure(root, env, "voices", "--input", str(source))
    _unchanged_failure(root, env, "advance", "--next", "Step 5")


def test_report_publication_failure_cannot_admit_stale_mode(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    source = _outcomes(root, env)
    destination = root / ".pr-review/voice-status.json"
    destination.mkdir()
    (destination / "not-a-file").write_text("real replacement failure")
    _unchanged_failure(root, env, "voices", "--input", str(source))
    assert _state(root)["voice_decisions"] == {}
    _unchanged_failure(root, env, "advance", "--next", "Step 5")


def test_actual_checkpoint_replace_failure_leaves_no_successful_late_save(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    source = _outcomes(root, env)
    path = root / ".pr-review/state.md"
    saved = path.read_bytes()
    path.unlink()
    path.mkdir()
    (path / "occupied").write_text("cannot replace a directory")
    # start 呼叫真實 atomic writer，不能覆蓋目錄目的地。
    assert _run(root, env, "start").returncode == 2
    assert (path / "occupied").read_text() == "cannot replace a directory"
    (path / "occupied").unlink()
    path.rmdir()
    path.write_bytes(saved)
    _ok(_run(root, env, "voices", "--input", str(source)))
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    _aggregate(root, env)
    assert _ok(_run(root, env, "resume"))["next"] == "Step 5a"


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root 會繞過真實目錄寫入權限"
)
def test_late_atomic_save_failure_keeps_prior_checkpoint_bytes(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    _late(root, env)
    directory = root / ".pr-review"
    mode = directory.stat().st_mode & 0o777
    try:
        directory.chmod(0o555)
        _unchanged_failure(root, env, "configure-ci", "--ci-command", "make ci")
    finally:
        directory.chmod(mode)
    assert "ci_command" not in _state(root)
    assert (
        _ok(_run(root, env, "configure-ci", "--ci-command", "make ci"))["ci_command"] == "make ci"
    )


def test_disputes_rulings_ci_baseline_and_new_pass_are_public_transitions(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    initial = _late(
        root,
        env,
        blocking=True,
        disputed=[{"id": "C1", "finding": "identity finding", "ruling": None}],
    )
    baseline = initial["baseline"]
    assert initial["next"] == "Step 5"
    _unchanged_failure(root, env, "advance", "--next", "Step 5a")
    _ok(
        _run(
            root,
            env,
            "ruling",
            "--finding",
            "C1",
            "--ruling",
            "fix",
            "--reason",
            "human confirms reproduction",
        )
    )
    _ok(_run(root, env, "configure-ci", "--ci-command", "make ci"))
    _route(root, env, "Step 6")
    moved = _move(root, env)
    _unchanged_failure(root, env, "resume")
    post = _ok(_run(root, env, "post-fix"))
    assert post["head"] == moved and post["reviewed_head"] == baseline and post["next"] == "Step 7"
    resumed = _ok(_run(root, env, "resume"))
    assert resumed["next"] == "Step 7" and resumed["captured_head"] == baseline
    _unchanged_failure(root, env, "advance", "--next", "Step 8")
    second = _ok(_run(root, env, "new-pass"))
    assert second["review_round"] == 2 and second["next"] == "Step 2"
    assert second["baseline"] == baseline and second["disputed"][0]["ruling"] == "fix"
    assert not second["voice_decisions"] and second["voice_history"]
    _unchanged_failure(root, env, "start")
    _ok(_run(root, env, "advance", "--next", "Step 3"))
    _unchanged_failure(root, env, "advance", "--next", "Step 5")
    _voices(root, env)
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    _aggregate(root, env)
    _route(root, env, "Step 8")
    _unchanged_failure(root, env, "advance", "--next", "Step 9")
    _ok(_run(root, env, "advance", "--next", "Step 9", "--ship-approved"))
    _unchanged_failure(root, env, "advance", "--next", "Step 10")
    Path(env["PR_CHECKS"]).write_text(json.dumps([{"name": "ci", "bucket": "pending"}]))
    _unchanged_failure(root, env, "ci")
    Path(env["PR_CHECKS"]).write_text(json.dumps([{"name": "ci", "bucket": "pass"}]))
    assert _ok(_run(root, env, "ci"))["next"] == "Step 10"
    assert _ok(_run(root, env, "resume"))["captured_head"] == baseline
    _move(root, env)
    _ok(_run(root, env, "post-fix"))
    _unchanged_failure(root, env, "new-pass")


def test_old_pass_reports_and_new_pass_approval_are_rejected(tmp_path: Path) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    source = _outcomes(
        root, env, statuses={"codex": {"status": "unavailable", "reason": "pass 1 quota"}}
    )
    assert _run(root, env, "voices", "--input", str(source)).returncode == 3
    _ok(_run(root, env, "voices", "--input", str(source), "--allow-claude-only"))
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    _aggregate(root, env, blocking=True)
    first_source = root / ".pr-review/outcomes-r1.json"
    first_bytes = first_source.read_bytes()
    old_final = (root / ".pr-review/final.md").read_bytes()
    _ok(_run(root, env, "configure-ci", "--ci-command", "make ci"))
    _route(root, env, "Step 6")
    _move(root, env)
    _ok(_run(root, env, "post-fix"))
    _ok(_run(root, env, "new-pass"))
    _ok(_run(root, env, "advance", "--next", "Step 3"))
    _ok(_run(root, env, "begin-attempt"))
    first_source.write_bytes(first_bytes)
    _unchanged_failure(root, env, "voices", "--input", str(first_source), "--allow-claude-only")
    source = _outcomes(
        root, env, statuses={"codex": {"status": "unavailable", "reason": "new pass quota"}}
    )
    assert _run(root, env, "voices", "--input", str(source)).returncode == 3
    _unchanged_failure(root, env, "advance", "--next", "Step 5")
    _ok(_run(root, env, "voices", "--input", str(source), "--allow-claude-only"))
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    (root / ".pr-review/final.md").write_bytes(old_final)
    _unchanged_failure(
        root, env, "checkpoint", "--input", str(root / ".pr-review/aggregation.json")
    )


def test_r2_failure_preserves_valid_r1_and_separately_discloses_debate_failure(
    tmp_path: Path,
) -> None:
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    _voices(root, env)
    _ok(_run(root, env, "advance", "--next", "Step 4"))
    status = _voices(
        root,
        env,
        phase="r2",
        statuses={"codex": {"status": "unavailable", "reason": "debate HTTP 502"}},
    )
    assert status["mode"] == "2-voice-mob" and status["active_voices"] == ["claude", "codex"]
    assert status["voice_failures"] == {} and status["debate_failures"] == {
        "codex": "debate HTTP 502"
    }
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    _aggregate(root, env)
    assert _ok(_run(root, env, "resume"))["voice_summary"].startswith("2-voice-mob")


@pytest.mark.parametrize("terminal", ["MERGED", "CLOSED"])
@pytest.mark.parametrize(
    "action",
    [
        "resume",
        "start",
        "advance",
        "begin-attempt",
        "voices",
        "checkpoint",
        "post-fix",
        "new-pass",
        "human-review",
        "ci",
    ],
)
def test_terminal_pr_routes_without_writes_even_after_squash_checkout(
    tmp_path: Path, terminal: str, action: str
) -> None:
    root, env = _case(tmp_path)
    original = _ok(_run(root, env, "start"))
    _move(root, env)
    _metadata(env, state=terminal, headRefOid=original["head"])
    path = root / ".pr-review/state.md"
    before = path.read_bytes()
    result = _run(root, env, action)
    assert path.read_bytes() == before
    if action == "resume":
        routed = _ok(result)
        assert routed == {
            "next": "Step 11" if terminal == "MERGED" else None,
            "terminal": terminal,
            "no_push_no_merge": True,
        }
    else:
        assert result.returncode == 2


def test_read_only_uses_same_provenance_and_exhaustion_without_lifecycle_state(
    tmp_path: Path,
) -> None:
    root, env = _case(tmp_path)
    source = _outcomes(
        root, env, read_only=True, statuses={"codex": {"status": "unavailable", "reason": "quota"}}
    )
    assert _run(root, env, "voices", "--input", str(source), "--read-only").returncode == 3
    assert _run(root, env, "verify-voices", "--read-only").returncode == 2
    _ok(_run(root, env, "voices", "--input", str(source), "--read-only", "--allow-claude-only"))
    report = _ok(_run(root, env, "verify-voices", "--read-only"))
    assert report["mode"] == "claude-only"
    _voices(root, env, read_only=True, phase="r2", statuses={"codex": {"status": "not-selected"}})
    report = _ok(_run(root, env, "verify-voices", "--read-only"))
    assert report["mode"] == "claude-only" and report["voice_failures"] == {"codex": "quota"}
    assert not (root / ".pr-review/state.md").exists()


@pytest.mark.parametrize("phase", ["r1", "r2"])
@pytest.mark.parametrize(
    "content", ["metadata-only", "missing-verdict", "quoted-review", "commented-review"]
)
def test_review_success_requires_complete_substantive_report(
    tmp_path: Path, phase: str, content: str
) -> None:
    """RCP-EG-003: 正確 identity／scope 不得替空白、截斷或僅引用的 review 提供成功證明。"""
    root, env = _case(tmp_path)
    _review_boundary(root, env)
    if phase == "r2":
        _voices(root, env)
        _ok(_run(root, env, "advance", "--next", "Step 4"))
    source = _outcomes(root, env, phase=phase)
    payload = json.loads(source.read_text())
    report = Path(payload["outcomes"]["codex"]["report"])
    header, scope, substantive = report.read_text().split("\n", 2)
    if content == "metadata-only":
        substantive = ""
    elif content == "missing-verdict":
        substantive = substantive[
            : substantive.index("## Verdict" if phase == "r1" else "## Final verdict")
        ]
    elif content == "commented-review":
        substantive = "<!--\n" + substantive + "-->\n"
    else:
        substantive = "```text\n" + substantive + "```\n"
    report.write_text(header + "\n" + scope + "\n" + substantive)
    payload["outcomes"]["codex"]["sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    source.write_text(json.dumps(payload))
    before_status = (
        (root / ".pr-review/voice-status.json").read_bytes()
        if (root / ".pr-review/voice-status.json").exists()
        else None
    )
    _unchanged_failure(root, env, "voices", "--phase", phase, "--input", str(source))
    after_status = (
        (root / ".pr-review/voice-status.json").read_bytes()
        if (root / ".pr-review/voice-status.json").exists()
        else None
    )
    assert after_status == before_status


@pytest.mark.parametrize("new_pass", [False, True])
def test_conflicting_dispute_id_never_reuses_unrelated_human_ruling(
    tmp_path: Path, new_pass: bool
) -> None:
    """RCP-ST-004: 同輪／跨輪同 id 不同 finding 必須拒絕，不可轉移人類 false-positive 裁決。"""
    root, env = _case(tmp_path)
    _late(root, env, blocking=True, disputed=[{"id": "C1", "finding": "finding A", "ruling": None}])
    _ok(
        _run(
            root,
            env,
            "ruling",
            "--finding",
            "C1",
            "--ruling",
            "false-positive",
            "--reason",
            "human rejects only A",
        )
    )
    if new_pass:
        _ok(_run(root, env, "configure-ci", "--ci-command", "make ci"))
        _route(root, env, "Step 6")
        _move(root, env)
        _ok(_run(root, env, "post-fix"))
        _ok(_run(root, env, "new-pass"))
        _ok(_run(root, env, "advance", "--next", "Step 3"))
        _voices(root, env)
        _ok(_run(root, env, "advance", "--next", "Step 5"))
    resumed = _ok(_run(root, env, "resume"))
    (root / ".pr-review/final.md").write_text(
        "<!-- checkpoint-final:" + json.dumps(resumed["final_identity"]) + " -->\n"
        "# Final\nNew finding B awaits human decision.\n"
    )
    source = root / ".pr-review/new-dispute.json"
    source.write_text(
        json.dumps(
            {
                "blocking": False,
                "disputed": [{"id": "C1", "finding": "NEW finding B", "ruling": None}],
            }
        )
    )
    _unchanged_failure(root, env, "checkpoint", "--input", str(source))
    assert _ok(_run(root, env, "resume"))["next"] == "Step 5"
    assert _state(root)["disputed"][0]["finding"] == "finding A"


def test_recheckpoint_cannot_erase_current_pass_human_fix_blocking(tmp_path: Path) -> None:
    """RCP-ST-005: 同輪 fix 裁決的 blocking 不得被舊 aggregation 的 false 清除。"""
    root, env = _case(tmp_path)
    items = [{"id": "C1", "finding": "must fix current defect", "ruling": None}]
    _late(root, env, blocking=False, disputed=items)
    ruled = _ok(
        _run(
            root,
            env,
            "ruling",
            "--finding",
            "C1",
            "--ruling",
            "fix",
            "--reason",
            "human requires correction",
        )
    )
    assert ruled["blocking"] is True
    refreshed = _aggregate(root, env, blocking=False, disputed=items)
    assert refreshed["blocking"] is True
    assert refreshed["disputed"][0]["ruling"] == "fix"
    for step in ("Step 5b", "Step 5c"):
        _ok(_run(root, env, "advance", "--next", step))
    _unchanged_failure(root, env, "advance", "--next", "Step 8")
    assert _ok(_run(root, env, "advance", "--next", "Step 6"))["next"] == "Step 6"


def _pass2_fix_pushed(root: Path, env: dict[str, str]) -> str:
    """走完 pass 1 fix → pass 2 blocking → Continue fixing 推送；回傳 pass 2 mob 審過的 HEAD。"""
    _late(root, env, blocking=True)
    _ok(_run(root, env, "configure-ci", "--ci-command", "make ci"))
    _route(root, env, "Step 6")
    _move(root, env)
    _ok(_run(root, env, "post-fix"))
    _ok(_run(root, env, "new-pass"))
    _ok(_run(root, env, "advance", "--next", "Step 3"))
    _voices(root, env)
    _ok(_run(root, env, "advance", "--next", "Step 5"))
    mob_head = _aggregate(root, env, blocking=True)["head"]
    _route(root, env, "Step 6")
    _move(root, env)
    post = _ok(_run(root, env, "post-fix"))
    assert post["next"] == "Step 7" and post["review_round"] == 2
    return mob_head


def test_pass2_post_fix_reaches_merge_only_through_recorded_human_review(tmp_path: Path) -> None:
    """RCP-ST-006: pass 2 修正後經人類複查邊界進 Step 8，仍需 ship 授權與本 HEAD CI（#675）。"""
    root, env = _case(tmp_path)
    mob_head = _pass2_fix_pushed(root, env)
    fixed = _state(root)["head"]
    _unchanged_failure(root, env, "advance", "--next", "Step 8")
    _unchanged_failure(root, env, "new-pass")
    _unchanged_failure(root, env, "start")
    reason = "human read pass-2 fix diff"
    reviewed = _ok(_run(root, env, "human-review", "--reason", reason))
    assert reviewed["next"] == "Step 8" and reviewed["reviewed_head"] == fixed
    assert reviewed["blocking"] is False and reviewed["review_round"] == 2
    assert reviewed["human_reviews"] == [
        {"from": mob_head, "head": fixed, "mob_head": mob_head, "reason": reason}
    ]
    resumed = _ok(_run(root, env, "resume"))
    assert resumed["next"] == "Step 8" and resumed["human_reviews"] == reviewed["human_reviews"]
    assert resumed["final_identity"]["head"] == mob_head
    _unchanged_failure(root, env, "advance", "--next", "Step 9")
    _ok(_run(root, env, "advance", "--next", "Step 9", "--ship-approved"))
    assert _ok(_run(root, env, "ci"))["next"] == "Step 10"
    # ship 後的 CI fix：再一次 post-fix → 人類複查，mob 證據仍綁原 pass 2 HEAD。
    _move(root, env)
    assert _ok(_run(root, env, "post-fix"))["next"] == "Step 7"
    assert _ok(_run(root, env, "resume"))["next"] == "Step 7"
    _unchanged_failure(root, env, "new-pass")
    again = _ok(_run(root, env, "human-review", "--reason", "human read CI fix"))
    assert [item["mob_head"] for item in again["human_reviews"]] == [mob_head, mob_head]
    assert again["human_reviews"][1]["from"] == fixed and "ship_approved_head" not in again
    _unchanged_failure(root, env, "advance", "--next", "Step 9")
    # Step 8 quick pass 提出 concern 後的修正也回 Step 7，同樣只能再經人類複查。
    _unchanged_failure(root, env, "post-fix")
    concern = _move(root, env)
    assert _ok(_run(root, env, "post-fix"))["next"] == "Step 7"
    third = _ok(_run(root, env, "human-review", "--reason", "human read concern fix"))
    assert third["head"] == concern and third["human_reviews"][2]["mob_head"] == mob_head


@pytest.mark.parametrize(
    "case",
    ["pass1-step7", "pass2-step6", "empty-reason", "missing-reason", "stale-voice-report"],
)
def test_human_review_rejects_outside_pass2_post_fix_boundary(tmp_path: Path, case: str) -> None:
    """RCP-ST-007: human-review 不得取代 pass 1 重審、不得缺 reason、不得採用失效 mob 證據。"""
    root, env = _case(tmp_path)
    args: tuple[str, ...] = ("human-review", "--reason", "human read diff")
    if case == "pass1-step7":
        _late(root, env, blocking=True)
        _ok(_run(root, env, "configure-ci", "--ci-command", "make ci"))
        _route(root, env, "Step 6")
        _move(root, env)
        _ok(_run(root, env, "post-fix"))
    elif case == "pass2-step6":
        _late(root, env, blocking=True)
        _ok(_run(root, env, "configure-ci", "--ci-command", "make ci"))
        _route(root, env, "Step 6")
        _move(root, env)
        _ok(_run(root, env, "post-fix"))
        _ok(_run(root, env, "new-pass"))
        _ok(_run(root, env, "advance", "--next", "Step 3"))
        _voices(root, env)
        _ok(_run(root, env, "advance", "--next", "Step 5"))
        _aggregate(root, env, blocking=True)
        _route(root, env, "Step 6")
    else:
        _pass2_fix_pushed(root, env)
        if case == "empty-reason":
            args = ("human-review", "--reason", "  ")
        elif case == "missing-reason":
            args = ("human-review",)
        else:
            (root / ".pr-review/codex-r1.md").write_text("stale replacement\n")
    _unchanged_failure(root, env, *args)


@pytest.mark.parametrize("mutation", ["mob-head", "reason", "extra-key", "pass1"])
def test_tampered_human_review_record_fails_closed(tmp_path: Path, mutation: str) -> None:
    """RCP-ST-008: 手改 human_reviews 紀錄不能讓 Step 8 checkpoint 繼續被採信。"""
    root, env = _case(tmp_path)
    _pass2_fix_pushed(root, env)
    _ok(_run(root, env, "human-review", "--reason", "human read diff"))
    state = _state(root)
    record = state["human_reviews"][0]
    if mutation == "mob-head":
        record["mob_head"] = "a" * 40
    elif mutation == "reason":
        record["reason"] = " "
    elif mutation == "extra-key":
        record["approved_by"] = "agent"
    else:
        state["review_round"] = 1
    (root / ".pr-review/state.md").write_text(json.dumps(state))
    _unchanged_failure(root, env, "resume")
    _unchanged_failure(root, env, "advance", "--next", "Step 9", "--ship-approved")

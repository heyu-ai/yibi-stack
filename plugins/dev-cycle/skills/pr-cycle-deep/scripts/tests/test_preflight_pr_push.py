"""PRP: pre-push gate behavior against real disposable Git repositories.

Only gh is replaced: it supplies controlled live API responses. The guarded git push
is real, so failures must preserve remote refs and must not recreate a deleted branch.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "preflight-pr-push.sh"


def _git(repo: Path, env: dict[str, str], *args: str) -> str:
    result = subprocess.run(  # nosec B603 B607
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True, timeout=30
    )
    return result.stdout.strip()


def _commit(repo: Path, env: dict[str, str], text: str) -> str:
    (repo / "file.txt").write_text(text, encoding="utf-8")
    _git(repo, env, "add", "file.txt")
    _git(repo, env, "commit", "-qm", text)
    return _git(repo, env, "rev-parse", "HEAD")


@dataclass
class RepoCase:
    repo: Path
    remote: Path
    response: Path
    env: dict[str, str]
    pr_head: str
    local_head: str

    def metadata(self, **changes: object) -> None:
        self.response.write_text(
            json.dumps(
                {
                    "number": 7,
                    "state": "OPEN",
                    "headRefName": "feature",
                    "headRefOid": self.pr_head,
                    **changes,
                }
            ),
            encoding="utf-8",
        )

    def remote_refs(self) -> str:
        return _git(self.remote, self.env, "for-each-ref", "--format=%(refname) %(objectname)")

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 B607
            ["bash", str(GATE), *(args or ("7", self.pr_head))],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def push(self, expected: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 B607
            [
                "bash",
                "-c",
                'bash "$1" "$2" "$3" && git push origin HEAD',
                "guarded-push",
                str(GATE),
                "7",
                expected or self.pr_head,
            ],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


@pytest.fixture
def repo_case(tmp_path: Path) -> RepoCase:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, env, "init", "--bare", "-q", "-b", "main")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, env, "init", "-q", "-b", "main")
    _git(repo, env, "config", "user.name", "Test")
    _git(repo, env, "config", "user.email", "test@example.com")
    _git(repo, env, "config", "commit.gpgsign", "false")
    _commit(repo, env, "base")
    _git(repo, env, "remote", "add", "origin", str(remote))
    _git(repo, env, "checkout", "-qb", "feature")
    pr_head = _commit(repo, env, "reviewed feature")
    _git(repo, env, "push", "-qu", "origin", "feature")
    local_head = _commit(repo, env, "review fixes")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" != pr ] || [ "$2" != view ] || [ "$3" != 7 ]; then exit 99; fi\n'
        'cat "$PR_RESPONSE"\n'
        'if [ "${PR_EXIT:-0}" != 0 ]; then echo "API unavailable" >&2; fi\n'
        'exit "${PR_EXIT:-0}"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    response = tmp_path / "response.json"
    env.update({"PATH": f"{bin_dir}{os.pathsep}{env['PATH']}", "PR_RESPONSE": str(response)})
    case = RepoCase(repo, remote, response, env, pr_head, local_head)
    case.metadata()
    return case


def test_open_preflight_is_read_only_then_allows_actual_fix_push(repo_case: RepoCase) -> None:
    """PRP-ST-001: gate alone is read-only; OPEN allows the real remote ref to advance."""
    case = repo_case
    before = case.remote_refs()
    preflight = case.run()
    assert preflight.returncode == 0, preflight.stderr
    assert case.remote_refs() == before
    assert _git(case.repo, case.env, "rev-parse", "HEAD") == case.local_head
    pushed = case.push()
    assert pushed.returncode == 0, pushed.stderr
    assert _git(case.remote, case.env, "rev-parse", "refs/heads/feature") == case.local_head


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
@pytest.mark.parametrize("deleted", [False, True])
def test_non_open_never_updates_or_recreates_branch(
    repo_case: RepoCase, state: str, deleted: bool
) -> None:
    """PRP-ST-002: terminal PR states preserve existing refs and deleted-branch absence."""
    case = repo_case
    case.metadata(state=state)
    if deleted:
        _git(case.remote, case.env, "update-ref", "-d", "refs/heads/feature")
    before = case.remote_refs()
    result = case.push()
    assert result.returncode == 2, result.stdout + result.stderr
    assert state in result.stderr
    assert case.remote_refs() == before
    assert _git(case.repo, case.env, "rev-parse", "HEAD") == case.local_head


def test_each_push_rechecks_live_state(repo_case: RepoCase) -> None:
    """PRP-ST-003: an earlier OPEN result cannot authorize a later fix batch."""
    case = repo_case
    assert case.push().returncode == 0
    case.metadata(state="MERGED", headRefOid=case.local_head)
    _git(case.remote, case.env, "update-ref", "-d", "refs/heads/feature")
    latest = _commit(case.repo, case.env, "late fix after merge")
    result = case.push(expected=case.local_head)
    assert result.returncode == 2
    assert case.remote_refs() == ""
    assert _git(case.repo, case.env, "rev-parse", "HEAD") == latest


def test_api_failure_is_not_open_even_with_valid_stdout(repo_case: RepoCase) -> None:
    """PRP-EG-001: valid-looking JSON cannot override a failed gh request."""
    case = repo_case
    case.env["PR_EXIT"] = "1"
    before = case.remote_refs()
    result = case.push()
    assert result.returncode == 1
    assert "API unavailable" in result.stderr
    assert case.remote_refs() == before


@pytest.mark.parametrize("payload", ["", "not json", "null", "[]", "{}"])
def test_missing_or_malformed_api_response_blocks_push(repo_case: RepoCase, payload: str) -> None:
    """PRP-EG-002: an empty, truncated or wrong-shaped response never authorizes a push."""
    case = repo_case
    case.response.write_text(payload, encoding="utf-8")
    before = case.remote_refs()
    assert case.push().returncode == 1
    assert case.remote_refs() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"number": 8},
        {"state": None},
        {"state": "UNKNOWN"},
        {"state": "open"},
        {"headRefName": ""},
        {"headRefName": "bad..ref"},
        {"headRefOid": None},
        {"headRefOid": "abc"},
    ],
)
def test_invalid_api_fields_fail_closed(repo_case: RepoCase, changes: dict[str, object]) -> None:
    """PRP-EG-003: another PR or unusable metadata is not an OPEN authorization."""
    case = repo_case
    case.metadata(**changes)
    before = case.remote_refs()
    assert case.push().returncode == 1
    assert case.remote_refs() == before


def test_open_pr_head_movement_requires_review(repo_case: RepoCase) -> None:
    """PRP-ST-004: OPEN alone cannot authorize pushing over an unexpected remote head."""
    case = repo_case
    case.metadata(headRefOid=case.local_head)
    before = case.remote_refs()
    result = case.push()
    assert result.returncode == 3
    assert case.remote_refs() == before


def test_open_pr_for_different_branch_cannot_authorize_current_branch(repo_case: RepoCase) -> None:
    """PRP-ST-005: looking up another OPEN PR must not authorize the current branch."""
    case = repo_case
    case.metadata(headRefName="different-feature")
    before = case.remote_refs()
    assert case.push().returncode == 3
    assert case.remote_refs() == before


def test_non_fast_forward_local_history_is_rejected(repo_case: RepoCase) -> None:
    """PRP-ST-006: preserve the reviewed remote history instead of authorizing a rewrite."""
    case = repo_case
    _git(case.repo, case.env, "reset", "--hard", f"{case.pr_head}^")
    _commit(case.repo, case.env, "divergent fix")
    before = case.remote_refs()
    assert case.run().returncode == 3
    assert case.remote_refs() == before


def test_missing_expected_commit_is_not_a_fast_forward(repo_case: RepoCase) -> None:
    """PRP-EG-004: an unavailable expected commit cannot be treated as ancestor success."""
    case = repo_case
    unknown = "f" * 40
    case.metadata(headRefOid=unknown)
    before = case.remote_refs()
    assert case.push(expected=unknown).returncode == 3
    assert case.remote_refs() == before


def test_detached_checkout_is_rejected(repo_case: RepoCase) -> None:
    """PRP-ST-007: a detached checkout cannot silently choose a push branch."""
    case = repo_case
    _git(case.repo, case.env, "checkout", "--detach", case.local_head)
    assert case.run().returncode == 1


@pytest.mark.parametrize("args", [("7",), ("0", "f" * 40), ("--help", "f" * 40), ("7", "short")])
def test_invalid_invocation_does_not_authorize_push(
    repo_case: RepoCase, args: tuple[str, ...]
) -> None:
    """PRP-VL-001: missing or option-like caller input fails before authorization."""
    case = repo_case
    before = case.remote_refs()
    assert case.run(*args).returncode == 1
    assert case.remote_refs() == before

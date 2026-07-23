"""release-full.sh 空 release guard 的黑盒測試。

v1.13.0 事故：release 流程沒有「自上個 tag 以來是否有新 commit」的檢查，
第二次 `make release` 在零新內容下照樣 bump -> gates -> tag，產出與前版
零 diff 的空版本。guard 在腳本最前端擋下這種空 release，`FORCE=1` 可覆寫。

測法：tmp git repo 釘住 tag/commit 狀態，`SKILL_DIR` 指向空目錄——guard 放行時
腳本會停在「not executable」這一步（無任何副作用），以此區分「被 guard 擋下」
與「通過 guard」兩種結束方式，不需要真的跑 bump/gates。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release-full.sh"

# 同 test_lessons_wrapper.py：從 pre-commit hook context 跑測試時 git 會 export
# GIT_DIR，蓋掉 fixture 想釘住的 tmp repo，必須清掉（rule 13「GIT_DIR / GIT_WORK_TREE
# Override git -C」）。
_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")

_EMPTY_RELEASE_MARK = "拒絕空 release"
_SKILL_MISSING_MARK = "not executable"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture()
def tagged_repo(tmp_path: Path) -> Path:
    """HEAD 上恰有一個 tag 的 git repo（空 release 的前置狀態）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init")
    _git(repo, "tag", "v0.1.0")
    return repo


def _run_release(
    repo: Path, tmp_path: Path, *, force: bool = False
) -> subprocess.CompletedProcess[str]:
    """以隔離環境跑 release-full.sh：SKILL_DIR 指向空目錄，guard 放行後必停在
    executable 檢查，保證測試不會真的走進 bump/gates。"""
    empty_skill_dir = tmp_path / "no-skill"
    empty_skill_dir.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_KEYS}
    env["SKILL_DIR"] = str(empty_skill_dir)
    if force:
        env["FORCE"] = "1"
    return subprocess.run(  # nosec B603
        ["bash", str(SCRIPT), "patch"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestEmptyReleaseGuard:
    def test_release_guard_001_zero_commits_since_tag_is_rejected(
        self, tagged_repo: Path, tmp_path: Path
    ) -> None:
        """RELEASE-GUARD-001: HEAD 即上個 tag（零新 commit）-> 拒絕空 release。"""
        result = _run_release(tagged_repo, tmp_path)
        assert result.returncode != 0
        assert _EMPTY_RELEASE_MARK in result.stderr
        # 必須死在 guard，而非走到後面的 skill 檢查
        assert _SKILL_MISSING_MARK not in result.stderr

    def test_release_guard_002_new_commit_passes_guard(
        self, tagged_repo: Path, tmp_path: Path
    ) -> None:
        """RELEASE-GUARD-002（正向對照）: tag 之後有新 commit -> guard 放行，
        停在下一步的 skill executable 檢查（證明不是 guard 誤擋）。"""
        _git(tagged_repo, "commit", "--allow-empty", "-m", "feat: something")
        result = _run_release(tagged_repo, tmp_path)
        assert result.returncode != 0
        assert _EMPTY_RELEASE_MARK not in result.stderr
        assert _SKILL_MISSING_MARK in result.stderr

    def test_release_guard_003_force_overrides_guard(
        self, tagged_repo: Path, tmp_path: Path
    ) -> None:
        """RELEASE-GUARD-003: FORCE=1 覆寫 guard（刻意重發同內容版本的逃生門）。"""
        result = _run_release(tagged_repo, tmp_path, force=True)
        assert result.returncode != 0
        assert _EMPTY_RELEASE_MARK not in result.stderr
        assert _SKILL_MISSING_MARK in result.stderr

    def test_release_guard_004_no_tags_skips_guard(self, tmp_path: Path) -> None:
        """RELEASE-GUARD-004: repo 完全沒有 tag（首次 release）-> guard 跳過。"""
        repo = tmp_path / "repo-untagged"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t.local")
        _git(repo, "config", "user.name", "t")
        _git(repo, "commit", "--allow-empty", "-m", "init")
        result = _run_release(repo, tmp_path)
        assert result.returncode != 0
        assert _EMPTY_RELEASE_MARK not in result.stderr
        assert _SKILL_MISSING_MARK in result.stderr

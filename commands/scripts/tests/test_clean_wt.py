"""clean_wt.sh 的行為測試。

這支腳本的核心保證是「不誤刪」，所以測試重心放在**該擋的有沒有擋住**：
- 分類正確（SAFE / KEEP / BLOCKED / REVIEW）
- 預設不刪任何東西
- worktree 裡的未提交內容一定擋下（分支比對看不到它）
- 沒有證據就不歸 SAFE（寧可留著也不猜）

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "commands" / "scripts" / "clean_wt.sh"

# gh 在測試環境可能已認證，會對 fake repo 發出無意義查詢並拖慢測試。
# 清空 PATH 中的 gh 不可行（腳本也要 git），改用 GH_CONFIG_DIR 指向空目錄讓 gh 查不到憑證，
# 腳本會走 [WARN] 分支並改用純 git 證據 -- 這正是我們要測的降級路徑。
def _env(tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "GH_CONFIG_DIR": str(tmp_path / "no-gh-config"),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "no-gitconfig"),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    r = subprocess.run(  # nosec B603
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return r.stdout.strip()


def _run(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(SCRIPT), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """一個有 origin/main 的最小 repo（origin 是本地 bare repo）。"""
    env = _env(tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(  # nosec B603
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=env
    )

    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True, env=env)  # nosec B603
    (work / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(work, "add", "-A", env=env)
    _git(work, "commit", "-qm", "seed", env=env)
    _git(work, "remote", "add", "origin", str(origin), env=env)
    _git(work, "push", "-q", "origin", "main", env=env)
    return work


class TestCleanWtClassification:
    def test_cwt_st_001_default_is_report_only(self, repo: Path, tmp_path: Path) -> None:
        """CWT-ST-001: 預設只報告，絕不刪除任何分支。"""
        env = _env(tmp_path)
        _git(repo, "branch", "leftover", env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "只報告" in r.stdout
        branches = _git(repo, "branch", "--format=%(refname:short)", env=env)
        assert "leftover" in branches, "預設模式不得刪除任何分支"

    def test_cwt_dt_001_merged_ancestor_branch_is_safe(self, repo: Path, tmp_path: Path) -> None:
        """CWT-DT-001: tip 已是 origin/main 祖先的分支 -> SAFE。"""
        env = _env(tmp_path)
        # 分支指向 main 的某個祖先 commit
        _git(repo, "branch", "already-in", "HEAD", env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        safe = r.stdout.split("══ KEEP")[0]
        assert "already-in" in safe, f"應歸為 SAFE:\n{r.stdout}"

    def test_cwt_dt_002_branch_with_unique_commits_is_review_not_safe(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-002: 有獨有 commit 且無 PR 的分支 -> REVIEW，不得歸 SAFE。

        這是「不誤刪」的核心：沒有證據顯示內容已進 main 就不能自動刪。
        """
        env = _env(tmp_path)
        _git(repo, "checkout", "-qb", "unique-work", env=env)
        (repo / "new.txt").write_text("unique\n", encoding="utf-8")
        _git(repo, "add", "-A", env=env)
        _git(repo, "commit", "-qm", "unique work", env=env)
        _git(repo, "checkout", "-q", "main", env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        safe = r.stdout.split("══ KEEP")[0]
        review = r.stdout.split("══ REVIEW")[1]
        assert "unique-work" not in safe, f"有獨有 commit 不得歸 SAFE:\n{r.stdout}"
        assert "unique-work" in review, f"應歸為 REVIEW:\n{r.stdout}"

    def test_cwt_eg_001_dirty_worktree_is_blocked(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-001: worktree 有未提交變更 -> BLOCKED，即使分支本身與 main 無差異。

        分支比對只看 commit，看不到工作目錄。實測事故（2026-07-15）：
        skill-governance-path-c 分支與 main 零差異，但 worktree 有 33 行未提交草稿。
        """
        env = _env(tmp_path)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "dirty-branch", str(wt), env=env)
        (wt / "uncommitted.txt").write_text("work in progress\n", encoding="utf-8")

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        blocked = r.stdout.split("══ BLOCKED")[1].split("══ REVIEW")[0]
        safe = r.stdout.split("══ KEEP")[0]
        assert "dirty-branch" in blocked, f"髒 worktree 必須 BLOCKED:\n{r.stdout}"
        assert "dirty-branch" not in safe

    def test_cwt_eg_002_apply_never_deletes_blocked(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-002: 即使加 --apply，BLOCKED 的分支仍不得被刪。"""
        env = _env(tmp_path)
        wt = tmp_path / "wt2"
        _git(repo, "worktree", "add", "-q", "-b", "dirty-keep", str(wt), env=env)
        (wt / "wip.txt").write_text("wip\n", encoding="utf-8")

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, r.stderr
        branches = _git(repo, "branch", "--format=%(refname:short)", env=env)
        assert "dirty-keep" in branches, "--apply 不得刪除 BLOCKED 分支"

    def test_cwt_st_002_apply_deletes_safe_branch(self, repo: Path, tmp_path: Path) -> None:
        """CWT-ST-002: --apply 會刪除 SAFE 分類的分支。"""
        env = _env(tmp_path)
        _git(repo, "branch", "gone-already", "HEAD", env=env)

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, r.stderr
        branches = _git(repo, "branch", "--format=%(refname:short)", env=env)
        assert "gone-already" not in branches, f"SAFE 分支應被刪除:\n{r.stdout}"

    def test_cwt_eg_003_never_deletes_main(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-003: main 永遠不出現在任何刪除清單。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--apply")

        assert r.returncode == 0, r.stderr
        branches = _git(repo, "branch", "--format=%(refname:short)", env=env)
        assert "main" in branches


class TestCleanWtArgs:
    @pytest.mark.parametrize("bad", ["abc", "-1", ""])
    def test_cwt_vl_001_rejects_non_numeric_stale_days(
        self, repo: Path, tmp_path: Path, bad: str
    ) -> None:
        """CWT-VL-001: --stale-days 非數值時 fail loud，不得靜默採用預設。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--stale-days", bad)
        assert r.returncode == 1
        assert "[FAIL]" in r.stderr

    def test_cwt_vl_002_rejects_stale_days_without_value(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-VL-002: --stale-days 漏傳值時給 clean [FAIL]，不得因 set -u 噴 stacktrace。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--stale-days")
        assert r.returncode == 1
        assert "[FAIL]" in r.stderr
        assert "unbound variable" not in r.stderr

    def test_cwt_vl_003_rejects_unknown_flag(self, repo: Path, tmp_path: Path) -> None:
        """CWT-VL-003: 未知參數必須 fail，不可被當成 no-op 忽略。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--force")
        assert r.returncode == 1
        assert "[FAIL]" in r.stderr

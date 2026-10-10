"""check-baseline.sh 的契約與行為測試（change: add-issue-triage-staleness-review）。

issue-triage 要拿「程式碼現況」判斷 issue 症狀是否已解；基準若是落後的 main 或沒合併的分支，
DONE 與 NOT DONE 都會判反。這支腳本在驗證症狀之前確認「檢視對象就是 origin/main」。

沿用 test_red_first_sh.py 的兩層慣例：

* **靜態契約測試** —— 讀 script 原始碼，斷言容易被「順手簡化」掉的不變量。
* **行為測試** —— 在拋棄式 git repo（bare origin + clone）裡，**每一個具名 exit code 都有一個
  實際會觸發它的輸入**。只測通過狀態等於沒有測試：把腳本短路成永遠 exit 0，
  通過狀態的測試依然全綠，所以每一種失敗狀態（test_cb_st_002 起）都必須有自己的對照。

Exit code 契約（與 check-baseline.sh 檔頭一致）：

    0  基準通過
    1  保留給腳本自身的未預期錯誤
    2  不在可讀取的 git repo
    3  fetch origin main 失敗（不回退到本機的 origin/main）
    4  checkout 的 commit 與 origin/main 不一致（訊息含 ahead 與 behind 數）
    5  tracked 檔案有未提交的修改（訊息含檔案數）
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
CHECK_BASELINE = SCRIPTS_DIR / "check-baseline.sh"

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_NOT_A_REPO = 2
EXIT_FETCH_FAILED = 3
EXIT_COMMIT_MISMATCH = 4
EXIT_TRACKED_MODIFIED = 5

# 清掉會讓 git 忽略 cwd 的環境變數（rule 17：GIT_DIR 優先於 -C / cwd）
_GIT_ENV_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _clean_env(**overrides: str) -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **overrides}
    for name in _GIT_ENV_VARS:
        if name not in overrides:
            env.pop(name, None)
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env=_clean_env(),
    )


def _commit_file(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _config_identity(repo: Path) -> None:
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")


def _make_repo(tmp_path: Path) -> tuple[Path, Path]:
    """建 bare origin 與一個停在 main、等於 origin/main 的 clone，回傳 (repo, origin)。"""
    origin = tmp_path / "origin.git"
    subprocess.run(  # nosec B603
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)],
        check=True,
        timeout=60,
        env=_clean_env(),
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _config_identity(seed)
    _git(seed, "remote", "add", "origin", str(origin))
    _commit_file(seed, "tracked.txt", "base\n", "base")
    _git(seed, "push", "-q", "origin", "main")

    repo = tmp_path / "repo"
    subprocess.run(  # nosec B603
        ["git", "clone", "-q", str(origin), str(repo)],
        check=True,
        timeout=60,
        env=_clean_env(),
    )
    _config_identity(repo)
    return repo, origin


def _advance_origin(tmp_path: Path, origin: Path, commits: int) -> None:
    """透過另一個 clone 讓 origin/main 前進 N 筆；本機 repo 完全不知情（尚未 fetch）。"""
    other = tmp_path / "other"
    if not other.exists():
        subprocess.run(  # nosec B603
            ["git", "clone", "-q", str(origin), str(other)],
            check=True,
            timeout=60,
            env=_clean_env(),
        )
        _config_identity(other)
    for i in range(commits):
        _commit_file(other, f"remote-{i}.txt", f"r{i}\n", f"remote {i}")
    _git(other, "push", "-q", "origin", "main")


def _run(cwd: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(CHECK_BASELINE)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=_clean_env(**env_overrides),
    )


class TestStaticContract:
    SRC = CHECK_BASELINE.read_text(encoding="utf-8") if CHECK_BASELINE.is_file() else ""

    def test_cb_dt_001_script_exists(self) -> None:
        assert CHECK_BASELINE.is_file(), f"缺少 {CHECK_BASELINE}"

    def test_cb_dt_002_fetches_origin_main_explicitly(self) -> None:
        """基準必須是剛 fetch 的 origin/main，不是本機殘留的 ref。"""
        assert re.search(r"git\b.*\bfetch\b.*\borigin\b.*\bmain\b", self.SRC)

    def test_cb_dt_003_fetch_failure_is_not_masked(self) -> None:
        """fetch 後面不得接 `|| true` / `|| exit 0`（rule 17：遮蔽 exit code）。"""
        fetch_lines = [
            line
            for line in self.SRC.splitlines()
            if "fetch" in line and not line.lstrip().startswith("#")
        ]
        assert fetch_lines, "找不到任何 fetch 指令行；空迴圈會讓下面的斷言空洞地通過"
        for line in fetch_lines:
            assert "|| true" not in line
            assert "|| exit 0" not in line

    def test_cb_dt_004_diagnostics_go_to_stderr(self) -> None:
        """每一行 [FAIL] 都必須導向 stderr（rule 17）。"""
        fail_lines = [
            line
            for line in self.SRC.splitlines()
            if "[FAIL]" in line and "echo" in line and not line.lstrip().startswith("#")
        ]
        assert fail_lines, "找不到任何 [FAIL] echo；空迴圈會讓下面的斷言空洞地通過"
        for line in fail_lines:
            assert ">&2" in line, line

    def test_cb_dt_005_header_documents_every_exit_code(self) -> None:
        """檔頭必須逐一列出 0、1、2、3、4、5；SKILL.md 的分支依據它。"""
        head = "\n".join(self.SRC.splitlines()[:40])
        for code in ("0", "1", "2", "3", "4", "5"):
            assert re.search(rf"^#\s+{code}\b", head, re.MULTILINE), f"檔頭缺 exit {code}"


class TestBehaviour:
    def test_cb_st_001_clean_and_equal_passes_with_sha_and_time(self, tmp_path: Path) -> None:
        """乾淨且等於 origin/main 的 checkout 通過，stdout 帶基準 SHA 與 fetch 時間。

        spec: issue-triage-evidence-baseline#clean-and-equal
        spec: issue-triage-evidence-baseline#passing-baseline
        tc: ITB-ST-001
        """
        repo, _ = _make_repo(tmp_path)
        proc = _run(repo)
        assert proc.returncode == EXIT_OK, proc.stderr
        expected = _git(repo, "rev-parse", "origin/main").stdout.strip()
        match = re.fullmatch(r"BASELINE_SHA=([0-9a-f]{40}) FETCHED_AT=(\S+)\n?", proc.stdout)
        assert match, proc.stdout
        assert match.group(1) == expected
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*", match.group(2))

    def test_cb_st_002_behind_detected_without_prior_manual_fetch(self, tmp_path: Path) -> None:
        """本機從未 fetch 過新 commit。

        若腳本沒自己 fetch，本機 origin/main 仍等於 HEAD，會誤判通過。

        spec: issue-triage-evidence-baseline#checkout-is-behind
        spec: issue-triage-evidence-baseline#fetch-succeeds
        tc: ITB-ST-002
        """
        repo, origin = _make_repo(tmp_path)
        _advance_origin(tmp_path, origin, commits=3)
        assert _git(repo, "rev-list", "--count", "HEAD..origin/main").stdout.strip() == "0"
        proc = _run(repo)
        assert proc.returncode == EXIT_COMMIT_MISMATCH, proc.stdout
        assert "[FAIL]" in proc.stderr
        assert "behind=3" in proc.stderr
        assert "ahead=0" in proc.stderr
        assert proc.stdout == ""

    def test_cb_st_003_ahead_of_origin_main_fails_with_count(self, tmp_path: Path) -> None:
        """checkout 有 origin/main 沒有的 commit（未合併的分支）：失敗並回報 ahead 數。

        spec: issue-triage-evidence-baseline#checkout-is-on-an-unmerged-branch
        tc: ITB-ST-003
        """
        repo, _ = _make_repo(tmp_path)
        _commit_file(repo, "local-a.txt", "a\n", "local a")
        _commit_file(repo, "local-b.txt", "b\n", "local b")
        proc = _run(repo)
        assert proc.returncode == EXIT_COMMIT_MISMATCH, proc.stdout
        assert "ahead=2" in proc.stderr
        assert "behind=0" in proc.stderr

    def test_cb_st_004_diverged_reports_both_counts(self, tmp_path: Path) -> None:
        repo, origin = _make_repo(tmp_path)
        _commit_file(repo, "local.txt", "l\n", "local")
        _advance_origin(tmp_path, origin, commits=2)
        proc = _run(repo)
        assert proc.returncode == EXIT_COMMIT_MISMATCH, proc.stdout
        assert "ahead=1" in proc.stderr
        assert "behind=2" in proc.stderr

    def test_cb_st_005_modified_tracked_file_fails_with_count_and_name(
        self, tmp_path: Path
    ) -> None:
        """tracked 檔案有未提交的修改：失敗並回報檔案數與檔名。

        spec: issue-triage-evidence-baseline#tracked-file-modified
        tc: ITB-ST-004
        """
        repo, _ = _make_repo(tmp_path)
        (repo / "tracked.txt").write_text("uncommitted edit\n", encoding="utf-8")
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "modified=1" in proc.stderr
        assert "tracked.txt" in proc.stderr
        assert proc.stdout == ""

    def test_cb_st_006_staged_change_counts_as_modified(self, tmp_path: Path) -> None:
        repo, _ = _make_repo(tmp_path)
        (repo / "tracked.txt").write_text("staged edit\n", encoding="utf-8")
        _git(repo, "add", "tracked.txt")
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "modified=1" in proc.stderr

    def test_cb_st_007_untracked_file_does_not_fail(self, tmp_path: Path) -> None:
        """untracked 暫存檔在主 checkout 極常見。

        列為失敗會讓檢查幾乎永遠紅，design 已明文接受這個殘餘風險。

        spec: issue-triage-evidence-baseline#clean-and-equal
        tc: ITB-EG-008
        """
        repo, _ = _make_repo(tmp_path)
        (repo / "scratch.txt").write_text("untracked\n", encoding="utf-8")
        proc = _run(repo)
        assert proc.returncode == EXIT_OK, proc.stderr

    def test_cb_st_008_unreachable_origin_fails_even_if_local_ref_matches(
        self, tmp_path: Path
    ) -> None:
        """fetch 失敗不得回退到本機 origin/main：此時本機 ref 恰好等於 HEAD，回退就會誤判通過。

        spec: issue-triage-evidence-baseline#fetch-fails
        tc: ITB-ST-005
        """
        repo, _ = _make_repo(tmp_path)
        _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
        assert (
            _git(repo, "rev-parse", "HEAD").stdout == _git(repo, "rev-parse", "origin/main").stdout
        )
        proc = _run(repo)
        assert proc.returncode == EXIT_FETCH_FAILED, proc.stdout
        assert "[FAIL]" in proc.stderr
        assert proc.stdout == ""

    def test_cb_st_009_missing_origin_remote_is_a_fetch_failure(self, tmp_path: Path) -> None:
        repo, _ = _make_repo(tmp_path)
        _git(repo, "remote", "remove", "origin")
        proc = _run(repo)
        assert proc.returncode == EXIT_FETCH_FAILED, proc.stdout

    def test_cb_st_010_outside_a_git_repo_exits_2(self, tmp_path: Path) -> None:
        """不在 git repo：exit 2、stdout 為空。

        spec: issue-triage-evidence-baseline#each-failure-is-distinguishable
        tc: ITB-EG-007
        """
        plain = tmp_path / "plain"
        plain.mkdir()
        proc = _run(plain)
        assert proc.returncode == EXIT_NOT_A_REPO, proc.stdout
        assert "[FAIL]" in proc.stderr
        assert proc.stdout == ""

    def test_cb_st_011_detached_head_at_origin_main_passes(self, tmp_path: Path) -> None:
        """從 origin/main 開的 worktree 或 detached HEAD 是正常用法，只看 commit 不看分支名。"""
        repo, _ = _make_repo(tmp_path)
        _git(repo, "checkout", "-q", "--detach", "origin/main")
        proc = _run(repo)
        assert proc.returncode == EXIT_OK, proc.stderr

    def test_cb_st_012_new_branch_at_same_commit_passes(self, tmp_path: Path) -> None:
        repo, _ = _make_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature", "origin/main")
        proc = _run(repo)
        assert proc.returncode == EXIT_OK, proc.stderr

    def test_cb_st_013_inherited_git_dir_does_not_redirect_to_another_repo(
        self, tmp_path: Path
    ) -> None:
        """rule 17：GIT_DIR 優先於 cwd。decoy 必須是**有效**的 repo 且狀態會讓檢查失敗，
        否則「忽略 GIT_DIR」與「被 GIT_DIR 騙去讀 decoy」無法區分。"""
        repo, _ = _make_repo(tmp_path)  # 乾淨且等於 origin/main，應該通過
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        _git(decoy, "init", "-q", "-b", "main")
        _config_identity(decoy)
        _commit_file(decoy, "x.txt", "x\n", "decoy")
        proc = _run(repo, GIT_DIR=str(decoy / ".git"), GIT_WORK_TREE=str(decoy))
        assert proc.returncode == EXIT_OK, proc.stderr

    def test_cb_st_014_assume_unchanged_edit_is_not_hidden(self, tmp_path: Path) -> None:
        """`assume-unchanged` 讓 `git status` 看不到修改，但 Read/Grep 讀到的是被改過的內容。

        只靠 status 會讓這種 tracked 修改通過基準；必須拿磁碟內容比對 HEAD 的 blob。

        spec: issue-triage-evidence-baseline#hidden-tracked-modification
        tc: ITB-ST-006
        """
        repo, _ = _make_repo(tmp_path)
        _git(repo, "update-index", "--assume-unchanged", "tracked.txt")
        (repo / "tracked.txt").write_text("LOCAL TAMPER\n", encoding="utf-8")
        assert _git(repo, "status", "--porcelain", "--untracked-files=no").stdout == ""
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "modified=1" in proc.stderr
        assert "tracked.txt" in proc.stderr
        assert proc.stdout == ""

    def test_cb_st_015_skip_worktree_edit_is_not_hidden(self, tmp_path: Path) -> None:
        """`skip-worktree` 同樣讓 status 靜默；磁碟上存在且內容不同就必須失敗。

        spec: issue-triage-evidence-baseline#hidden-tracked-modification
        tc: ITB-ST-007
        """
        repo, _ = _make_repo(tmp_path)
        _git(repo, "update-index", "--skip-worktree", "tracked.txt")
        (repo / "tracked.txt").write_text("LOCAL TAMPER\n", encoding="utf-8")
        assert _git(repo, "status", "--porcelain", "--untracked-files=no").stdout == ""
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "tracked.txt" in proc.stderr

    def test_cb_st_016_index_flags_with_unchanged_content_pass(self, tmp_path: Path) -> None:
        """對照：旗標本身不是失敗，內容等於 HEAD、或 sparse 缺檔都通過。

        sparse 缺檔必須是真的 sparse checkout（`core.sparseCheckout` 為 true、tag 為 S）；
        只有 skip-worktree 旗標而沒開 sparse 的缺檔是被刪掉的檔案，見 ITB-ST-013。

        spec: issue-triage-evidence-baseline#hidden-tracked-modification
        tc: ITB-ST-008
        """
        repo, _ = _make_repo(tmp_path)
        _commit_file(repo, "sparse.txt", "s\n", "add sparse")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "update-index", "--assume-unchanged", "tracked.txt")
        _git(repo, "sparse-checkout", "init", "--no-cone")
        _git(repo, "sparse-checkout", "set", "/tracked.txt")
        assert not (repo / "sparse.txt").exists()
        assert _git(repo, "config", "--bool", "core.sparseCheckout").stdout.strip() == "true"
        proc = _run(repo)
        assert proc.returncode == EXIT_OK, proc.stderr

    def test_cb_st_017_local_branch_named_origin_main_does_not_shadow_remote_ref(
        self, tmp_path: Path
    ) -> None:
        """本機分支叫 `origin/main` 時，短名稱 `origin/main` 會先解析到 refs/heads。

        基準必須用完整的 refs/remotes/origin/main；訊息也不得夾帶 git 的 ambiguity warning。

        spec: issue-triage-evidence-baseline#fetch-succeeds
        tc: ITB-ST-009
        """
        repo, origin = _make_repo(tmp_path)
        remote_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _commit_file(repo, "other.txt", "o\n", "other")
        _git(repo, "branch", "origin/main", "HEAD")
        _git(repo, "reset", "-q", "--hard", remote_sha)
        proc = _run(repo)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert f"BASELINE_SHA={remote_sha} " in proc.stdout

        _advance_origin(tmp_path, origin, commits=1)
        behind = _run(repo)
        assert behind.returncode == EXIT_COMMIT_MISMATCH, behind.stdout
        assert "ahead=0 behind=1" in behind.stderr
        assert "warning" not in behind.stderr


def _push_files(repo: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add fixtures")
    _git(repo, "push", "-q", "origin", "main")


def _push_symlink(repo: Path, name: str, target: str) -> None:
    os.symlink(target, repo / name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add symlink {name}")
    _git(repo, "push", "-q", "origin", "main")


class TestCwdScope:
    """`git ls-files` 與 `git status` 預設只看 cwd 底下；腳本必須先切到 repo 根目錄。"""

    def test_cb_st_018_hidden_edit_outside_cwd_is_caught_from_a_subdirectory(
        self, tmp_path: Path
    ) -> None:
        """從子目錄執行時，子目錄之外被旗標隱藏的修改一樣要擋下。

        舊版只掃 cwd 底下的 index：`top.txt` 在 repo 根目錄，從 `docs/` 執行會 exit 0。

        spec: issue-triage-evidence-baseline#run-from-a-subdirectory
        tc: ITB-ST-010
        """
        repo, _ = _make_repo(tmp_path)
        _push_files(repo, {"top.txt": "top\n", "docs/guide.md": "guide\n"})
        _git(repo, "update-index", "--assume-unchanged", "top.txt")
        (repo / "top.txt").write_text("LOCAL TAMPER\n", encoding="utf-8")
        assert _git(repo, "status", "--porcelain", "--untracked-files=no").stdout == ""
        from_root = _run(repo)
        assert from_root.returncode == EXIT_TRACKED_MODIFIED, from_root.stdout
        from_sub = _run(repo / "docs")
        assert from_sub.returncode == EXIT_TRACKED_MODIFIED, from_sub.stdout
        assert "top.txt" in from_sub.stderr
        assert from_sub.stdout == ""

    def test_cb_st_019_unchanged_flagged_file_inside_cwd_passes_from_a_subdirectory(
        self, tmp_path: Path
    ) -> None:
        """對照：旗標但內容等於 HEAD 的檔案在 cwd 內，從子目錄執行也要通過。

        舊版從子目錄看到的路徑是 cwd 相對（`bar.txt`），查不到 HEAD 的 blob 而誤報 exit 5。

        spec: issue-triage-evidence-baseline#run-from-a-subdirectory
        tc: ITB-ST-011
        """
        repo, _ = _make_repo(tmp_path)
        _push_files(repo, {"sub/bar.txt": "bar\n"})
        _git(repo, "update-index", "--assume-unchanged", "sub/bar.txt")
        from_root = _run(repo)
        assert from_root.returncode == EXIT_OK, from_root.stderr
        from_sub = _run(repo / "sub")
        assert from_sub.returncode == EXIT_OK, from_sub.stderr
        assert re.fullmatch(r"BASELINE_SHA=[0-9a-f]{40} FETCHED_AT=\S+\n?", from_sub.stdout)


class TestFlaggedFileAbsentFromDisk:
    """旗標隱藏的檔案不在磁碟上：只有真的 sparse checkout 才算正常。"""

    def test_cb_st_020_assume_unchanged_and_deleted_is_modified(self, tmp_path: Path) -> None:
        """assume-unchanged 的檔案被刪掉：status 看不到，但 Read/Grep 會找不到它，不是乾淨基準。

        spec: issue-triage-evidence-baseline#hidden-tracked-file-deleted-from-disk
        tc: ITB-ST-012
        """
        repo, _ = _make_repo(tmp_path)
        _push_files(repo, {"gone.txt": "gone\n"})
        _git(repo, "update-index", "--assume-unchanged", "gone.txt")
        (repo / "gone.txt").unlink()
        assert _git(repo, "status", "--porcelain", "--untracked-files=no").stdout == ""
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "modified=1" in proc.stderr
        assert "gone.txt" in proc.stderr
        assert proc.stdout == ""

    def test_cb_st_021_skip_worktree_and_deleted_without_sparse_is_modified(
        self, tmp_path: Path
    ) -> None:
        """skip-worktree 的缺檔只有在 sparse checkout 開啟時才豁免；沒開就是被刪掉的檔案。

        spec: issue-triage-evidence-baseline#hidden-tracked-file-deleted-from-disk
        tc: ITB-ST-013
        """
        repo, _ = _make_repo(tmp_path)
        _push_files(repo, {"gone.txt": "gone\n"})
        _git(repo, "update-index", "--skip-worktree", "gone.txt")
        (repo / "gone.txt").unlink()
        assert _git(repo, "status", "--porcelain", "--untracked-files=no").stdout == ""
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "gone.txt" in proc.stderr

    def test_cb_st_022_sparse_enabled_does_not_exempt_an_assume_unchanged_deletion(
        self, tmp_path: Path
    ) -> None:
        """豁免只給 S／s tag：sparse 開著時，assume-unchanged（小寫 h）的缺檔仍然是修改。

        spec: issue-triage-evidence-baseline#hidden-tracked-file-deleted-from-disk
        tc: ITB-ST-013
        """
        repo, _ = _make_repo(tmp_path)
        _push_files(repo, {"gone.txt": "gone\n"})
        _git(repo, "sparse-checkout", "init", "--no-cone")
        _git(repo, "sparse-checkout", "set", "/tracked.txt", "/gone.txt")
        _git(repo, "update-index", "--assume-unchanged", "gone.txt")
        (repo / "gone.txt").unlink()
        assert _git(repo, "config", "--bool", "core.sparseCheckout").stdout.strip() == "true"
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "gone.txt" in proc.stderr


class TestFlaggedSymlinkAndNewFile:
    def test_cb_st_023_retargeted_assume_unchanged_symlink_is_modified(
        self, tmp_path: Path
    ) -> None:
        """symlink 的內容是連結目標：assume-unchanged 後把它改指向別處，要擋下。

        spec: issue-triage-evidence-baseline#hidden-tracked-modification
        tc: ITB-ST-014
        """
        repo, _ = _make_repo(tmp_path)
        _push_files(repo, {"real.txt": "real\n", "other.txt": "other\n"})
        _push_symlink(repo, "link", "real.txt")
        _git(repo, "update-index", "--assume-unchanged", "link")
        (repo / "link").unlink()
        os.symlink("other.txt", repo / "link")
        assert _git(repo, "status", "--porcelain", "--untracked-files=no").stdout == ""
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "link" in proc.stderr

    def test_cb_st_024_unchanged_assume_unchanged_symlink_passes(self, tmp_path: Path) -> None:
        """對照：旗標但目標沒變的 symlink 通過；否則上一個測試只證明「symlink 一律失敗」。

        spec: issue-triage-evidence-baseline#hidden-tracked-modification
        tc: ITB-ST-015
        """
        repo, _ = _make_repo(tmp_path)
        _push_files(repo, {"real.txt": "real\n"})
        _push_symlink(repo, "link", "real.txt")
        _git(repo, "update-index", "--assume-unchanged", "link")
        proc = _run(repo)
        assert proc.returncode == EXIT_OK, proc.stderr

    def test_cb_st_025_flagged_file_that_is_not_in_head_is_modified(self, tmp_path: Path) -> None:
        """intent-to-add 加 assume-unchanged：status 為空、index 有檔但 HEAD 沒有，必須擋下。

        spec: issue-triage-evidence-baseline#hidden-tracked-modification
        tc: ITB-ST-016
        """
        repo, _ = _make_repo(tmp_path)
        (repo / "brand-new.txt").write_text("new\n", encoding="utf-8")
        _git(repo, "add", "-N", "brand-new.txt")
        _git(repo, "update-index", "--assume-unchanged", "brand-new.txt")
        assert _git(repo, "status", "--porcelain", "--untracked-files=no").stdout == ""
        proc = _run(repo)
        assert proc.returncode == EXIT_TRACKED_MODIFIED, proc.stdout
        assert "brand-new.txt" in proc.stderr


# 假的 git：只讓指定的子指令失敗，其餘轉給真的 git。略過 -c 與 -C 這類全域選項後的第一個字是子指令。
SHIM = """#!/usr/bin/env bash
args=("$@")
i=0
while [ "$i" -lt "${#args[@]}" ]; do
  case "${args[$i]}" in
    -c | -C) i=$((i + 2)) ;;
    -*) i=$((i + 1)) ;;
    *) break ;;
  esac
done
if [ "${args[$i]:-}" = "${SHIM_FAIL_SUBCMD}" ]; then
  echo "shim: simulated failure of git ${SHIM_FAIL_SUBCMD}" >&2
  exit 3
fi
exec "${SHIM_REAL_GIT}" "$@"
"""


class TestUnexpectedGitFailure:
    @pytest.mark.parametrize(
        ("subcommand", "flagged"),
        [
            ("rev-list", "file"),
            ("status", "file"),
            ("config", "file"),
            ("ls-files", "file"),
            ("hash-object", "file"),
            ("hash-object", "symlink"),
        ],
    )
    def test_cb_eg_017_a_failing_git_subcommand_exits_1_without_passing(
        self, tmp_path: Path, subcommand: str, flagged: str
    ) -> None:
        """git 自己壞掉（子指令非 0）不是基準通過：exit 1、stdout 為空、stderr 以 [FAIL] 說明。

        每個子指令都在「會走到它」的 fixture 上測：hash-object 需要被旗標隱藏、磁碟上存在的檔案，
        且一般檔案與 symlink 各走不同分支。分支若把 `fail 1` 改成 `true`，這裡會變成 exit 0 或 5。

        spec: issue-triage-evidence-baseline#unexpected-git-failure-is-not-a-pass
        tc: ITB-EG-017
        """
        repo, _ = _make_repo(tmp_path)
        if flagged == "symlink":
            _push_symlink(repo, "link", "tracked.txt")
            _git(repo, "update-index", "--assume-unchanged", "link")
        else:
            _git(repo, "update-index", "--assume-unchanged", "tracked.txt")
        shim_dir = tmp_path / "shim-bin"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(SHIM, encoding="utf-8")
        shim.chmod(0o755)
        real_git = shutil.which("git")
        assert real_git, "找不到真的 git"
        proc = _run(
            repo,
            PATH=f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
            SHIM_FAIL_SUBCMD=subcommand,
            SHIM_REAL_GIT=real_git,
        )
        assert proc.returncode == EXIT_UNEXPECTED, (proc.stdout, proc.stderr)
        assert proc.stdout == ""
        assert "[FAIL]" in proc.stderr


class TestDistinctExitCodes:
    def test_cb_dt_006_every_failure_has_its_own_code(self, tmp_path: Path) -> None:
        """四種失敗必須是四個互不相同的非 0 code，SKILL.md 才能逐一分支而不是塌成單一失敗。

        spec: issue-triage-evidence-baseline#each-failure-is-distinguishable
        tc: ITB-DT-006
        """
        codes: dict[str, int] = {}

        plain = tmp_path / "plain"
        plain.mkdir()
        codes["not_a_repo"] = _run(plain).returncode

        r1 = tmp_path / "fetch"
        r1.mkdir()
        repo1, _ = _make_repo(r1)
        _git(repo1, "remote", "set-url", "origin", str(r1 / "missing.git"))
        codes["fetch_failed"] = _run(repo1).returncode

        r2 = tmp_path / "behind"
        r2.mkdir()
        repo2, origin2 = _make_repo(r2)
        _advance_origin(r2, origin2, commits=1)
        codes["commit_mismatch"] = _run(repo2).returncode

        r3 = tmp_path / "dirty"
        r3.mkdir()
        repo3, _ = _make_repo(r3)
        (repo3 / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        codes["tracked_modified"] = _run(repo3).returncode

        assert all(c != 0 for c in codes.values()), codes
        assert len(set(codes.values())) == 4, codes
        assert codes == {
            "not_a_repo": EXIT_NOT_A_REPO,
            "fetch_failed": EXIT_FETCH_FAILED,
            "commit_mismatch": EXIT_COMMIT_MISMATCH,
            "tracked_modified": EXIT_TRACKED_MODIFIED,
        }

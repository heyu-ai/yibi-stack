"""red-first.sh 的契約與行為測試（PR #469 mob review Round 2）。

沿用 test_preflight_review_snapshot.py 的兩層慣例：

* **靜態契約測試** —— 讀 script 原始碼，斷言幾個容易被「順手簡化」掉的不變量
  （標題只經變數傳入、body 用 `>|` 覆寫、base 取 FETCH_HEAD）。

* **行為測試** —— 在拋棄式 repo 裡放假的 `gh` 與假的 checker，**每一個具名 exit code
  都有一個實際會觸發它的輸入**。PR #469 Round 2 的 Critical 正是「runbook 照字面執行時
  gate 靜默失效」，所以 happy path 只佔少數，其餘都是正向對照。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
RED_FIRST = SCRIPTS_DIR / "red-first.sh"

# 具名 exit code，與 script 檔頭的表格一一對應
EXIT_CONTINUE = 0
EXIT_VERDICT_FAIL = 1
EXIT_ERROR = 2
EXIT_TREE_NOT_RESTORED = 3

# 刻意含 `${N}`（本 repo PR #387 的真實標題形狀）與反引號：若被 shell 展開，
# checker 收到的標題會不同，argv 比對就會失敗
HOSTILE_TITLE = 'fix(x): 位置參數改 ${N} 並處理 `touch pwned` 與 "引號"'

FAKE_GH = """#!/usr/bin/env bash
# 假的 gh：只支援 `gh pr view <n> --json <field> -q .<field>`
if [ -n "${FAKE_GH_FAIL:-}" ]; then echo "gh: simulated failure" >&2; exit 1; fi
case "$5" in
  title) printf '%s\\n' "${FAKE_GH_TITLE-}" ;;
  baseRefName) printf '%s\\n' "${FAKE_GH_BASE:-main}" ;;
  body) printf '%s\\n' "${FAKE_GH_BODY:-body}" ;;
  *) echo "unexpected field $5" >&2; exit 1 ;;
esac
"""

FAKE_CHECKER = '''"""假的 red-first-check.py（行為見 FAKE_CHECKER_MODE）。"""
import os
import pathlib
import sys

pathlib.Path(os.environ["FAKE_ARGV_OUT"]).write_text("\\n".join(sys.argv[1:]), encoding="utf-8")
repo = pathlib.Path(sys.argv[sys.argv.index("--repo") + 1])
mode = os.environ.get("FAKE_CHECKER_MODE", "pass")
if mode == "pass":
    print("red-first: PASS")
    sys.exit(0)
if mode == "fail":
    print("red-first: FAIL")
    sys.exit(1)
if mode == "traceback":
    print("Traceback (most recent call last):\\nKeyError: x")
    sys.exit(1)
if mode == "exit2":
    print("[FAIL] 測試在 HEAD 就沒過")
    sys.exit(2)
if mode == "exit137":
    sys.exit(137)
if mode == "dirty":
    (repo / "leak.txt").write_text("reverted production code\\n", encoding="utf-8")
    print("red-first: PASS")
    sys.exit(0)
if mode == "side":
    (repo / "side.txt").write_text("tool side effect\\n", encoding="utf-8")
    print("[WARN] 執行期間出現新的工作樹改動：", file=sys.stderr)
    print("    ?? side.txt", file=sys.stderr)
    print("red-first: PASS")
    sys.exit(0)
sys.exit(99)
'''


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=60
    )


def _setup(tmp_path: Path, *, checker_on_base: bool = True, with_checker: bool = True) -> Path:
    """建 origin（bare）+ 工作 checkout；main 為 base，feature 分支多一筆 commit。"""
    origin = tmp_path / "origin.git"
    subprocess.run(  # nosec B603
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, timeout=60
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "remote", "add", "origin", str(origin))
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    if with_checker and checker_on_base:
        (repo / "scripts").mkdir()
        (repo / "scripts" / "red-first-check.py").write_text(FAKE_CHECKER, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "f.txt").write_text("feature\n", encoding="utf-8")
    if with_checker and not checker_on_base:
        (repo / "scripts").mkdir()
        (repo / "scripts" / "red-first-check.py").write_text(FAKE_CHECKER, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feature")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    return repo


def _run(
    tmp_path: Path, repo: Path, **env_overrides: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    out_dir = tmp_path / "out"
    argv_out = tmp_path / "argv.txt"
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GH_TITLE": "feat: add thing",
        "FAKE_ARGV_OUT": str(argv_out),
        **env_overrides,
    }
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    proc = subprocess.run(  # nosec B603
        [
            "bash",
            str(RED_FIRST),
            "--pr",
            "7",
            "--repo-root",
            str(repo),
            "--out-dir",
            str(out_dir),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )
    return proc, argv_out


class TestStaticContract:
    SRC = RED_FIRST.read_text(encoding="utf-8")

    def test_rfs_dt_001_title_only_passed_via_variable(self) -> None:
        """標題只能以 "$PR_TITLE" 傳給 checker，不得出現任何貼字面值的佔位符。"""
        assert '--title "$PR_TITLE"' in self.SRC
        assert "{{pr_title}}" not in self.SRC
        assert "<PR title>" not in self.SRC

    def test_rfs_dt_002_body_overwritten_noclobber_safe(self) -> None:
        assert '>| "$OUT_DIR/pr-body.md"' in self.SRC

    def test_rfs_dt_003_base_is_fetched_not_a_local_ref(self) -> None:
        assert "git rev-parse FETCH_HEAD" in self.SRC
        assert "origin/{{base_branch}}" not in self.SRC


class TestBehaviour:
    def test_rfs_st_001_no_checker_skips_with_exit_0(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path, with_checker=False)
        proc, _ = _run(tmp_path, repo)
        assert proc.returncode == EXIT_CONTINUE, proc.stderr
        assert "[SKIP] red-first: no checker" in proc.stdout
        assert "RED_FIRST_RESULT=skip-no-checker" in proc.stdout

    def test_rfs_st_002_pass_passes_hostile_title_verbatim(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        proc, argv_out = _run(tmp_path, repo, FAKE_GH_TITLE=HOSTILE_TITLE)
        assert proc.returncode == EXIT_CONTINUE, proc.stderr
        argv = argv_out.read_text(encoding="utf-8").split("\n")
        assert argv[argv.index("--title") + 1] == HOSTILE_TITLE
        assert not (tmp_path / "pwned").exists()
        assert not (repo / "pwned").exists()

    def test_rfs_st_003_base_is_fetch_head_sha(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        proc, argv_out = _run(tmp_path, repo)
        assert proc.returncode == EXIT_CONTINUE, proc.stderr
        argv = argv_out.read_text(encoding="utf-8").split("\n")
        origin_main = _git(repo, "rev-parse", "origin/main").stdout.strip()
        assert argv[argv.index("--base") + 1] == origin_main

    def test_rfs_st_004_verdict_fail_exits_1(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="fail")
        assert proc.returncode == EXIT_VERDICT_FAIL, proc.stderr
        assert "RED_FIRST_RESULT=fail" in proc.stdout

    def test_rfs_st_005_exit_1_without_verdict_is_error(self, tmp_path: Path) -> None:
        """traceback 也是 exit 1，但不是判定；必須變成 exit 2，不能叫作者去補測試。"""
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="traceback")
        assert proc.returncode == EXIT_ERROR, proc.stdout
        assert "沒有 'red-first: FAIL' 判定行" in proc.stderr

    @pytest.mark.parametrize("mode", ["exit2", "exit137"])
    def test_rfs_st_006_other_checker_exits_are_errors(self, tmp_path: Path, mode: str) -> None:
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE=mode)
        assert proc.returncode == EXIT_ERROR, proc.stdout

    def test_rfs_st_007_unexplained_dirt_after_run_exits_3(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="dirty")
        assert proc.returncode == EXIT_TREE_NOT_RESTORED, proc.stdout
        assert "leak.txt" in proc.stderr
        assert "RED_FIRST_RESULT=tree-not-restored" in proc.stdout

    def test_rfs_st_008_listed_side_effect_warns_and_keeps_verdict(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="side")
        assert proc.returncode == EXIT_CONTINUE, proc.stderr
        assert "[WARN] red-first: 測試工具留下副作用" in proc.stdout
        assert "side.txt" in proc.stdout

    def test_rfs_st_009_dirty_before_run_is_error(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        (repo / "wip.txt").write_text("uncommitted\n", encoding="utf-8")
        proc, argv_out = _run(tmp_path, repo)
        assert proc.returncode == EXIT_ERROR, proc.stdout
        assert not argv_out.exists(), "工作區不乾淨時不得執行 checker"

    def test_rfs_st_010_gh_failure_is_error(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        proc, argv_out = _run(tmp_path, repo, FAKE_GH_FAIL="1")
        assert proc.returncode == EXIT_ERROR, proc.stdout
        assert not argv_out.exists()

    def test_rfs_st_011_empty_title_is_error(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        proc, argv_out = _run(tmp_path, repo, FAKE_GH_TITLE="")
        assert proc.returncode == EXIT_ERROR, proc.stdout
        assert "標題為空" in proc.stderr
        assert not argv_out.exists()

    def test_rfs_st_012_checker_modified_by_pr_is_flagged(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path, checker_on_base=False)
        proc, _ = _run(tmp_path, repo)
        assert proc.returncode == EXIT_CONTINUE, proc.stderr
        assert "[WARN] red-first: checker modified by this PR" in proc.stdout

    def test_rfs_st_013_checker_on_base_is_not_flagged(self, tmp_path: Path) -> None:
        """RFS-ST-012 的對照：checker 不在 PR diff 裡時不得誤報。"""
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo)
        assert "checker modified by this PR" not in proc.stdout

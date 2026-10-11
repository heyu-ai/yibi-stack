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
import re
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

# 跑之前工作樹不乾淨時的錯誤訊息（RFS-ST-009／021 共用）
DIRTY_BEFORE_MSG = "跑 checker 前工作樹就不乾淨"

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
import subprocess
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
if mode == "unchecked":
    # yibi-mvp 檢查器現在的輸出形狀：產品碼改動全在不支援的目錄，exit 0 且不印判定行
    print("[WARN] 檢查器不支援的目錄，未檢查：scripts/harness/gate.py")
    print("[WARN] 產品碼改動只在檢查器不支援的目錄（1 個檔），"
          "red-first 沒有檢查任何東西，不是通過；請另附證據（例如手動 mutation）")
    sys.exit(0)
if mode == "unchecked-marker":
    print("red-first: UNCHECKED")
    sys.exit(0)
if mode == "pass-and-unchecked":
    print("red-first: UNCHECKED")
    print("red-first: PASS")
    sys.exit(0)
if mode == "partial-unsupported":
    # 只有部分改動在不支援的目錄，其餘有跑測試：這是 PASS，不是 unchecked
    print("[WARN] 檢查器不支援的目錄，未檢查：scripts/harness/gate.py")
    print("red-first: PASS")
    sys.exit(0)
if mode == "fail-and-unchecked":
    # exit 1 帶 FAIL 判定時，即使同時印了 unchecked 標記，結論仍是 fail（AC-2）
    print("red-first: UNCHECKED")
    print("red-first: FAIL")
    sys.exit(1)
if mode == "sentence-and-pass":
    print("[WARN] red-first 沒有檢查任何東西，不是通過")
    print("red-first: PASS")
    sys.exit(0)
if mode == "inline-marker-and-pass":
    # 標記不是整行：不算 unchecked（AC-1）
    print("[INFO] red-first: UNCHECKED is not emitted")
    print("red-first: PASS")
    sys.exit(0)


def git(*args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


if mode == "submodule-edit":
    with (repo / "sub" / "s.txt").open("a", encoding="utf-8") as fh:
        fh.write("checker wrote inside the submodule\\n")
    print("red-first: PASS")
    sys.exit(0)
if mode == "stage-new":
    (repo / "staged.txt").write_text("checker staged this\\n", encoding="utf-8")
    git("add", "staged.txt")
    print("red-first: PASS")
    sys.exit(0)
if mode == "reset-soft":
    git("reset", "-q", "--soft", "HEAD~1")
    print("red-first: PASS")
    sys.exit(0)
if mode == "commit-empty":
    # HEAD 換了 commit，但工作樹與 index 都乾淨：只有 HEAD 比對抓得到
    git("commit", "-q", "--allow-empty", "-m", "checker commit")
    print("red-first: PASS")
    sys.exit(0)
if mode == "switch-branch":
    # 同一個 commit、換了分支：只有分支比對抓得到
    git("checkout", "-q", "-b", "other")
    print("red-first: PASS")
    sys.exit(0)
if mode == "fail-and-dirty":
    (repo / "leak.txt").write_text("reverted production code\\n", encoding="utf-8")
    print("red-first: FAIL")
    sys.exit(1)
if mode == "orphan":
    # 切到 orphan 分支：HEAD 變成 unborn，`git rev-parse --verify HEAD` 會失敗（#545 第 1 項）
    git("checkout", "-q", "--orphan", "tmp")
    print("red-first: PASS")
    sys.exit(0)
sys.exit(99)
'''


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=60
    )


def _add_submodule(tmp_path: Path, repo: Path) -> None:
    """在 repo 加一個 submodule `sub`，並在 .gitmodules 設 `ignore = dirty`。

    `ignore = dirty` 讓預設的 `git status` 看不到 submodule 內的改動；腳本必須用
    `--ignore-submodules=none` 才看得到。少了這個設定，拿掉該旗標的突變不會被任何測試抓到。
    """
    src = tmp_path / "subsrc"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "test@example.com")
    _git(src, "config", "user.name", "Test")
    (src / "s.txt").write_text("sub\n", encoding="utf-8")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "sub")
    _git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(src), "sub")
    _git(repo, "config", "-f", ".gitmodules", "submodule.sub.ignore", "dirty")


def _setup(
    tmp_path: Path,
    *,
    checker_on_base: bool = True,
    with_checker: bool = True,
    with_submodule: bool = False,
) -> Path:
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
    if with_submodule:
        _add_submodule(tmp_path, repo)
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

    def test_rfs_dt_004_header_documents_unchecked(self) -> None:
        """檔頭的 exit code 表是呼叫端的正本，unchecked 必須列在 exit 0 那一列。"""
        header = self.SRC.split("set -euo pipefail", 1)[0]
        exit0_row = header[header.index("#   0 ") : header.index("#   1 ")]
        assert "RED_FIRST_RESULT=unchecked" in exit0_row
        assert "red-first: UNCHECKED" in exit0_row
        assert "不是通過" in exit0_row

    def test_rfs_dt_005_pr_cycle_fast_token_list_covers_every_token(self) -> None:
        """pr-cycle-fast 3.0b 把 token 寫成封閉清單（「只會是…其中之一」）並直接放進 --reason。

        腳本新增 token 而清單沒跟上時，下游會把沒列出的 token 當成意外值；從原始碼抽出所有
        token 與清單比對，讓兩邊不能各自漂移。
        """
        emitted = set(re.findall(r"RED_FIRST_RESULT=([a-z][a-z-]*)", self.SRC))
        assert {"pass", "unchecked", "fail", "error", "tree-not-restored"} <= emitted
        fast = (SCRIPTS_DIR.parent.parent / "pr-cycle-fast" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        start = fast.index("token 只會是")
        token_list = fast[start : fast.index("其中之一", start)]
        missing = sorted(t for t in emitted if f"`{t}`" not in token_list)
        assert not missing, f"pr-cycle-fast 3.0b 的 token 清單缺少：{missing}"

    def test_rfs_dt_006_pr_cycle_fast_says_unchecked_is_not_a_pass(self) -> None:
        """pr-cycle-fast 3.0b 的 exit 0 那一列必須寫明 unchecked 不是通過（AC-6）。"""
        fast = (SCRIPTS_DIR.parent.parent / "pr-cycle-fast" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        start = fast.index("#### 3.0b")
        section = fast[start : fast.index("\n### ", start)]
        assert "token 為 `unchecked` 時**不是通過**" in section


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

    def test_rfs_st_008_self_reported_side_effect_is_not_excused(self, tmp_path: Path) -> None:
        """checker 自己列出的副作用不再被豁免（#496 NIT）：工作樹前後不一致一律 exit 3。

        舊版會把 checker 以縮排列出的改動當成「工具副作用」放行；但 checker 在暫存
        worktree 執行、不寫使用者的工作區，那條分支只會讓「自稱是副作用」的改動溜過去。
        """
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="side")
        assert proc.returncode == EXIT_TREE_NOT_RESTORED, proc.stdout + proc.stderr
        assert "side.txt" in proc.stderr
        assert "RED_FIRST_RESULT=tree-not-restored" in proc.stdout

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

    def test_rfs_st_014_unexpected_git_failure_is_error_not_verdict(self, tmp_path: Path) -> None:
        """base 與 PR 沒有共同祖先時 merge-base 失敗；必須是 exit 2，不能以 1 被讀成判定失敗。"""
        repo = _setup(tmp_path)
        _git(repo, "checkout", "-q", "--orphan", "island")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "island")
        _git(repo, "push", "-q", "origin", "island")
        _git(repo, "checkout", "-q", "feature")
        proc, argv_out = _run(tmp_path, repo, FAKE_GH_BASE="island")
        assert proc.returncode == EXIT_ERROR, proc.stdout + proc.stderr
        assert "RED_FIRST_RESULT=error" in proc.stdout
        assert not argv_out.exists()

    def test_rfs_st_013_checker_on_base_is_not_flagged(self, tmp_path: Path) -> None:
        """RFS-ST-012 的對照：checker 不在 PR diff 裡時不得誤報。"""
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo)
        assert proc.returncode == EXIT_CONTINUE, proc.stdout + proc.stderr
        assert "checker modified by this PR" not in proc.stdout


class TestUnchecked:
    """checker 沒有檢查任何東西時，結論不得是 pass（issue #521）。"""

    @pytest.mark.parametrize(
        "mode",
        ["unchecked", "unchecked-marker", "pass-and-unchecked", "sentence-and-pass"],
    )
    def test_rfs_st_015_unchecked_is_its_own_verdict(self, tmp_path: Path, mode: str) -> None:
        """四種形狀：yibi-mvp 現在印的句子、機讀標記，以及兩者各自與 PASS 同時出現。

        後兩種鎖住「unchecked 優先於 PASS」。
        """
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE=mode)
        assert proc.returncode == EXIT_CONTINUE, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=unchecked"
        assert "RED_FIRST_RESULT=pass" not in proc.stdout
        assert "[WARN] red-first: checker 沒有檢查任何東西" in proc.stdout

    @pytest.mark.parametrize("mode", ["partial-unsupported", "inline-marker-and-pass"])
    def test_rfs_st_016_not_unchecked_is_still_pass(self, tmp_path: Path, mode: str) -> None:
        """RFS-ST-015 的對照：結論仍是 pass 的兩種形狀。

        只有部分改動在不支援的目錄（其餘有跑測試），或 `red-first: UNCHECKED` 不是整行。
        """
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE=mode)
        assert proc.returncode == EXIT_CONTINUE, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=pass"

    def test_rfs_st_017_unchecked_marker_does_not_rescue_a_fail(self, tmp_path: Path) -> None:
        """unchecked 只在 checker exit 0 時判定（AC-2）。

        exit 1 帶 FAIL 判定時，即使輸出也有 unchecked 標記，結論仍是 fail。
        """
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="fail-and-unchecked")
        assert proc.returncode == EXIT_VERDICT_FAIL, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=fail"
        assert "RED_FIRST_RESULT=unchecked" not in proc.stdout


class TestTreeNotRestored:
    """從乾淨的狀態開始，跑完後工作樹不乾淨或 HEAD／分支變了，一律 exit 3（AC-4）。

    每個案例鎖住一個面向：submodule 內容、index、HEAD（含工作樹仍乾淨的情況）、分支，
    以及 checker 自己判定失敗時——工作樹沒還原優先於判定，不得以 exit 1 回報。
    """

    @pytest.mark.parametrize(
        ("mode", "with_submodule"),
        [
            ("submodule-edit", True),
            ("stage-new", False),
            ("reset-soft", False),
            ("commit-empty", False),
            ("switch-branch", False),
            ("fail-and-dirty", False),
            ("orphan", False),
        ],
        ids=[
            "submodule-edit",
            "index-change",
            "reset-soft",
            "head-moved-tree-clean",
            "branch-switched",
            "fail-and-dirty",
            "orphan",
        ],
    )
    def test_rfs_st_018_tree_or_head_changed_exits_3(
        self, tmp_path: Path, mode: str, with_submodule: bool
    ) -> None:
        repo = _setup(tmp_path, with_submodule=with_submodule)
        proc, argv_out = _run(tmp_path, repo, FAKE_CHECKER_MODE=mode)
        assert argv_out.exists(), "乾淨的起點應執行 checker"
        assert proc.returncode == EXIT_TREE_NOT_RESTORED, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=tree-not-restored"

    def test_rfs_st_024_detached_start_is_supported(self, tmp_path: Path) -> None:
        """從 detached HEAD 起跑是支援的形狀，結論照常是 pass（#545 第 6 項）。"""
        repo = _setup(tmp_path)
        _git(repo, "checkout", "-q", "--detach")
        proc, argv_out = _run(tmp_path, repo)
        assert argv_out.exists(), "detached HEAD 起點應執行 checker"
        assert proc.returncode == EXIT_CONTINUE, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=pass"

    def test_rfs_st_025_detached_start_then_branch_switch_exits_3(self, tmp_path: Path) -> None:
        """從 detached HEAD 起跑、checker 切到分支：commit 不變，只有分支比對抓得到。"""
        repo = _setup(tmp_path)
        _git(repo, "checkout", "-q", "--detach")
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="switch-branch")
        assert proc.returncode == EXIT_TREE_NOT_RESTORED, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=tree-not-restored"
        assert "所在分支變了（DETACHED -> refs/heads/other）" in proc.stderr

    def test_rfs_st_019_clean_submodule_is_pass(self, tmp_path: Path) -> None:
        """RFS-ST-018[submodule-edit] 的對照：有 submodule 但沒被改時，結論是 pass。"""
        repo = _setup(tmp_path, with_submodule=True)
        proc, _ = _run(tmp_path, repo)
        assert proc.returncode == EXIT_CONTINUE, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=pass"


def _commit_on_branch(repo: Path, branch: str, path: str, content: str) -> None:
    """從 feature 開 branch，寫一個檔並 commit，再切回 feature。"""
    _git(repo, "checkout", "-q", "-b", branch, "feature")
    (repo / path).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", branch)
    _git(repo, "checkout", "-q", "feature")


def _merge_no_commit(repo: Path) -> None:
    _commit_on_branch(repo, "side", "g.txt", "side\n")
    _git(repo, "merge", "-q", "--no-commit", "--no-ff", "side")


def _revert_no_commit(repo: Path) -> None:
    _git(repo, "revert", "--no-commit", "HEAD")


def _cherry_pick_resolved_not_committed(repo: Path) -> None:
    """衝突已 `git add` 解決但尚未 commit：只剩 CHERRY_PICK_HEAD，沒有 unmerged 項目。"""
    _commit_on_branch(repo, "side", "f.txt", "side version\n")
    (repo / "f.txt").write_text("feature version 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "feature 2")
    subprocess.run(  # nosec B603
        ["git", "cherry-pick", "side"], cwd=repo, capture_output=True, check=False, timeout=60
    )
    (repo / "f.txt").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "f.txt")


def _rebase_stopped_at_break(repo: Path) -> None:
    """互動式 rebase 停在 `break`：工作樹乾淨，只剩 rebase-merge 目錄。"""
    editor = repo.parent / "seq-editor.py"
    editor.write_text(
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "p.write_text('break\\n' + p.read_text(encoding='utf-8'), encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = {**os.environ, "GIT_SEQUENCE_EDITOR": f"python3 {editor}"}
    subprocess.run(  # nosec B603
        ["git", "rebase", "-q", "-i", "main"],
        cwd=repo,
        capture_output=True,
        check=True,
        timeout=60,
        env=env,
    )


def _rebase_apply_conflict(repo: Path) -> None:
    """`rebase --apply` 衝突：留下 rebase-apply 目錄（另有 unmerged 項目）。"""
    _git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("main changed\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "main 2")
    _git(repo, "checkout", "-q", "feature")
    subprocess.run(  # nosec B603
        ["git", "rebase", "--apply", "main"],
        cwd=repo,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert (repo / ".git" / "rebase-apply").is_dir(), "前提：rebase-apply 應處於衝突停止狀態"


def _cherry_pick_sequence_mid(repo: Path) -> None:
    """多 commit 的 cherry-pick 停在中途：A 衝突後以 `git commit` 解決（而非 --continue）。

    CHERRY_PICK_HEAD 已被移除、沒有 unmerged、工作樹乾淨，只剩 `.git/sequencer`；B 尚未套用，
    所以 HEAD 不是要檢查的樹（#545 第 2 項）。
    """
    _git(repo, "checkout", "-q", "-b", "side", "feature")
    (repo / "f.txt").write_text("side A\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "A")
    (repo / "g.txt").write_text("g\n", encoding="utf-8")
    _git(repo, "add", "g.txt")
    _git(repo, "commit", "-q", "-m", "B")
    _git(repo, "checkout", "-q", "feature")
    (repo / "f.txt").write_text("feature version 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "feature 2")
    subprocess.run(  # nosec B603
        ["git", "cherry-pick", "feature..side"],
        cwd=repo,
        capture_output=True,
        check=False,
        timeout=60,
    )
    (repo / "f.txt").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "resolved A")
    assert (repo / ".git" / "sequencer").is_dir(), "前提：sequencer 應仍存在"
    assert not (repo / "g.txt").exists(), "前提：B 尚未套用"


def _stash_apply_conflict(repo: Path) -> None:
    """`stash apply` 衝突：留下 unmerged 項目，但沒有任何 *_HEAD 狀態檔。"""
    (repo / "f.txt").write_text("stashed\n", encoding="utf-8")
    _git(repo, "stash", "push", "-q", "-m", "rfs-test")
    (repo / "f.txt").write_text("committed differently\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "diverge")
    subprocess.run(  # nosec B603
        ["git", "stash", "apply"], cwd=repo, capture_output=True, check=False, timeout=60
    )


class TestOperationInProgress:
    """merge／rebase／cherry-pick／revert 進行中時，HEAD 不是要檢查的樹，不得執行 checker（AC-5）。

    進行中守衛排在乾淨檢查之前，所以每個案例都由它自己的條件回報，錯誤訊息指出具體的操作。
    拿掉某一個條件時：merge、revert、cherry-pick、rebase-apply、unmerged 五個案例同時讓工作樹
    不乾淨（或有未解衝突），仍會以 exit 2 擋下，只有訊息斷言（`expected_state in stderr`）轉紅；
    rebase 停在 `break`、以及 cherry-pick 序列中途（只剩 sequencer）時工作樹乾淨，拿掉對應條件
    會讓 checker 被執行而轉紅。
    """

    @pytest.mark.parametrize(
        ("prepare", "expected_state"),
        [
            (_merge_no_commit, "MERGE_HEAD"),
            (_revert_no_commit, "REVERT_HEAD"),
            (_cherry_pick_resolved_not_committed, "CHERRY_PICK_HEAD"),
            (_rebase_stopped_at_break, "rebase（rebase-merge）"),
            (_rebase_apply_conflict, "rebase（rebase-apply）"),
            (_stash_apply_conflict, "未解衝突"),
            (_cherry_pick_sequence_mid, "sequencer"),
        ],
        ids=["merge", "revert", "cherry-pick", "rebase", "rebase-apply", "unmerged", "sequencer"],
    )
    def test_rfs_st_020_in_progress_operation_is_error(
        self, tmp_path: Path, prepare, expected_state: str
    ) -> None:
        repo = _setup(tmp_path)
        prepare(repo)
        proc, argv_out = _run(tmp_path, repo)
        assert proc.returncode == EXIT_ERROR, proc.stdout + proc.stderr
        assert expected_state in proc.stderr
        assert "RED_FIRST_RESULT=error" in proc.stdout
        assert not argv_out.exists(), "操作進行中時不得執行 checker"


def _cherry_pick_no_commit(repo: Path) -> None:
    """`cherry-pick --no-commit` 不留任何狀態檔，只留 staged 改動（AC-8 的起因）。"""
    _commit_on_branch(repo, "side", "g.txt", "side\n")
    _git(repo, "cherry-pick", "--no-commit", "side")


def _merge_squash(repo: Path) -> None:
    """`merge --squash` 同樣不留 MERGE_HEAD，只留 staged 改動。"""
    _commit_on_branch(repo, "side", "g.txt", "side\n")
    _git(repo, "merge", "-q", "--squash", "side")


def _staged_edit(repo: Path) -> None:
    """使用者自己 `git add` 的改動：與上面兩種在 git 裡無法分辨，一併拒絕。"""
    (repo / "f.txt").write_text("staged edit\n", encoding="utf-8")
    _git(repo, "add", "f.txt")


class TestStagedChanges:
    """不留狀態檔、只留 staged 改動的操作，由乾淨檢查以 exit 2 擋下（AC-8）。"""

    @pytest.mark.parametrize(
        "prepare",
        [_cherry_pick_no_commit, _merge_squash, _staged_edit],
        ids=["cherry-pick-no-commit", "merge-squash", "staged-edit"],
    )
    def test_rfs_st_021_staged_changes_are_error(self, tmp_path: Path, prepare) -> None:
        repo = _setup(tmp_path)
        prepare(repo)
        proc, argv_out = _run(tmp_path, repo)
        assert proc.returncode == EXIT_ERROR, proc.stdout + proc.stderr
        assert DIRTY_BEFORE_MSG in proc.stderr
        assert "RED_FIRST_RESULT=error" in proc.stdout
        assert not argv_out.exists(), "有 staged 改動時不得執行 checker"


def _untracked_file(repo: Path) -> None:
    (repo / "wip.txt").write_text("uncommitted\n", encoding="utf-8")


def _unstaged_edit(repo: Path) -> None:
    (repo / "f.txt").write_text("local edit\n", encoding="utf-8")


def _dirty_submodule(repo: Path) -> None:
    with (repo / "sub" / "s.txt").open("a", encoding="utf-8") as fh:
        fh.write("local edit inside the submodule\n")


class TestDirtyBeforeRun:
    """跑之前工作樹不乾淨就拒絕執行（AC-3）。

    checker 若就地把產品碼還原到 merge-base，會覆蓋使用者未 commit 的改動。
    """

    @pytest.mark.parametrize(
        ("prepare", "with_submodule"),
        [
            (_untracked_file, False),
            (_unstaged_edit, False),
            (_staged_edit, False),
            (_dirty_submodule, True),
        ],
        ids=["untracked", "unstaged", "staged", "submodule"],
    )
    def test_rfs_st_009_dirty_before_run_is_error(
        self, tmp_path: Path, prepare, with_submodule: bool
    ) -> None:
        repo = _setup(tmp_path, with_submodule=with_submodule)
        prepare(repo)
        proc, argv_out = _run(tmp_path, repo)
        assert proc.returncode == EXIT_ERROR, proc.stdout + proc.stderr
        assert DIRTY_BEFORE_MSG in proc.stderr
        assert "RED_FIRST_RESULT=error" in proc.stdout
        assert not argv_out.exists(), "工作樹不乾淨時不得執行 checker"


# 以環境變數注入 `status.showUntrackedFiles=no`：只作用於 red-first.sh 內的 git 呼叫，
# 不動 fixture 的 repo config。大型 repo 常為了效能這樣設；設了之後，不帶
# --untracked-files=all 的 `git status --porcelain` 完全不列 untracked 檔
HIDE_UNTRACKED = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "status.showUntrackedFiles",
    "GIT_CONFIG_VALUE_0": "no",
}


class TestUntrackedHiddenByConfig:
    """使用者設定不得讓乾淨檢查漏看 untracked 檔（Round 2 Critical）。

    與 submodule 的 `--ignore-submodules=none` 是同一類問題：git 設定會壓掉 status 的輸出。
    拿掉任一處的 `--untracked-files=all`，對應的案例就會轉紅。
    """

    def test_rfs_st_022_untracked_before_run_is_error_despite_config(self, tmp_path: Path) -> None:
        repo = _setup(tmp_path)
        _untracked_file(repo)
        proc, argv_out = _run(tmp_path, repo, **HIDE_UNTRACKED)
        assert proc.returncode == EXIT_ERROR, proc.stdout + proc.stderr
        assert DIRTY_BEFORE_MSG in proc.stderr
        assert "RED_FIRST_RESULT=error" in proc.stdout
        assert not argv_out.exists(), "有 untracked 檔時不得執行 checker"

    def test_rfs_st_023_untracked_left_by_checker_exits_3_despite_config(
        self, tmp_path: Path
    ) -> None:
        repo = _setup(tmp_path)
        proc, _ = _run(tmp_path, repo, FAKE_CHECKER_MODE="dirty", **HIDE_UNTRACKED)
        assert proc.returncode == EXIT_TREE_NOT_RESTORED, proc.stdout + proc.stderr
        assert proc.stdout.rstrip().splitlines()[-1] == "RED_FIRST_RESULT=tree-not-restored"
        assert "leak.txt" in proc.stderr

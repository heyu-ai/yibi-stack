"""preflight-review-snapshot.sh 的契約與行為測試（issue #372）。

兩層，沿用 test_setup_review_dir.py 的慣例：

* **靜態契約測試** —— 讀 script 原始碼，斷言幾個容易被「順手簡化」掉的不變量
  （`rev-parse -q --verify MERGE_HEAD` 必須包在 `if !` 裡、`--sha` 取值前必須驗 `$#`
  邊界、不得清除呼叫端的 git 環境變數）。

* **行為測試** —— 對真實的拋棄式 repo 跑完整流程，**每一個具名 exit code 都有一個實際
  會觸發它的輸入**。這是刻意的：一個 gate 的「PASS」在你證明它會對已知壞輸入失敗之前
  沒有資訊量，所以 happy path 只佔其中兩個案例，其餘都是正向對照。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from __future__ import annotations

import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
PREFLIGHT = SCRIPTS_DIR / "preflight-review-snapshot.sh"

# 具名 exit code，與 script 檔頭的表格一一對應。
# 這些常數存在的理由是：測試若直接寫裸數字，改動 script 的 exit code 時測試會用
# 「數字對不上」的方式失敗，讀者看不出語意。
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_UNMERGED = 2
EXIT_MERGE_IN_PROGRESS = 3
EXIT_HEAD_MOVED = 4


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )


def _run_preflight(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(PREFLIGHT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _init_repo(path: Path) -> Path:
    """建立一個有一筆 commit 的拋棄式 repo。"""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "f.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "f.txt")
    _git(path, "commit", "-q", "-m", "base")
    return path


def _make_conflict(repo: Path) -> None:
    """製造一個**未解**的 merge 衝突：MERGE_HEAD 存在，且 diff-filter=U 非空。"""
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "f.txt").write_text("side\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "side")
    _git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "main")
    # 衝突使 merge 以非零退出，這是預期行為，故 check=False
    _git(repo, "merge", "side", check=False)


def _make_merge_in_progress_without_conflict(repo: Path) -> None:
    """製造「衝突已解但尚未 commit」：MERGE_HEAD 仍在，但沒有 unmerged entries。

    這個狀態是本 gate 的關鍵案例——只看 `diff-filter=U` 的實作會放行它，但工作區
    此時仍是 merge 中繼態，不是任何 commit 的忠實內容。
    """
    _make_conflict(repo)
    (repo / "f.txt").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "f.txt")  # 解掉衝突但不 commit


# --------------------------------------------------------------------------- #
# 靜態契約測試
# --------------------------------------------------------------------------- #


class TestPreflightSourceContract:
    def test_pfs_dt_001_merge_head_probe_is_wrapped_in_if(self) -> None:
        """PFS-DT-001: `rev-parse -q --verify MERGE_HEAD` 必須包在 `if` 裡

        它在 ref 不存在時 exit 非零。裸寫一行的話，`set -e` 會讓「沒有進行中的 merge」
        這個**正常**情況直接中止整個 script——gate 於是在最常見的路徑上消失。
        """
        src = PREFLIGHT.read_text(encoding="utf-8")
        merge_head_lines = [
            line
            for line in src.splitlines()
            if "--verify MERGE_HEAD" in line and not line.lstrip().startswith("#")
        ]
        assert merge_head_lines, "找不到 MERGE_HEAD 探測（gate 的核心）"
        for line in merge_head_lines:
            assert line.lstrip().startswith("if "), (
                f"MERGE_HEAD 探測必須包在 if 裡，否則 set -e 會在無 merge 時中止：{line!r}"
            )

    def test_pfs_dt_002_sha_flag_checks_arg_count_before_dereference(self) -> None:
        """PFS-DT-002: `--sha` 取 `$2` 之前必須驗 `$#`，否則漏傳值會噴 unbound variable"""
        src = PREFLIGHT.read_text(encoding="utf-8")
        sha_branch = src.split("--sha)", 1)
        assert len(sha_branch) == 2, "找不到 --sha 分支"
        # 邊界檢查必須出現在賦值之前
        after = sha_branch[1]
        guard_idx = after.find('[ "$#" -lt 2 ]')
        assign_idx = after.find('PINNED_SHA="$2"')
        assert guard_idx != -1, "--sha 分支缺少 $# 邊界檢查"
        assert assign_idx != -1, "--sha 分支找不到賦值"
        assert guard_idx < assign_idx, "$# 邊界檢查必須在取 $2 之前"

    def test_pfs_dt_003_does_not_clear_caller_git_env(self) -> None:
        """PFS-DT-003: 本 script 不得清除呼叫端的 GIT_DIR / GIT_WORK_TREE

        rule 11 的 `env -u GIT_DIR ...` 慣例只適用於「這個 script 自己住在哪個 repo」
        那一族（resolve-skill-repo）。本 script 問的是「呼叫端正在哪個 repo 工作」，
        清掉會回答錯的 repo——方向相反，不可照抄。
        """
        src = PREFLIGHT.read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
        assert "env -u GIT_DIR" not in code, (
            "不可清除呼叫端 git 環境——本 script 要回答的正是呼叫端所在的 repo"
        )


# --------------------------------------------------------------------------- #
# 行為測試：每個具名 exit code 都有觸發它的實際輸入
# --------------------------------------------------------------------------- #


class TestPreflightCheckMode:
    def test_pfs_st_001_clean_repo_passes_and_emits_head(self, tmp_path: Path) -> None:
        """PFS-ST-001: 乾淨工作區 -> exit 0，且 stdout 帶出 HEAD sha 供 verify 使用"""
        repo = _init_repo(tmp_path / "clean")
        res = _run_preflight(repo, "check")

        assert res.returncode == EXIT_OK, res.stderr
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        assert f"HEAD={head}" in res.stdout, "check 必須輸出 HEAD=<sha>，否則 verify 無從比對"

    def test_pfs_st_002_unmerged_files_are_rejected(self, tmp_path: Path) -> None:
        """PFS-ST-002: 有未解衝突 -> exit 2（正向對照：gate 必須擋下已知壞輸入）"""
        repo = _init_repo(tmp_path / "conflict")
        _make_conflict(repo)

        # 前提檢查：確認我們真的造出了 unmerged entry，否則這個對照組是空的
        unmerged = _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        assert unmerged, "fixture 沒有造出未解衝突，本對照組無效"

        res = _run_preflight(repo, "check")
        detail = res.stdout + res.stderr
        assert res.returncode == EXIT_UNMERGED, f"應以 {EXIT_UNMERGED} 拒絕：{detail}"
        assert "[FAIL]" in res.stderr
        assert "f.txt" in res.stderr, "錯誤訊息必須列出是哪些檔案未解，否則使用者無從下手"

    def test_pfs_st_003_unmerged_beats_explicit_sha(self, tmp_path: Path) -> None:
        """PFS-ST-003: 未解衝突時即使指定 --sha 也要拒絕

        --sha 的用途是「工作區不可信，改讀這個不可變 SHA」，但未解衝突代表整個
        工作區處於半套用狀態；放行會讓呼叫端誤以為自己拿到了乾淨快照。
        """
        repo = _init_repo(tmp_path / "conflict-sha")
        _make_conflict(repo)
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        res = _run_preflight(repo, "check", "--sha", head)
        assert res.returncode == EXIT_UNMERGED, "未解衝突優先於 --sha，不可被 override"

    def test_pfs_st_004_merge_in_progress_without_conflict_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """PFS-ST-004: 衝突已解但未 commit -> exit 3

        這是只看 `diff-filter=U` 的實作會漏掉的狀態，故單獨立案。
        """
        repo = _init_repo(tmp_path / "merging")
        _make_merge_in_progress_without_conflict(repo)

        # 前提檢查：確認這個 fixture 真的是「有 MERGE_HEAD 但無 unmerged」
        unmerged = _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        assert not unmerged, "fixture 應已解完衝突，否則測到的是 exit 2 而非 exit 3"
        _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")  # 不存在會 raise

        res = _run_preflight(repo, "check")
        assert res.returncode == EXIT_MERGE_IN_PROGRESS, (
            f"應以 {EXIT_MERGE_IN_PROGRESS} 拒絕：{res.stdout}{res.stderr}"
        )
        assert "--sha" in res.stderr, "拒絕訊息必須告訴使用者 override 的方式"

    def test_pfs_st_005_merge_in_progress_with_valid_sha_passes(self, tmp_path: Path) -> None:
        """PFS-ST-005: merge 進行中 + 合法 --sha -> exit 0，並要求 reviewer 用 git show"""
        repo = _init_repo(tmp_path / "merging-pinned")
        _make_merge_in_progress_without_conflict(repo)
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        res = _run_preflight(repo, "check", "--sha", head)
        assert res.returncode == EXIT_OK, res.stderr
        assert f"PINNED={head}" in res.stdout
        assert "git show" in res.stdout, "釘選模式必須明說 reviewer 該怎麼讀檔，否則等於沒釘"

    def test_pfs_st_006_nonexistent_sha_is_rejected(self, tmp_path: Path) -> None:
        """PFS-ST-006: --sha 指向不存在的 commit -> exit 1（否則後續 git show 全部會失敗）"""
        repo = _init_repo(tmp_path / "bad-sha")
        res = _run_preflight(repo, "check", "--sha", "0" * 40)
        assert res.returncode == EXIT_USAGE
        assert "[FAIL]" in res.stderr

    def test_pfs_st_007_sha_flag_without_value_fails_cleanly(self, tmp_path: Path) -> None:
        """PFS-ST-007: `--sha` 漏傳值要乾淨 [FAIL]，不是 set -u 的 unbound variable stacktrace"""
        repo = _init_repo(tmp_path / "sha-noval")
        res = _run_preflight(repo, "check", "--sha")
        assert res.returncode == EXIT_USAGE
        assert "[FAIL]" in res.stderr
        assert "unbound variable" not in res.stderr, "應為乾淨的用法錯誤，而非 set -u 崩潰"

    def test_pfs_st_008_a_tree_dirty_but_not_merging_still_passes(self, tmp_path: Path) -> None:
        """PFS-ST-008: 單純有未 commit 的改動（非 merge）不該被擋

        負向對照：本 gate 的目的是擋 merge 中繼態，不是擋「有 uncommitted 改動」。
        review 一份尚未 commit 的工作成果是完全合法的日常用途，擋掉就是純粹的迴歸。
        """
        repo = _init_repo(tmp_path / "dirty")
        (repo / "f.txt").write_text("edited but not committed\n", encoding="utf-8")

        res = _run_preflight(repo, "check")
        assert res.returncode == EXIT_OK, f"單純髒工作區不可被擋（會誤殺日常 review）：{res.stderr}"


class TestPreflightVerifyMode:
    def test_pfs_st_009_head_unchanged_passes(self, tmp_path: Path) -> None:
        """PFS-ST-009: review 期間 HEAD 沒動 -> exit 0"""
        repo = _init_repo(tmp_path / "stable")
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        res = _run_preflight(repo, "verify", head)
        assert res.returncode == EXIT_OK, res.stderr

    def test_pfs_st_010_head_moved_is_reported(self, tmp_path: Path) -> None:
        """PFS-ST-010: review 期間 HEAD 移動 -> exit 4（這正是 issue #372 的併發情境）"""
        repo = _init_repo(tmp_path / "moved")
        before = _git(repo, "rev-parse", "HEAD").stdout.strip()

        # 模擬另一個 session 在 review 期間 commit
        (repo / "g.txt").write_text("from another session\n", encoding="utf-8")
        _git(repo, "add", "g.txt")
        _git(repo, "commit", "-q", "-m", "concurrent")

        res = _run_preflight(repo, "verify", before)
        assert res.returncode == EXIT_HEAD_MOVED, res.stdout + res.stderr
        assert before[:8] in res.stderr and "->" in res.stderr, (
            "訊息必須同時給出舊與新 sha，使用者才知道基準移到哪去了"
        )

    def test_pfs_st_011_verify_without_argument_fails(self, tmp_path: Path) -> None:
        """PFS-ST-011: verify 缺參數 -> exit 1，且不是 unbound variable"""
        repo = _init_repo(tmp_path / "verify-noarg")
        res = _run_preflight(repo, "verify")
        assert res.returncode == EXIT_USAGE
        assert "unbound variable" not in res.stderr


class TestPreflightUsageGuards:
    def test_pfs_st_012_outside_git_repo_fails(self, tmp_path: Path) -> None:
        """PFS-ST-012: 不在 git repo 內 -> exit 1（而非把它誤報成快照乾淨）"""
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        res = _run_preflight(plain, "check")
        assert res.returncode == EXIT_USAGE
        assert "[FAIL]" in res.stderr

    @pytest.mark.parametrize("args", [(), ("bogus",)])
    def test_pfs_st_013_missing_or_unknown_mode_fails(
        self, tmp_path: Path, args: tuple[str, ...]
    ) -> None:
        """PFS-ST-013: 未指定或未知模式 -> exit 1，並印出用法"""
        repo = _init_repo(tmp_path / f"mode-{'-'.join(args) or 'empty'}")
        res = _run_preflight(repo, *args)
        assert res.returncode == EXIT_USAGE
        assert "用法" in res.stderr


# --------------------------------------------------------------------------- #
# 接線契約：gate 要在**每一個**入口，不是只在寫的時候記得的那一個
# --------------------------------------------------------------------------- #

PLUGIN_SKILLS = SCRIPTS_DIR.parents[1]

# issue #372 點名的四個 review 入口。這份清單就是「涵蓋面」本身——
# 新增 review 類 skill 時要一併加進來，否則新入口會靜默地沒有 gate。
REVIEW_ENTRYPOINTS = [
    "pr-cycle-deep",
    "mob-code-review-only",
    "pr-review-cycle",
    "pr-cycle-fast",
]


class TestPreflightIsWiredIntoEveryReviewEntrypoint:
    @pytest.mark.parametrize("skill", REVIEW_ENTRYPOINTS)
    def test_pfs_dt_004_entrypoint_invokes_preflight_check(self, skill: str) -> None:
        """PFS-DT-004: 每個 review 入口都必須實際呼叫 preflight check

        一個 gate 只裝在「寫的時候記得的那個入口」等於沒裝。這個 parametrize 讓
        「少接一個」變成紅燈，而不是要靠人記得。
        """
        skill_md = PLUGIN_SKILLS / skill / "SKILL.md"
        assert skill_md.is_file(), f"找不到 {skill_md}"
        text = skill_md.read_text(encoding="utf-8")
        assert "preflight-review-snapshot.sh check" in text, (
            f"{skill} 未接上 preflight check —— reviewer 會讀到工作區中間狀態"
        )

    @pytest.mark.parametrize("skill", REVIEW_ENTRYPOINTS)
    def test_pfs_dt_005_entrypoint_documents_the_blocking_exit_codes(self, skill: str) -> None:
        """PFS-DT-005: 每個入口都要寫出 exit 2 / 3 的處置，否則 agent 只會看到 PASS/FAIL

        rule 11「Tool Exit Codes Must Be Listed in SKILL.md Branch Design」：只定義
        PASS/FAIL 的 runbook 會把不同狀態壓平，agent 於是把「merge 進行中」誤route 成
        一般失敗或直接略過。
        """
        text = (PLUGIN_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "`2`" in text and "`3`" in text, f"{skill} 未列出 exit 2 / 3 的具名處置"
        assert "--sha" in text, f"{skill} 未說明 exit 3 的 override 方式"

    @pytest.mark.parametrize("skill", REVIEW_ENTRYPOINTS)
    def test_pfs_dt_006_entrypoint_wires_the_post_round_verify(self, skill: str) -> None:
        """PFS-DT-006: 每個入口都要在 reviewer 回來後跑 verify

        只跑 check 只鎖住「派工當下」；issue #372 的第一手證據是 review **期間**工作區被
        外部改動。少了 verify，那個情境完全沒被涵蓋。
        """
        text = (PLUGIN_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "preflight-review-snapshot.sh verify" in text, (
            f"{skill} 只接了 check 沒接 verify —— review 期間基準被搬走不會被發現"
        )

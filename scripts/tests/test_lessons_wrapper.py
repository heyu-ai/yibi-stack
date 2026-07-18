"""scripts/lessons wrapper 的 --project 注入策略測試。

這支 wrapper 承擔一個讀寫不對稱的保證：

- 寫入（add）必須注入 cwd 偵測到的 project——issue #243 的 287 條 retro lesson
  就是因為沒走 wrapper、cwd 被 `uv run --directory` 換成 yibi-stack 而被誤記。
- 讀取（show / search）必須**不**注入——mycelium CLI 對這兩者的 --project 預設是
  「顯示全部 project」（`cli.py` 的 `default=None`；`db.py` 在 project 為 falsy 時
  不 append `project = ?` 條件，故無 WHERE 過濾），wrapper 若注入就靜默覆寫了該預設，
  呼叫端以為拿到跨 project 結果、實際只拿到 cwd 那個 repo 的，且無任何錯誤訊號。

測法：PATH 注入假 `uv`，把 wrapper 最終組出的引數原樣印出來比對，不真的跑 mycelium。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "lessons"

# git 的 repo 選擇變數優先於 cwd，會蓋掉 fixture 想釘住的 cwd 前提（rule 13
# 「GIT_DIR / GIT_WORK_TREE Override git -C」）。git 在跑 hook 時會 export GIT_DIR，
# 而本 repo 重度依賴 pre-commit——不清掉的話，從 hook context 跑的測試會拿到外層
# repo 名而非 fixture 的 cwd 名，寫入路徑測試無故轉紅（實測 2 failed）。
#
# 注意：只清「測試環境」，不清 wrapper 自身。wrapper 問的是「caller 在哪個 repo」，
# 理應尊重 caller 的 git env（從 hook context 呼叫時 GIT_DIR 指的正是正確的 repo）；
# rule 13 的清除規範只涵蓋「這支 script 自己住在哪」的呼叫。
_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _clean_git_env() -> dict[str, str]:
    """回傳清掉 git repo 選擇變數的 os.environ 副本。"""
    return {k: v for k, v in os.environ.items() if k not in _GIT_ENV_KEYS}


def _make_env(tmp_path: Path) -> dict[str, str]:
    """組出讓 wrapper 可跑的隔離環境：假 HOME + 假 resolve-skill-repo + 假 uv。

    假 uv 把收到的引數原樣印到 stdout，讓測試能斷言 wrapper 到底組了什麼指令。
    """
    fake_home = tmp_path / "home"
    bin_dir = fake_home / ".agents" / "bin"
    bin_dir.mkdir(parents=True)

    skill_repo = tmp_path / "skill_repo"
    skill_repo.mkdir()

    resolver = bin_dir / "resolve-skill-repo"
    resolver.write_text(f'#!/usr/bin/env bash\necho "{skill_repo}"\n', encoding="utf-8")
    resolver.chmod(0o755)

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    uv_shim = shim_dir / "uv"
    uv_shim.write_text('#!/usr/bin/env bash\necho "$@"\n', encoding="utf-8")
    uv_shim.chmod(0o755)

    return {
        **_clean_git_env(),
        "HOME": str(fake_home),
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
    }


def _git(cwd: Path, *args: str) -> None:
    """在 cwd 跑 git，失敗就炸——fixture 前提不成立時要大聲，不要靜默跳過。"""
    subprocess.run(  # nosec B603
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        timeout=30,
        env=_clean_git_env(),
    )


def _init_repo(path: Path) -> None:
    """建一個最小 git repo。

    刻意不用 `git init -b main`：`-b` 需要 git >= 2.28。fixture 自身不該比受測程式更挑
    工具版本（rule 09「A Compatibility Test's Fixture Must Run in the Environment It
    Claims to Cover」）。
    """
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "symbolic-ref", "HEAD", "refs/heads/main")


def _assert_not_git(path: Path) -> None:
    """釘住「這個 cwd 不是 git repo」的前提——不成立時立刻大聲失敗。

    先前此前提只寫在 docstring、無人強制：它成立僅因今日 pytest 的 tmp_path 落在
    /private/var/folders。若 TMPDIR 哪天位於 git repo 內，wrapper 會改走 git 分支，
    測試會以令人困惑的訊息失敗。
    """
    result = subprocess.run(  # nosec B603
        ["git", "rev-parse", "--git-dir"],
        cwd=str(path),
        capture_output=True,
        timeout=30,
        check=False,
        env=_clean_git_env(),
    )
    assert result.returncode != 0, (
        f"fixture 前提不成立：{path} 竟是 git repo（TMPDIR 位於 repo 內？），"
        f"basename(pwd) fallback 分支不會被執行"
    )


def _run_wrapper(
    tmp_path: Path, args: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """在隔離環境執行 wrapper。

    預設 cwd 為一個非 git 目錄（走 `basename(pwd)` fallback 分支）；該前提由
    `_assert_not_git` 明確斷言，而非碰巧成立。
    """
    if cwd is None:
        cwd = tmp_path / "some-project"
        cwd.mkdir()
        _assert_not_git(cwd)
    return subprocess.run(  # nosec B603
        ["bash", str(WRAPPER), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
        cwd=str(cwd),
    )


def _project_of(stdout: str) -> str | None:
    """從 wrapper 組出的引數列中取出 --project 的值（token 比對，不用子字串）。

    子字串比對不夠精確：`"--project some-project" in stdout` 在
    `--project some-project-WRONG-SUFFIX` 下也會通過（rule 09「Assertion Semantic
    Precision」）。
    """
    tokens = stdout.split()
    for i, token in enumerate(tokens):
        if token == "--project":
            return tokens[i + 1] if i + 1 < len(tokens) else None
        if token.startswith("--project="):
            return token.split("=", 1)[1]
    return None


class TestReadCommandsSkipProjectInjection:
    @pytest.mark.parametrize("subcmd", ["show", "search"])
    def test_lsw_dt_001_read_command_does_not_inject_project(
        self, tmp_path: Path, subcmd: str
    ) -> None:
        """LSW-DT-001: show / search 不注入 --project，保留 CLI 的「預設全部」語意。"""
        result = _run_wrapper(tmp_path, [subcmd, "--json"])
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) is None, (
            f"{subcmd} 被注入了 --project，會靜默把跨 project 查詢縮成單一 repo：{result.stdout!r}"
        )
        assert f"lessons {subcmd} --json" in result.stdout

    @pytest.mark.parametrize(
        "project_args",
        [["--project", "yibi-mvp"], ["--project=yibi-mvp"]],
        ids=["space", "equals"],
    )
    def test_lsw_dt_002_read_command_still_forwards_explicit_project(
        self, tmp_path: Path, project_args: list[str]
    ) -> None:
        """LSW-DT-002: 呼叫端明確指定 --project 時，show 仍原樣轉發（不吞掉）。

        兩種形式都測：`--project val` 與 `--project=val`。
        """
        result = _run_wrapper(tmp_path, ["show", *project_args])
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) == "yibi-mvp"

    def test_lsw_dt_006_help_does_not_inject_project(self, tmp_path: Path) -> None:
        """LSW-DT-006: --help 不注入。

        若注入，實際指令會變成 `lessons --help --project X`；click 的 parser 先因未知
        option 而 exit 2，eager 的 --help 根本來不及觸發，help 永遠印不出來（實測）。
        """
        result = _run_wrapper(tmp_path, ["--help"])
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) is None, (
            f"--help 被注入了 --project，真實 CLI 會 exit 2 而印不出 help：{result.stdout!r}"
        )


class TestWriteCommandInjectsProject:
    def test_lsw_dt_003_add_injects_detected_project(self, tmp_path: Path) -> None:
        """LSW-DT-003: add 仍注入 cwd 偵測到的 project（issue #243 的防線，不可退化）。"""
        result = _run_wrapper(tmp_path, ["add", "--key", "k", "--type", "pitfall"])
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) == "some-project", (
            f"add 未注入正確的 --project，會重演 #243 的 287 條 lesson 記錯 project："
            f"{result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "project_args",
        [["--project", "yibi-mvp"], ["--project=yibi-mvp"]],
        ids=["space", "equals"],
    )
    def test_lsw_dt_004_add_does_not_double_inject(
        self, tmp_path: Path, project_args: list[str]
    ) -> None:
        """LSW-DT-004: add 已帶 --project 時不重複注入（兩種形式都測）。

        equals 形式是 scripts/lessons 註解明寫「token-based check 支援 --project=val」的
        存在理由；不測的話，把 `--project=*` arm 拿掉會全數存活（mutation 實證）。
        """
        result = _run_wrapper(tmp_path, ["add", "--key", "k", *project_args])
        assert result.returncode == 0, result.stderr
        assert result.stdout.count("--project") == 1, result.stdout
        assert _project_of(result.stdout) == "yibi-mvp"

    def test_lsw_dt_005_unknown_subcommand_defaults_to_injecting(self, tmp_path: Path) -> None:
        """LSW-DT-005: 未知子命令 fail-safe 走注入路徑。

        未來若新增**寫入類**子命令而漏改 wrapper 的豁免清單，寧可多帶 scope，也不要讓它
        靜默寫到錯的 project——#243 的代價高於多帶一個旗標。用一個刻意不存在的子命令名
        測 fail-safe 本身（delete / retire 已明確豁免，見 test_lsw_dt_006）。
        """
        result = _run_wrapper(tmp_path, ["frobnicate", "--foo", "bar"])
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) == "some-project"

    @pytest.mark.parametrize("subcmd", ["delete", "retire"])
    def test_lsw_dt_006_id_targeted_command_skips_injection(
        self, subcmd: str, tmp_path: Path
    ) -> None:
        """LSW-DT-006: delete / retire 以 --id 操作單一 lesson，wrapper 不得注入 --project。

        CLI 對這兩者不定義 --project option；若 wrapper 注入，click 會因未知 option 以
        exit 2 大聲失敗（issue #242）。此測試釘住豁免，避免日後 fail-safe 預設重新吞掉它們。
        """
        result = _run_wrapper(tmp_path, [subcmd, "--id", "abc"])
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) is None, (
            f"{subcmd} 不應被注入 --project（會讓 click exit 2）：{result.stdout!r}"
        )

    def test_lsw_dt_010_non_git_fallback_emits_warning(self, tmp_path: Path) -> None:
        """LSW-DT-010: 非 git 目錄走 basename(pwd) fallback 時，須印 [WARN] 到 stderr。

        fallback 會生出貌似合理的錯 project 名（如從 ~/Downloads 呼叫記成 Downloads），
        且壓掉了 CLI 在此路徑唯一的大聲訊號（issue #254）。wrapper 至少要對此發聲並
        提示用 --project 指定。拿掉 wrapper 的 [WARN] echo 後本測試轉紅（mutation 反證）。
        """
        result = _run_wrapper(tmp_path, ["add", "--key", "k"])
        assert result.returncode == 0, result.stderr
        assert "[WARN]" in result.stderr, (
            f"非 git 目錄 fallback 未對可能記錯的 project 名發聲：{result.stderr!r}"
        )
        assert "--project" in result.stderr, (
            f"[WARN] 未提示改用 --project 指定正確 scope：{result.stderr!r}"
        )

    def test_lsw_eg_001_no_subcommand_does_not_crash(self, tmp_path: Path) -> None:
        """LSW-EG-001: 不帶任何引數時 `${1:-}` 不因 set -u 而炸。

        只斷言 docstring 指名的 unbound variable 性質：假 uv shim 永遠 exit 0，故
        returncode 不帶資訊（production 實際 exit 2）。
        """
        result = _run_wrapper(tmp_path, [])
        assert "unbound variable" not in result.stderr


class TestGitProjectDetection:
    """釘住 git 偵測分支——production 真正會走的那一條。

    先前所有測試的 cwd 都是非 git 目錄，故 `basename(pwd)` fallback 以外的程式碼零覆蓋：
    把 git 偵測改壞（拿掉 dirname → `--project .git`、換成常數、強制走 fallback → worktree
    名）測試全數存活。agent 實際都是在 git repo 內呼叫 lessons，fallback 幾乎永不執行。
    """

    def test_lsw_dt_007_add_from_git_repo_uses_repo_name(self, tmp_path: Path) -> None:
        """LSW-DT-007: 在 git repo 內，add 注入的是 repo 目錄名（非 `.git`、非常數）。"""
        repo = tmp_path / "my-repo"
        _init_repo(repo)
        result = _run_wrapper(tmp_path, ["add", "--key", "k"], cwd=repo)
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) == "my-repo", (
            f"git repo 內偵測到的 project 錯誤（拿掉 dirname 會變成 .git）：{result.stdout!r}"
        )

    def test_lsw_dt_008_add_from_subdir_uses_repo_root_name(self, tmp_path: Path) -> None:
        """LSW-DT-008: 從 repo 子目錄呼叫，仍取 repo root 名而非子目錄名。

        走的是 git 偵測而非 basename(pwd)——若 fallback 被誤觸，這裡會拿到 `deep`。
        """
        repo = tmp_path / "my-repo"
        _init_repo(repo)
        nested = repo / "nested" / "deep"
        nested.mkdir(parents=True)
        result = _run_wrapper(tmp_path, ["add", "--key", "k"], cwd=nested)
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) == "my-repo", (
            f"子目錄呼叫應取 repo root 名，實得：{result.stdout!r}"
        )

    def test_lsw_dt_009_add_from_linked_worktree_uses_main_repo_name(self, tmp_path: Path) -> None:
        """LSW-DT-009: 從 linked worktree 呼叫，取**主 repo** 名而非 worktree 名。

        這是 `dirname(--git-common-dir)` 存在的唯一理由，也是本 repo 文件化的陷阱：
        worktree 內 `--show-toplevel` 會給出 worktree 名。issue #243 的失敗模式正是
        lesson 被記到錯的 project 名——本測試釘住的就是這條 wrapper 的核心價值。
        """
        repo = tmp_path / "my-repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "f.txt")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")

        wt = repo / ".claude" / "worktrees" / "feat-x"
        _git(repo, "worktree", "add", "-q", "-b", "feat-x", str(wt))

        result = _run_wrapper(tmp_path, ["add", "--key", "k"], cwd=wt)
        assert result.returncode == 0, result.stderr
        assert _project_of(result.stdout) == "my-repo", (
            f"linked worktree 內應取主 repo 名（得到 feat-x 代表用了 --show-toplevel "
            f"或誤走 fallback）：{result.stdout!r}"
        )


class TestReadListDriftGuard:
    def test_lsw_vl_001_every_cli_subcommand_is_classified(self) -> None:
        """LSW-VL-001: wrapper 的讀寫分類必須涵蓋 CLI 所有子命令。

        wrapper 的 `show|search` 是硬編碼，權威來源是 cli.py 的 @lessons.command。
        未知子命令的 fail-safe 是「注入」——對**寫入**正確，但對未來新增的**讀取**
        子命令（list / stats / export）會靜默把它窄化到 cwd 的 repo、零訊號，正是本
        PR 要修的那個 bug。此測試讓「新增子命令」強制做出明確決定，而非繼承錯的預設。
        """
        from tasks.mycelium.cli import lessons

        # 不注入 --project 的子命令：讀取（保留全部 project 語意）或 id-targeted
        # （delete / retire 以精確 --id 操作，CLI 不定義 --project；注入會讓 click exit 2）。
        known_no_inject = {"show", "search", "delete", "retire"}
        # 注入 cwd project 的寫入子命令。
        known_write = {"add"}
        unclassified = set(lessons.commands) - known_no_inject - known_write
        assert not unclassified, (
            f"lessons 新增了未分類的子命令 {sorted(unclassified)}：請先在 scripts/lessons 決定"
            f"它是「不注入」（讀取，或以 --id 操作的 delete/retire——加進 case 豁免清單）或"
            f"「寫入」（維持注入），再同步更新本測試。漏改的話，新的讀取子命令會靜默只回傳 "
            f"cwd 那個 repo 的結果；新的 id-targeted 子命令則會被注入 --project 而 click exit 2。"
        )

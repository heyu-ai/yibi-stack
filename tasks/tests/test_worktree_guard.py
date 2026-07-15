"""tasks/_worktree_guard.py 的行為測試（issue #237）。

本模組是 `scripts/assert_not_worktree.sh` 的薄包裝，故這裡**不重測偵測邏輯**
（那是 scripts/tests/test_assert_not_worktree.py 的 72 個測試的職責）。這裡只測
包裝層自己的契約：

1. 把 exit code 正確轉成「放行 / SystemExit(1)」
2. 每一條「腳本跑不起來」的路徑都 fail-closed（不是 fail-open）
3. command 字串原樣傳給腳本（[FAIL] 訊息才能給出可照抄的指令）

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from __future__ import annotations

import subprocess  # nosec B404
from pathlib import Path

import pytest

from tasks import _worktree_guard
from tasks._worktree_guard import assert_not_worktree


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=False
    )


def _init_repo_portable(root: Path) -> None:
    """以舊 git 也支援的方式 init（不用 `git init -b`，那是 2.28+）。

    理由同 scripts/tests/test_assert_not_worktree.py：fixture 不該比受測目標更挑環境。
    """
    _run(["git", "init", "-q", str(root)])
    _run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"])


def _make_repo(root: Path) -> Path:
    """建立一個有 initial commit 的 git repo（worktree add 需要至少一個 commit）。"""
    root.mkdir(parents=True, exist_ok=True)
    _init_repo_portable(root)
    _run(["git", "-C", str(root), "config", "user.email", "test@example.com"])
    _run(["git", "-C", str(root), "config", "user.name", "test"])
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _run(["git", "-C", str(root), "add", "README.md"])
    _run(["git", "-C", str(root), "commit", "-qm", "init"])
    return root


def _make_worktree(tmp_path: Path) -> Path:
    """回傳一個真實的 linked worktree 路徑。"""
    repo = _make_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(wt)])
    return wt


class TestAssertNotWorktree:
    def test_wg_dt_001_worktree_is_blocked(self, tmp_path: Path) -> None:
        """WG-DT-001: repo_root 是 worktree -> SystemExit(1)。"""
        wt = _make_worktree(tmp_path)
        with pytest.raises(SystemExit) as exc:
            assert_not_worktree("uv run python -m tasks.scheduler install", repo_root=wt)
        assert exc.value.code == 1

    def test_wg_dt_002_main_repo_passes(self, tmp_path: Path) -> None:
        """WG-DT-002: repo_root 是主 repo -> 放行（不得誤擋）。

        誤擋比漏擋更容易被發現，但一樣是 bug：主 repo 裝不了東西。
        """
        repo = _make_repo(tmp_path / "repo")
        assert_not_worktree("uv run python -m tasks.scheduler install", repo_root=repo)

    def test_wg_eg_001_non_git_dir_passes(self, tmp_path: Path) -> None:
        """WG-EG-001: 非 git 目錄 -> 放行，沿用腳本的 fail-open 契約。

        解壓 zip 後安裝是合法情境；不是 git repo 就不可能是 worktree。包裝層不得
        自作主張收緊，否則與腳本的契約分岔。
        """
        plain = tmp_path / "plain"
        plain.mkdir()
        assert_not_worktree("uv run python -m tasks.scheduler install", repo_root=plain)

    def test_wg_dt_003_command_reaches_script_message(
        self, tmp_path: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """WG-DT-003: command 原樣傳進腳本，出現在 [FAIL] 訊息裡。

        這正是 issue #237 把腳本的 `make ${TARGET}` 硬編前綴拿掉的理由：Python 呼叫端
        的復原指令不是 make。若前綴被改回去，這個斷言會抓到「make uv run python ...」。
        """
        wt = _make_worktree(tmp_path)
        command = "uv run python -m tasks.mycelium insight install-hook"
        with pytest.raises(SystemExit):
            assert_not_worktree(command, repo_root=wt)
        err = capfd.readouterr().err
        assert command in err
        assert f"make {command}" not in err, "腳本又替 Python 呼叫端補上了 make 前綴"


class _FakeSubprocess:
    """替換 _worktree_guard 命名空間裡的 `subprocess` 名稱。

    **必須整個換掉名稱，不可 `setattr(_worktree_guard.subprocess, "run", ...)`**：
    後者拿到的是真正的 subprocess module，patch 下去是全域生效，連 guard 自己要跑的
    守門腳本都會被打壞（而且 mypy 會以 attr-defined 擋下這種穿透 module 的存取）。

    `TimeoutExpired` 必須保留：`_worktree_guard` 的 `except subprocess.TimeoutExpired`
    在例外發生時才從自己的 module global 解析這個名稱，少了它會變成 AttributeError。
    """

    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, *, raises: BaseException | None = None, returncode: int = 0) -> None:
        self._raises = raises
        self._returncode = returncode

    def run(self, *_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if self._raises is not None:
            raise self._raises
        return subprocess.CompletedProcess(args=[], returncode=self._returncode)


class _NoBashShutil:
    """which() 永遠找不到執行檔。"""

    @staticmethod
    def which(_name: str) -> str | None:
        return None


class TestFailClosed:
    """腳本跑不起來時必須擋下，而不是放行。

    這整組對應 PR #234 反覆修掉的 fail-open 形狀：任何「判不出來」都不能放行。
    """

    def test_wg_eg_002_missing_script_blocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """WG-EG-002: 守門腳本不存在 -> SystemExit(1) + 具名 [FAIL]。"""
        monkeypatch.setattr(_worktree_guard, "GUARD_SCRIPT", tmp_path / "nope.sh")
        with pytest.raises(SystemExit) as exc:
            assert_not_worktree("uv run python -m tasks.scheduler install")
        assert exc.value.code == 1
        assert "[FAIL]" in capfd.readouterr().err

    def test_wg_eg_003_missing_bash_blocks(
        self, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """WG-EG-003: 找不到 bash -> SystemExit(1)。"""
        monkeypatch.setattr(_worktree_guard, "shutil", _NoBashShutil)
        with pytest.raises(SystemExit) as exc:
            assert_not_worktree("uv run python -m tasks.scheduler install")
        assert exc.value.code == 1
        assert "bash" in capfd.readouterr().err

    def test_wg_eg_004_timeout_blocks(
        self, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """WG-EG-004: 腳本逾時 -> SystemExit(1)，不得當成「沒問題」放行。"""
        fake = _FakeSubprocess(raises=subprocess.TimeoutExpired(cmd="bash", timeout=1))
        monkeypatch.setattr(_worktree_guard, "subprocess", fake)
        with pytest.raises(SystemExit) as exc:
            assert_not_worktree("uv run python -m tasks.scheduler install")
        assert exc.value.code == 1
        assert "[FAIL]" in capfd.readouterr().err

    def test_wg_eg_005_oserror_blocks(
        self, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """WG-EG-005: 執行腳本本身 OSError（如 exec 權限問題）-> SystemExit(1)。"""
        monkeypatch.setattr(
            _worktree_guard, "subprocess", _FakeSubprocess(raises=OSError("permission denied"))
        )
        with pytest.raises(SystemExit) as exc:
            assert_not_worktree("uv run python -m tasks.scheduler install")
        assert exc.value.code == 1
        assert "[FAIL]" in capfd.readouterr().err

    @pytest.mark.parametrize("code", [1, 2, 127])
    def test_wg_dt_004_any_nonzero_blocks(self, code: int, monkeypatch: pytest.MonkeyPatch) -> None:
        """WG-DT-004: **任何**非 0 exit code 都擋下，不分辨原因。

        包裝層刻意不解讀 returncode 的語意——腳本已把「是 worktree」與「判不出來」
        全部歸進非 0。在這裡加解讀（例如「只有 1 才擋」）就是新的 fail-open。
        127 = command not found，正是那種「不解讀就會被誤放行」的值。
        """
        monkeypatch.setattr(_worktree_guard, "subprocess", _FakeSubprocess(returncode=code))
        with pytest.raises(SystemExit) as exc:
            assert_not_worktree("uv run python -m tasks.scheduler install")
        assert exc.value.code == 1

    def test_wg_dt_005_zero_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WG-DT-005: exit 0 -> 放行。

        與 DT-004 成對：只證明「非 0 會擋」不夠，一個永遠 raise 的包裝也能讓 DT-004
        全綠。這條確認 0 真的被當成放行。
        """
        monkeypatch.setattr(_worktree_guard, "subprocess", _FakeSubprocess(returncode=0))
        assert_not_worktree("uv run python -m tasks.scheduler install")

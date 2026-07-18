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

import importlib
import subprocess  # nosec B404
from collections.abc import Iterator
from pathlib import Path

import click
import pytest

from tasks import _worktree_guard
from tasks._worktree_guard import GUARD_SCRIPT, assert_not_worktree

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """執行 setup 用的 git 指令；**失敗即 raise**。

    `check=True` 不是潔癖：fixture 悄悄失敗會讓測試因錯的理由變綠。若 `git worktree add`
    失敗，`wt` 根本不存在，guard 會走「[FAIL] 目錄不存在」那條路 exit 1，於是 WG-DT-001
    照樣通過——但它驗到的是「目錄不存在」而非「偵測到 worktree」。（由 mob review 的
    codex 與 agy 兩個 voice 各自獨立指出。）
    """
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=True
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
    """回傳一個真實的 linked worktree 路徑。

    建完後斷言它真的被 git 登記為 linked worktree——`check=True` 只擋「指令失敗」，
    這條擋的是「指令成功了但產物不是我們要的東西」，否則後續斷言驗到的可能是別的狀態。
    """
    repo = _make_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(wt)])
    listed = _run(["git", "-C", str(repo), "worktree", "list", "--porcelain"]).stdout
    assert f"worktree {wt.resolve()}" in listed, f"fixture 未建出 linked worktree：{listed}"
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

    @pytest.mark.parametrize("code", [1, 2, 126, 127, -9, -15])
    def test_wg_dt_004_any_nonzero_blocks(self, code: int, monkeypatch: pytest.MonkeyPatch) -> None:
        """WG-DT-004: **任何**非 0 exit code 都擋下，不分辨原因。

        包裝層刻意不解讀 returncode 來決定擋不擋——腳本已把「是 worktree」與「判不出來」
        全部歸進非 0。在這裡加解讀（例如「只有 1 才擋」）就是新的 fail-open。
        負值（被訊號殺掉）是最容易在日後被誤「正規化」成 0 的值，故一併釘住。
        """
        monkeypatch.setattr(_worktree_guard, "subprocess", _FakeSubprocess(returncode=code))
        with pytest.raises(SystemExit) as exc:
            assert_not_worktree("uv run python -m tasks.scheduler install")
        assert exc.value.code == 1

    @pytest.mark.parametrize("code", [2, 42, 125, 126, 127, 137, 143, -9, -15])
    def test_wg_dt_006_abnormal_exit_is_not_silent(
        self, code: int, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """WG-DT-006: 腳本契約外的離開碼必須由 wrapper 自己出聲，不得靜默。

        腳本的契約只有 exit 0 / exit 1（見其 header）。其他值都不是它產生的，故不存在
        「它已經印過訊息」這個前提；此時 wrapper 若也沉默，使用者只拿到一個沒有任何解釋
        的 exit 1——而本模組的整個論點是「判不出來必須大聲」。

        參數涵蓋實測過的兩種訊號形狀：**137/143**（bash 的子行程被殺，bash 以 128+N 收場，
        是**正值**）與 **-9/-15**（bash 自己被殺）。首版條件寫成 `< 0 or in (126, 127)`，
        漏掉前者與 2..125——列舉必然漏，故改以契約（!= 1）為界。
        （round 2：codex 指出應以文件化的離開碼為界，agy 實證指出 128+N 漏網。）

        DT-004 涵蓋不到這條：它只斷言 exit code，而 _FakeSubprocess 從不寫 stderr，
        所以有沒有訊息它都會綠（由 mob review 的 comment-analyzer 指出）。
        """
        monkeypatch.setattr(_worktree_guard, "subprocess", _FakeSubprocess(returncode=code))
        with pytest.raises(SystemExit):
            assert_not_worktree("uv run python -m tasks.mycelium insight install-hook")
        err = capfd.readouterr().err
        assert "[FAIL]" in err
        assert str(code) in err, "訊息未指出實際的離開碼"
        assert "uv run python -m tasks.mycelium insight install-hook" in err, "訊息未指名指令"

    def test_wg_dt_007_script_owned_exit_stays_silent(
        self, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """WG-DT-007: exit 1（腳本契約內、它自己會印訊息）時 wrapper 不得重複發聲。

        與 DT-006 成對。腳本已為 exit 1 印過針對 command 客製的 [FAIL]；wrapper 再印一次
        會變成兩段互相矛盾的診斷（「偵測到 worktree」+「異常終止」），訓練讀者忽略警告。
        沒有這條，把 DT-006 的條件放寬成「所有非 0 都印」也會全綠。

        只測 1：契約內的非 0 就只有它。首版還放了 2，那是把「腳本沒有的出口」誤當成
        script-owned——正是 round 2 修掉的誤解。
        """
        monkeypatch.setattr(_worktree_guard, "subprocess", _FakeSubprocess(returncode=1))
        with pytest.raises(SystemExit):
            assert_not_worktree("uv run python -m tasks.scheduler install")
        assert "[FAIL]" not in capfd.readouterr().err, "wrapper 對腳本已處理的離開碼重複發聲"

    def test_wg_dt_005_zero_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WG-DT-005: exit 0 -> 放行。

        與 DT-004 成對：只證明「非 0 會擋」不夠，一個永遠 raise 的包裝也能讓 DT-004
        全綠。這條確認 0 真的被當成放行。
        """
        monkeypatch.setattr(_worktree_guard, "subprocess", _FakeSubprocess(returncode=0))
        assert_not_worktree("uv run python -m tasks.scheduler install")


# 已知會把 repo 路徑寫進機器層級狀態的 click 安裝指令。
# 這是 Makefile 那側 GUARDED_TARGETS 的 Python 對應物。
#
# key 是 (cli 檔, click group, 指令名) 三元組，**不能只用指令名**：insight 與 recap 的
# 指令名都叫 install-hook，只比對名字的話拿掉其中一個仍會撞到另一個而全綠——首版就是
# 這樣寫的，突變驗證（M14）抓到它是假測試。
_GUARDED_CLI_COMMANDS = {
    ("tasks/scheduler/cli.py", "cli", "install"): "uv run python -m tasks.scheduler install",
    (
        "tasks/mycelium/cli.py",
        "handover",
        "install-hooks",
    ): "uv run python -m tasks.mycelium handover install-hooks",
    (
        "tasks/mycelium/cli.py",
        "insight",
        "install-hook",
    ): "uv run python -m tasks.mycelium insight install-hook",
    (
        "tasks/mycelium/cli.py",
        "recap",
        "install-hook",
    ): "uv run python -m tasks.mycelium recap install-hook",
}

# 非 click 的進入點（獨立腳本的 main()），掃不到，逐一列出。
_GUARDED_SCRIPTS = {"scripts/register_skill_repo.py": "make install"}


def _walk_commands(group: click.Group, group_name: str) -> Iterator[tuple[str, str]]:
    """遞迴走訪 click group，yield (所屬 group 名, 指令名)。

    **group 自己也要 yield，不能只 yield 葉節點**：click 的 group 可以用
    `invoke_without_command=True` 直接執行，所以一個名為 `install*` 的 group 同樣是進入點。
    首版只 yield 非 group 的葉節點，實測確認它整個逃掉：

        @root.group("install-agent", invoke_without_command=True)  # 有子指令 status
        -> 走訪結果 [('cli', 'install-plain'), ('install-agent', 'status')]
        -> install-agent 從未出現；只有它的子指令，而 status 不以 install 開頭故被濾掉

    （由 mob review round 3 的 codex voice 指出，探針證實。）
    """
    for name, cmd in group.commands.items():
        yield group_name, name
        if isinstance(cmd, click.Group):
            yield from _walk_commands(cmd, name)


def _scan_install_commands() -> set[tuple[str, str, str]]:
    """問 click 本人：tasks/**/cli.py 裡所有 install* 指令的 (檔案, group, 指令名)。

    **用 introspection 而非正規表示式**：首版用 regex 掃原始碼，三個 review voice 都指出
    它太脆，而 Claude voice 量化了危害——`@cli.command()` 後面夾一個 `@click.option(...)`
    再 `def install(` 這種寫法，**本 repo 的 tasks/*/cli.py 裡已有 32 個指令在用**，正是
    regex 的 `\\)\\s*\\ndef` 抓不到的形狀。也就是說：只要有人給既有的 install 加一個
    `--force` 選項，它就會靜默地從清單掃描裡消失。其他漏網形狀還有 `@insight.command()`
    的隱式命名（regex 把 group 寫死成 `cli`）、`command("x", short_help=...)`、
    `command(name="x")`、結尾逗號。

    click 自己的 registry 是唯一權威，且完全不受格式影響——四種漏網形狀一次全解。
    """
    found: set[tuple[str, str, str]] = set()
    for cli_path in sorted(_REPO_ROOT.glob("tasks/**/cli.py")):
        rel = cli_path.relative_to(_REPO_ROOT)
        module = importlib.import_module(".".join(rel.with_suffix("").parts))
        root = getattr(module, "cli", None)
        if not isinstance(root, click.Group):
            continue
        for group_name, cmd_name in _walk_commands(root, "cli"):
            if cmd_name.startswith("install"):
                found.add((str(rel), group_name, cmd_name))
    return found


class TestGuardedSinkInventory:
    """WG-DT-008/009: 把「哪些進入點必須有 guard」變成機械檢查，而不是靠人記得。

    issue #237 的成因不是有人拿掉了 guard，而是**沒有人列全**：issue 點名 2 個進入點，
    實際有 5 個，而最暴露的兩個（insight / recap install-hook）連 make target 都沒有，
    於是用 Makefile 當搜尋索引的人必然看不到它們。

    刻意**不**做「全掃 tasks/**/cli.py 找 Path.home() 寫入」——mob review 的 codex voice
    正確指出那個形狀兩頭都會漏：uninstall 路徑合法寫 settings.json 卻會被誤報（false
    positive），而經由 helper 間接抵達的 sink 又掃不到（false negative）。改用窄形式：
    釘住已知清單，並用命名慣例強制新的 install 指令入列。

    殘留（明說以便日後 re-probe。這段被 round 2 與 round 3 各修正過一次，兩次都是因為
    它比實情樂觀——殘留說明本身也是一種會衰減的宣稱，rule 11）：
    - 新 sink 若**不叫 install\\***（如 `setup-agent`、`link-hook`）仍抓不到。這是刻意的
      取捨——窄而可信，勝過寬而必然被關掉。
    - 非 click 的進入點（獨立腳本的 main()）掃不到，故 `_GUARDED_SCRIPTS` 手動列出。
    - **檔名不是 `tasks/**/cli.py`** 就不在 glob 範圍內：`tasks/<mod>/commands.py`、
      `tasks/<mod>/cli/__init__.py` 這種 package 形式、或 `scripts/` 底下的 click 進入點，
      glob 掃不到，而上一條的 `_GUARDED_SCRIPTS` 只涵蓋**非 click** 的腳本，補不到它們。
    - 指令若不掛在該模組的 `cli` group 底下（例如另建一個 group 但沒 add 進 cli），
      click 的 registry 走不到它。
    - **lazy / 自訂 group**：本掃描讀 `group.commands`（eager mapping）。若日後有人改用
      覆寫 `list_commands()` / `get_command()` 的 lazy group，其子指令不會出現在
      `commands` 裡而整批逃掉。本 repo 目前全是 decorator 填充的普通 `click.Group`，
      故 `commands` 是完整的；不為假想情境改寫成建 `click.Context` 的形式，是因為那會替
      一個「該無聊地可靠」的測試加進 ctx 建構的失敗模式。改用 lazy group 時要回來補這裡。
      （由 mob review round 3 的 codex voice 指出。）

    歷史（只記已修好的不一致，不要與上面的殘留混為一談）：round 2 之前實作用的是
    `tasks/*/cli.py`（單層）卻宣稱掃 `tasks/**/cli.py`，巢狀路徑連宣稱的範圍都漏——glob
    的 `*` 不跨 `/`（rule 02）。現已改用 `**`，使實作與宣稱一致；但「不在 tasks/**/cli.py
    就抓不到」這個殘留本身依然成立，見上面第三條。
    （round 3 的 claude voice 指出：改寫時把那條殘留降格成歷史註記，讀起來像已解決。）
    """

    def test_wg_dt_008_every_guarded_entry_point_calls_the_guard(self) -> None:
        """WG-DT-008: 清單上的每個進入點都必須帶著自己的復原指令呼叫 guard。"""
        by_file: list[tuple[str, str]] = list(_GUARDED_SCRIPTS.items())
        by_file += [(path, cmd) for (path, _g, _n), cmd in _GUARDED_CLI_COMMANDS.items()]
        for rel_path, command in by_file:
            source = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
            assert f'assert_not_worktree("{command}"' in source, (
                f"{rel_path} 未以 {command!r} 呼叫 assert_not_worktree——"
                f"guard 被移除，或復原指令漂掉了"
            )

    def test_wg_dt_009_no_install_command_escapes_the_inventory(self) -> None:
        """WG-DT-009: tasks/*/cli.py 裡的 install* 指令集合必須與清單**完全相等**。

        這條抓的是 issue #237 的**成因**而非症狀：新增一個 install-hook 卻忘了 guard 時，
        DT-008 不會紅（它只檢查清單上的），行為測試也不會紅（沒人為它寫測試）。這條會紅，
        因為新指令不在清單裡——作者被迫把它列進來，而列進來就會被 DT-008 要求 guard。

        用相等而非單向包含：反向（清單有、程式碼沒有）代表指令被刪或改名，此時 DT-008
        的斷言字串會過期而變成永遠通過的空檢查。兩個方向都要紅。
        """
        found = _scan_install_commands()
        assert found, "掃不到任何 install 指令——正規表示式已過期，這個檢查形同虛設"

        inventory = set(_GUARDED_CLI_COMMANDS)
        missing = found - inventory
        stale = inventory - found
        assert not missing, (
            f"這些 install 指令不在 _GUARDED_CLI_COMMANDS 清單上：{sorted(missing)}。"
            f"它若會把 repo 路徑寫進機器層級狀態（plist / settings.json / config.json），"
            f"請加上 assert_not_worktree 並列入清單；若不會，請在清單旁註明豁免理由。"
        )
        assert not stale, (
            f"清單列了程式碼裡不存在的指令：{sorted(stale)}。"
            f"指令被刪或改名時，DT-008 的斷言會退化成永遠通過的空檢查。"
        )

    def test_wg_dt_010_guard_script_exists_at_the_resolved_path(self) -> None:
        """WG-DT-010: GUARD_SCRIPT 必須指到真實存在的檔案。

        它是由 PROJECT_ROOT 組出來的；repo 結構一改（如 scripts/ 更名）而沒人動這裡，
        每個呼叫端都會在執行期才炸「找不到守門腳本」——那是 fail-closed，但是在使用者
        面前才發現。這條讓它在 CI 就紅。
        """
        assert GUARD_SCRIPT.is_file(), f"守門腳本不存在：{GUARD_SCRIPT}"

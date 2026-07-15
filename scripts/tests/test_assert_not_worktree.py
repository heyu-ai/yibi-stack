"""assert_not_worktree.sh 的行為測試。

這支腳本擋的是一個「安靜壞掉」的失敗鏈（issue #232 附帶發現）：
在 worktree 裡跑 make install -> 全域 symlink 指向 worktree ->
分支合併後 worktree 被刪 -> 所有 skill 失效。

Makefile 既有的安裝後 gate 在結構上擋不住這個 case：它比對
`resolve-skill-repo 輸出 == $(CURDIR)`，而 worktree 裡兩者本來就相等。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "assert_not_worktree.sh"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=False
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(root), *args])


def _init_repo_portable(root: Path, *init_args: str) -> None:
    """以「舊 git 也支援」的方式 init 並把預設分支設成 main。

    不可用 `git init -b main`：`-b` 是 git 2.28（2020）才加入。本測試檔的重點之一
    正是驗證舊 git 上的行為（ANW-EG-004），若 fixture 自己就需要新 git，在真正的
    舊環境下會先掛在 fixture 而非測到腳本——宣稱測相容性、實際沒測到。
    （由 mob review 的 codex voice 指出。）

    `git symbolic-ref HEAD` 在 init 之後、commit 之前設定，古老 git 皆支援。
    """
    _run(["git", "init", "-q", *init_args, str(root)])
    _run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"])


def _make_repo(root: Path) -> Path:
    """建立一個有 initial commit 的 git repo（git worktree add 需要至少一個 commit）。"""
    root.mkdir(parents=True, exist_ok=True)
    _init_repo_portable(root)
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    return root


class TestAssertNotWorktree:
    def test_anw_st_001_main_repo_passes_silently(self, tmp_path: Path) -> None:
        """ANW-ST-001: 主 repo 放行，且不產生任何輸出（安裝正常路徑不該被吵）。"""
        repo = _make_repo(tmp_path / "repo")
        result = _run(["bash", str(GUARD), str(repo), "install"])
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr == ""

    def test_anw_dt_001_worktree_is_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-001: 在 worktree 內必須 exit 1 擋下。

        這是本腳本存在的唯一理由：worktree 的 checkout 是完整的，
        resolve-skill-repo 的 tasks/mycelium 身分檢查照樣會通過，
        Makefile 的 resolved == CURDIR gate 也照樣會通過。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        added = _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        assert added.returncode == 0, added.stderr

        result = _run(["bash", str(GUARD), str(wt), "install"])
        assert result.returncode == 1
        assert "worktree" in result.stderr

    def test_anw_st_002_failure_names_main_repo_and_target(self, tmp_path: Path) -> None:
        """ANW-ST-002: [FAIL] 訊息必須指出主 repo 路徑與 target 名稱。

        錯誤訊息要能自己講出修法（CLAUDE.md：每個外部呼叫都要有可行動的 [FAIL]）。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

        result = _run(["bash", str(GUARD), str(wt), "install-force-one"])
        assert result.returncode == 1
        # 主 repo 的絕對路徑要出現在 cd 指令裡，使用者才知道去哪
        assert str(repo.resolve()) in result.stderr
        # target 名稱要被帶進訊息，不能寫死 "install"
        assert "install-force-one" in result.stderr
        # worktree 自身路徑也要印出來，讓使用者確認被擋的是哪一個
        assert str(wt.resolve()) in result.stderr

    def test_anw_eg_001_non_git_dir_passes(self, tmp_path: Path) -> None:
        """ANW-EG-001: 非 git repo 放行（fail-open）。

        下載 zip 解壓後安裝是合法情境；且不是 git repo 就不可能是 worktree。
        擋下它會是回歸。
        """
        plain = tmp_path / "plain"
        plain.mkdir()
        result = _run(["bash", str(GUARD), str(plain), "install"])
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""

    def test_anw_eg_002_diagnostics_go_to_stderr_not_stdout(self, tmp_path: Path) -> None:
        """ANW-EG-002: [FAIL] 診斷一律走 stderr（rule 13）。

        make 的 stdout 可能被 parse 或 redirect，診斷混進去會讓下游靜默失敗。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

        result = _run(["bash", str(GUARD), str(wt), "install"])
        assert result.stdout == ""
        assert "[FAIL]" in result.stderr

    def test_anw_dt_011_dangling_git_symlink_is_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-011: .git 是 dangling symlink 的 worktree 仍須擋下。

        `-e` 會**跟隨** symlink，所以 dangling 的 .git（連結還在、目標沒了）會讓
        `[ ! -e ]` 為真而走進 fail-open。實測（修法前 exit 0，由 mob review 的
        codex voice 指出）：把真 worktree 的 .git 換成 dangling symlink 後遭放行。

        `-L` 測的是「連結本身存在」，與 -e 聯用才等於「真的沒有 .git 項目」。
        本測試經突變驗證：拿掉 `[ ! -L ]` 會讓它失敗。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        (wt / ".git").unlink()
        (wt / ".git").symlink_to(repo / ".git" / "worktrees" / "gone")

        assert (wt / ".git").is_symlink(), "測試前提不成立：.git 應為 symlink"
        assert not (wt / ".git").exists(), "測試前提不成立：symlink 應為 dangling"

        result = _run(["bash", str(GUARD), str(wt), "install"])
        assert result.returncode == 1, (
            f"dangling .git symlink 遭放行（fail-open）：{result.stderr!r}"
        )
        assert "[FAIL]" in result.stderr

    @pytest.mark.parametrize(
        "env_var",
        [
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_COMMON_DIR",
            "GIT_INDEX_FILE",
            "GIT_CEILING_DIRECTORIES",
        ],
    )
    def test_anw_eg_010_git_env_cannot_defeat_guard_from_subdir(
        self, tmp_path: Path, env_var: str
    ) -> None:
        """ANW-EG-010: 從 worktree 的「子目錄」呼叫時，git 環境變數同樣不得擊穿 gate。

        GIT_CEILING_DIRECTORIES 是實測唯一在此路徑會擊穿的變數（由 mob review 的
        silent-failure-hunter 指出）：設成 worktree 路徑時，從子目錄呼叫會讓 git
        停止向上尋找而回報非 repo -> exit 0。

        目前 7 個 Makefile 呼叫點都傳 $(CURDIR)（repo 根），走不到這條路徑，但
        清掉是零成本，且這是最後一個 env 操控的缺口。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        sub = wt / "sub"
        sub.mkdir()

        env = dict(os.environ)
        env[env_var] = str(wt) if env_var == "GIT_CEILING_DIRECTORIES" else str(repo / ".git")
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(sub), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, (
            f"{env_var} 從子目錄擊穿 gate（fail-open）：{result.stdout!r} {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "env_var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"]
    )
    def test_anw_eg_003_inherited_git_env_cannot_defeat_guard(
        self, tmp_path: Path, env_var: str
    ) -> None:
        """ANW-EG-003: 繼承的 git 環境變數不得讓 gate 失效。

        GIT_DIR 等變數的優先權高於 `git -C`，設定後 git 會回報那個 repo 而無視 -C。

        實證範圍（誠實標註，勿誤讀為四個都經過驗證）：
        - GIT_DIR 是**唯一實測會擊穿本 gate 的向量**。修法前 GIT_DIR=<main>/.git
          讓本腳本在 worktree 內從 exit 1 變成 exit 0，即安靜放行 worktree 安裝。
          此參數經突變驗證：移掉 env -u 後本測試會失敗。
        - 其餘三個變數目前無論有無 env -u 都會通過，屬 defense-in-depth，
          釘住它們是為了防止日後 git 行為改變或 _GIT 被誤改。移掉 env -u
          不會讓那三個參數失敗——不要據此以為它們是實證漏洞。

        這條路徑不是假想：git hook 執行期間會設 GIT_DIR，而本 repo 大量用 pre-commit。
        同一 root cause 見 PR #233 對 resolve-skill-repo 的修法。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

        env = dict(os.environ)
        env[env_var] = str(repo / ".git")
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(wt), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, (
            f"{env_var} 讓 worktree gate 失效（fail-open）：{result.stdout!r}"
        )
        assert "worktree" in result.stderr

    def test_anw_eg_004_old_git_without_path_format_still_blocks(self, tmp_path: Path) -> None:
        """ANW-EG-004: 不支援 --path-format 的舊 git 上，gate 仍須正確擋下 worktree。

        `--path-format` 是 git 2.31（2021）才加入。第一版實作用了它，而舊 git 的 fatal
        會被 fail-open 分支吃掉，讓 gate 靜默失效——三家 reviewer（Claude/codex/agy）
        R1 獨立收斂到這個 Critical。修法改用 cd+pwd 正規化，完全不依賴該 flag。

        **本測試證明的範圍（誠實標註）**：它只用 shim 拒絕 `--path-format`，其餘一律
        轉給宿主的現代 git。因此它證明的是「這一條 flag 相依性已被移除」，**不是**
        腳本 header 宣稱的 git 2.7 相容底線——要證明後者需要在 CI 跑真的 git 2.7
        binary，本 repo 目前沒有那個基礎設施（由 mob review 的 codex voice 指出）。
        不要把這條測試的綠燈讀成「2.7 相容性已驗證」。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

        shim = tmp_path / "shim"
        shim.mkdir()
        real_git = shutil.which("git")
        (shim / "git").write_text(
            "#!/bin/bash\n"
            'for a in "$@"; do\n'
            '  case "$a" in\n'
            "    --path-format*) echo \"fatal: unknown option '--path-format'\" >&2; exit 129 ;;\n"
            "  esac\n"
            "done\n"
            f'exec {real_git} "$@"\n',
            encoding="utf-8",
        )
        (shim / "git").chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env['PATH']}"
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(wt), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, (
            f"舊 git 讓 worktree gate 失效（fail-open）：{result.stdout!r} {result.stderr!r}"
        )
        assert "worktree" in result.stderr

    def test_anw_eg_008_worktree_list_failure_still_reports_loudly(self, tmp_path: Path) -> None:
        """ANW-EG-008: `git worktree list` 失敗時仍須印出 [FAIL]，且不得給出臆測的 cd 建議。

        本腳本是 set -e + pipefail。裸賦值 `X=$(cmd | awk)` 在 cmd 失敗時會讓腳本
        當場終止——此處已確定是 worktree，卻會在印出 [FAIL] 之前就死掉：exit 128、
        輸出全空。實測（修法前）：exit=128 且輸出完全空白。由 mob review 的 agy
        voice 指出。方向上是 fail-closed（install 仍被擋），但使用者拿不到任何說明，
        違反 CLAUDE.md「每個外部呼叫都要有可行動的 [FAIL]」。

        本測試同時補上 agy 指出的測試缺口：舊 shim 只擋 --path-format，把
        worktree list 放行給真 git，所以這個 bug 完全沒被測到。

        註：這裡走的是「路徑不相等」的一般 worktree 分支，worktree list 只用來美化
        訊息，故降級成「不給 cd 建議」即可。dirname fallback 已在 round 3 移除
        （它會在 --separate-git-dir 佈局下指向錯目錄），所以此處斷言的是**不得**
        出現 cd 建議——docstring 一度仍在描述那個已移除的 fallback，由 codex 指出。
        recovery 分支（.git 已刪的巢狀 worktree）則相反：那裡 worktree list 是唯一
        防線，失敗必須 fail-closed，見 ANW-EG-015。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

        shim = tmp_path / "shim"
        shim.mkdir()
        real_git = shutil.which("git")
        (shim / "git").write_text(
            "#!/bin/bash\n"
            'for a in "$@"; do\n'
            '  if [ "$a" = "worktree" ]; then\n'
            '    echo "fatal: simulated worktree list failure" >&2\n'
            "    exit 128\n"
            "  fi\n"
            "done\n"
            f'exec {real_git} "$@"\n',
            encoding="utf-8",
        )
        (shim / "git").chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env['PATH']}"
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(wt), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, (
            f"worktree list 失敗讓腳本靜默終止（exit={result.returncode}）"
        )
        # 關鍵：訊息必須存在，不能是空白的靜默死亡
        assert "[FAIL]" in result.stderr
        assert "worktree" in result.stderr
        # 問不出主 repo 時**不得**印出 cd 建議：dirname 猜測在 --separate-git-dir
        # 等佈局下會指到不存在或無關的目錄，而誤導的訊息比簡短的更糟（rule 11）。
        # 由 mob review 的 codex voice 以本 PR 自己寫下的原則反過來檢驗而發現。
        assert "無法從 git 問出主 repo 路徑" in result.stderr
        assert "cd " not in result.stderr

    def test_anw_dt_007_pruned_worktree_is_still_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-007: admin dir 被 prune 的殘留 worktree 仍須擋下。

        git 對「真的不是 repo」與「worktree 的 admin dir 不見了」回報**同一句話**
        （`fatal: not a git repository: (null)`），所以單靠訊息比對放行會擊穿 gate。

        實測（修法前 exit 0，由 mob review 的 silent-failure-hunter 指出並複現）：
        `rm -rf <main>/.git/worktrees/<name>` 後，worktree 目錄的 .git 檔案還在，
        明確是 worktree，卻被放行——而且它正是「陳舊且注定消失」的目錄，即本 gate
        存在的理由本身。

        區分依據：合法的 fail-open（解壓 zip）根本沒有 .git。
        本測試經突變驗證：拿掉 `[ ! -e "$DIR/.git" ]` 條件會讓它失敗。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        shutil.rmtree(repo / ".git" / "worktrees" / "wt")

        # 前提確認：.git 檔案仍在，git 仍回報 not a git repository
        assert (wt / ".git").exists(), "測試前提不成立：.git 應仍存在"

        result = _run(["bash", str(GUARD), str(wt), "install"])
        assert result.returncode == 1, (
            f"被 prune 的殘留 worktree 遭放行（fail-open）：{result.stderr!r}"
        )
        assert "[FAIL]" in result.stderr

    def test_anw_dt_008_worktree_of_moved_main_is_still_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-008: 主 repo 被搬走後的殘留 worktree 仍須擋下。

        與 ANW-DT-007 同一 root cause，但成因是日常操作（主 repo 被搬移或重新
        clone），不是刻意破壞。git 同樣回報 `not a git repository: (null)`。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        repo.rename(tmp_path / "repo_moved")

        assert (wt / ".git").exists(), "測試前提不成立：.git 應仍存在"

        result = _run(["bash", str(GUARD), str(wt), "install"])
        assert result.returncode == 1, (
            f"主 repo 搬走後的殘留 worktree 遭放行（fail-open）：{result.stderr!r}"
        )
        assert "[FAIL]" in result.stderr

    def test_anw_st_005_separate_git_dir_main_repo_passes(self, tmp_path: Path) -> None:
        """ANW-ST-005: --separate-git-dir 的主 repo 必須放行。

        該情境下 .git 是「檔案」而非目錄。這是 `[ ! -e "$DIR/.git" ]` 區分依據的
        風險面：若判斷寫錯，合法的主 repo 會因為「有 .git」被誤擋。實際上 git
        能正常解析它，根本走不到 fail-open 分支。
        """
        sep = tmp_path / "sep"
        sep_git = tmp_path / "sepgit"
        sep.mkdir()
        _init_repo_portable(sep, f"--separate-git-dir={sep_git}")
        _git(sep, "config", "user.email", "t@e.com")
        _git(sep, "config", "user.name", "t")
        (sep / "README.md").write_text("x\n", encoding="utf-8")
        _git(sep, "add", "README.md")
        _git(sep, "commit", "-qm", "init")

        assert (sep / ".git").is_file(), "測試前提不成立：.git 應為檔案"
        result = _run(["bash", str(GUARD), str(sep), "install"])
        assert result.returncode == 0, f"separate-git-dir 主 repo 被誤擋：{result.stderr!r}"

    def test_anw_dt_010_worktree_of_separate_git_dir_main_is_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-010: --separate-git-dir 主 repo 的 worktree 仍須擋下。"""
        sep = tmp_path / "sep"
        sep_git = tmp_path / "sepgit"
        sep.mkdir()
        _init_repo_portable(sep, f"--separate-git-dir={sep_git}")
        _git(sep, "config", "user.email", "t@e.com")
        _git(sep, "config", "user.name", "t")
        (sep / "README.md").write_text("x\n", encoding="utf-8")
        _git(sep, "add", "README.md")
        _git(sep, "commit", "-qm", "init")

        wt = tmp_path / "wt"
        added = _git(sep, "worktree", "add", "-q", "-b", "feat", str(wt))
        assert added.returncode == 0, added.stderr

        result = _run(["bash", str(GUARD), str(wt), "install"])
        assert result.returncode == 1, "separate-git-dir 主 repo 的 worktree 未被擋下"
        assert "worktree" in result.stderr

    def test_anw_dt_012_pruned_worktree_subdir_is_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-012: 被 prune 的 worktree 的「子目錄」也須擋下。

        .git 在 worktree 根而不在子目錄，所以只看 $DIR/.git 會漏。實測（修法前，
        由 mob review 的 codex voice 指出）：prune 後 gate 對根回 exit 1（正確），
        對子目錄回 exit 0（放行）。修法：fail-open 前往上走訪祖先找 .git。

        本測試經突變驗證：把祖先走訪改回只看 $DIR/.git 會讓它失敗。
        """
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        sub = wt / "sub"
        sub.mkdir()
        shutil.rmtree(repo / ".git" / "worktrees" / "wt")

        # 前提：.git 在根不在子目錄
        assert (wt / ".git").exists(), "測試前提不成立：worktree 根應有 .git"
        assert not (sub / ".git").exists(), "測試前提不成立：子目錄不應有 .git"

        result = _run(["bash", str(GUARD), str(sub), "install"])
        assert result.returncode == 1, (
            f"壞掉 worktree 的子目錄遭放行（fail-open）：{result.stderr!r}"
        )
        assert "[FAIL]" in result.stderr

    def test_anw_eg_012_relative_dir_does_not_hang_the_ancestor_walk(self, tmp_path: Path) -> None:
        """ANW-EG-012: 相對路徑的 $DIR 不得讓祖先走訪無限迴圈。

        `dirname .` 回傳 `.`，所以祖先走訪的 `[ "$d" = "/" ]` 終止條件永遠不成立
        -> 迴圈掛死，make 整個卡住且無任何輸出。這比 fail-open 更難診斷：使用者
        連錯誤訊息都沒有，只看到指令不會結束。

        實測（修法前）：在非 git 目錄下 `assert_not_worktree.sh . install` timeout。
        修法：一開始就把 $DIR 正規化成絕對實體路徑。

        本測試用 timeout 而非只看 returncode：掛住的話 subprocess.run 會丟
        TimeoutExpired，正是我們要抓的。
        """
        plain = tmp_path / "plain" / "nested"
        plain.mkdir(parents=True)

        # cwd 設在該目錄，傳入相對路徑 "."
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), ".", "install"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            cwd=str(plain),
        )
        assert result.returncode == 0, f"相對路徑下非 git 目錄未被放行：{result.stderr!r}"

    def test_anw_dt_013_relative_dir_still_blocks_a_worktree(self, tmp_path: Path) -> None:
        """ANW-DT-013: 相對路徑的 $DIR 仍須正確擋下 worktree（正規化不得改變判定）。"""
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), ".", "install"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            cwd=str(wt),
        )
        assert result.returncode == 1, "相對路徑下 worktree 未被擋下"
        assert "worktree" in result.stderr
        # 正規化後訊息仍須印出絕對路徑，不是 "."
        assert str(wt.resolve()) in result.stderr

    def test_anw_dt_014_registered_worktree_with_deleted_git_is_blocked(
        self, tmp_path: Path
    ) -> None:
        """ANW-DT-014: 仍登記、但 .git 已遺失的 worktree（位於主 repo 樹內）須擋下。

        該 worktree 的 .git 被刪除後，git 會往上解析到主 repo，--git-dir 與
        --git-common-dir 相等 -> 走正常放行路徑。但實測它**仍登記在主 repo**
        （git worktree list 標記為 prunable），所以不能推論「它已只是一般目錄」。
        由 mob review 的 codex voice 指出。

        誠實標註危害範圍：實測本 repo 目前沒有工具會刪除該目錄——
        `git worktree prune` 只移除 admin entry，/clean-merged 與 /clean-gone 也沒有
        刪 worktree 目錄的邏輯，故危害鏈未閉合。採用此修法不是因為危害已證實，
        而是因為直接問 git 比用文字論證它安全更可靠。

        本測試經突變驗證：拿掉 worktree list 比對會讓它失敗。
        """
        repo = _make_repo(tmp_path / "repo")
        nested = repo / ".claude" / "worktrees" / "wt1"
        nested.parent.mkdir(parents=True)
        _git(repo, "worktree", "add", "-q", "-b", "feat1", str(nested))
        (nested / ".git").unlink()

        # 前提：git 從該目錄往上解析到主 repo（即相等性檢查會放行）
        toplevel = _run(["git", "-C", str(nested), "rev-parse", "--show-toplevel"])
        assert toplevel.stdout.strip() == str(repo.resolve()), "測試前提不成立：git 應解析到主 repo"
        # 前提：它仍登記為 worktree
        listing = _git(repo, "worktree", "list", "--porcelain")
        assert str(nested.resolve()) in listing.stdout, "測試前提不成立：應仍登記"

        result = _run(["bash", str(GUARD), str(nested), "install"])
        assert result.returncode == 1, f"仍登記的 worktree（.git 已刪）遭放行：{result.stderr!r}"
        assert "worktree" in result.stderr

    def _make_registered_broken_nested(self, tmp_path: Path) -> tuple[Path, Path]:
        """建一個「仍登記但 .git 已刪」的巢狀 worktree，回傳 (主 repo, worktree 根)。"""
        repo = _make_repo(tmp_path / "repo")
        nested = repo / ".claude" / "worktrees" / "wt1"
        nested.parent.mkdir(parents=True)
        _git(repo, "worktree", "add", "-q", "-b", "feat1", str(nested))
        (nested / ".git").unlink()
        return repo, nested

    def test_anw_dt_015_registered_broken_worktree_subdir_is_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-015: 仍登記、.git 已刪的 worktree 的「子目錄」也須擋下。

        登記檢查原本只比對 $DIR 與 worktree 根「完全相等」，子目錄因此不匹配而放行。
        codex 與 agy 在 R6 各自獨立指出，且 agy 點名這是**本 PR 在 round 4 已經修好
        的同一個 class**（_find_broken_git_ancestor 當初也只看 $DIR 自己），卻在
        round 5 的新程式碼裡重新引入。

        修法：用 containment（case "$DIR" in "$wt_abs" | "$wt_abs"/*）而非 equality。
        本測試經突變驗證：改回只比對相等會讓它失敗。
        """
        _repo, nested = self._make_registered_broken_nested(tmp_path)
        sub = nested / "sub"
        sub.mkdir()

        result = _run(["bash", str(GUARD), str(sub), "install"])
        assert result.returncode == 1, (
            f"仍登記 worktree 的子目錄遭放行（fail-open）：{result.stderr!r}"
        )
        assert "worktree" in result.stderr
        # 訊息要指出 worktree 根，使用者才知道問題出在哪一層
        assert str(nested.resolve()) in result.stderr

    def test_anw_eg_015_worktree_list_failure_on_recovery_path_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """ANW-EG-015: 登記檢查查詢失敗時必須 fail-closed，不可跳過整段檢查。

        `if REGISTERED=$(git worktree list ...); then ... fi` 在查詢失敗時會整段跳過
        而落到 exit 0。對「.git 已刪的巢狀 worktree」而言，這個查詢是**唯一剩下的
        防線**——跳過它等於完全沒防護（由 mob review 的 codex voice 指出）。

        注意這與 ANW-EG-008 不同：那條走的是「路徑不相等」的一般 worktree 分支，
        worktree list 只用來美化訊息；這條走的是 recovery 分支，它是防線本身。
        """
        _repo, nested = self._make_registered_broken_nested(tmp_path)

        shim = tmp_path / "shim"
        shim.mkdir()
        real_git = shutil.which("git")
        (shim / "git").write_text(
            "#!/bin/bash\n"
            'for a in "$@"; do\n'
            '  if [ "$a" = "worktree" ]; then\n'
            '    echo "fatal: simulated worktree list failure" >&2\n'
            "    exit 128\n"
            "  fi\n"
            "done\n"
            f'exec {real_git} "$@"\n',
            encoding="utf-8",
        )
        (shim / "git").chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env['PATH']}"
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(nested), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, (
            f"worktree list 失敗讓唯一防線被跳過（fail-open）：{result.stdout!r}"
        )
        assert "[FAIL]" in result.stderr

    def test_anw_eg_014_cdpath_cannot_redirect_relative_dir(self, tmp_path: Path) -> None:
        """ANW-EG-014: CDPATH 不得讓相對路徑的 $DIR 被導向別的目錄。

        `export CDPATH=` 原本排在正規化 cd 的**下面**，等於沒保護到它。POSIX：cd 的
        運算元不以 /、. 或 .. 開頭時會搜尋 CDPATH，命中還會把目的地印到 stdout。
        於是 DIR='wt' 會被導去 <trap>/wt，且 $() 取回兩行垃圾。

        實測（由 mob review 的 silent-failure-hunter 指出）：碰巧 fail-closed，
        但那是意外而非設計，且 [FAIL] 會指名錯的目錄。

        本測試經突變驗證：把 `export CDPATH=` 移回正規化之後會讓它失敗。
        """
        repo = _make_repo(tmp_path / "repo")
        wt_name = "wt"
        wt = tmp_path / "base" / wt_name
        wt.parent.mkdir()
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

        # CDPATH trap：一個同名但完全無關的目錄
        trap_dir = tmp_path / "trap"
        (trap_dir / wt_name).mkdir(parents=True)

        env = dict(os.environ)
        env["CDPATH"] = str(trap_dir)
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), wt_name, "install"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            cwd=str(wt.parent),
            env=env,
        )
        assert result.returncode == 1, "CDPATH 下 worktree 未被擋下"
        # 關鍵：訊息必須指名真正的 worktree，不是 trap 目錄
        assert str(trap_dir) not in result.stderr, (
            f"[FAIL] 訊息指向 CDPATH trap 目錄而非真實路徑：{result.stderr!r}"
        )
        assert str(wt.resolve()) in result.stderr

    def test_anw_eg_013_ancestor_walk_helper_never_calls_exit(self) -> None:
        """ANW-EG-013: _find_broken_git_ancestor 不得用 exit 表達失敗。

        它被 `$(...)` 呼叫，那是 subshell——exit 只結束 subshell，腳本會繼續跑，
        於是「無法判定」被誤當成「沒找到 .git」而走進 fail-open。

        實測（修法前）：深度上限確實印出了 [FAIL]，腳本卻仍 exit 0。這個假象還
        連帶讓 ANW-EG-012 變成假測試（斷言的 0 剛好等於 bug 造成的 0）——是本 PR
        自己的突變測試把兩者一起揪出來的。

        改用 return code（0=找到 / 1=沒找到 / 2=超過上限），呼叫端逐一分辨。
        這是靜態檢查：它防的是「後人把 return 2 改回 exit 1」這種看起來更直覺、
        實際會靜默 fail-open 的回頭路。
        """
        src = GUARD.read_text(encoding="utf-8")
        start = src.index("_find_broken_git_ancestor() {")
        end = src.index("\n}", start)
        body = src[start:end]

        assert "exit " not in body, (
            "_find_broken_git_ancestor 內含 exit：它在 $() subshell 裡執行，"
            "exit 不會終止腳本，會靜默 fail-open。請用 return code。"
        )
        # 三種 return code 都必須存在
        for rc in ("return 0", "return 1", "return 2"):
            assert rc in body, f"缺少 {rc}"

    def test_anw_eg_011_healthy_repo_is_not_accused_of_being_broken(self, tmp_path: Path) -> None:
        """ANW-EG-011: 非 not-a-repo 的 git 失敗不得印出「這個 repo 壞了」的臆測。

        提示訊息原本只 gate 在「有沒有 .git」，於是任何其他 git 失敗（dubious
        ownership、git 不在 PATH）發生在有 .git 的目錄時都會照印。實測（由 mob
        review 的 silent-failure-hunter 指出）：在一個**健康的主 repo** 上用 shim
        模擬 dubious ownership，訊息宣稱 admin dir 被 prune / 主 repo 被搬移
        ——全部是假的，把使用者送去查錯方向。

        擋下是對的（fail-closed），但不得猜原因。
        """
        repo = _make_repo(tmp_path / "repo")

        shim = tmp_path / "shim"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/bin/bash\n"
            "echo \"fatal: detected dubious ownership in repository at '/x'\" >&2\n"
            "exit 128\n",
            encoding="utf-8",
        )
        (shim / "git").chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env['PATH']}"
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(repo), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, "非 not-a-repo 的 git 失敗未擋下"
        # git 的原始訊息要透出來
        assert "dubious ownership" in result.stderr
        # 但不得臆測成因
        assert "prune" not in result.stderr
        assert "repo 壞了" not in result.stderr

    def test_anw_eg_009_cdpath_cannot_pollute_path_normalization(self, tmp_path: Path) -> None:
        """ANW-EG-009: CDPATH 不得污染路徑正規化。

        POSIX：cd 的目標若首段不是 . 或 ..（git 會回傳 ".git"），就會搜尋 CDPATH，
        命中時還會把目的地印到 stdout，污染 $() 取值。實測（由 mob review 的
        silent-failure-hunter 指出）：CDPATH 指向含 .git 的目錄時，
        `cd .git && pwd -P` 回傳兩行。腳本以 `export CDPATH=` 消除此相依。
        """
        repo = _make_repo(tmp_path / "repo")
        trap_dir = tmp_path / "cdpath_trap"
        (trap_dir / ".git").mkdir(parents=True)

        env = dict(os.environ)
        env["CDPATH"] = str(trap_dir)
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(repo), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 0, f"CDPATH 污染了正規化，主 repo 被誤擋：{result.stderr!r}"
        assert result.stdout == ""

    def test_anw_eg_005_non_repo_git_error_fails_loud(self, tmp_path: Path) -> None:
        """ANW-EG-005: git 因「非 not-a-repo」的原因失敗時，必須 fail loud 而非放行。

        fail-open 只允許「git 明說這不是 git repo」一種情況。舊版寫法把所有 git 失敗
        都當成非 git repo，於是 dubious ownership（sudo make install / repo 屬於他人）、
        權限不足、git 不在 PATH 全部被靜默放行。
        """
        shim = tmp_path / "shim"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/bin/bash\n"
            'echo "fatal: detected dubious ownership in repository at /x" >&2\n'
            "exit 128\n",
            encoding="utf-8",
        )
        (shim / "git").chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env['PATH']}"
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(tmp_path), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, "非 not-a-repo 的 git 失敗被靜默放行"
        assert "[FAIL]" in result.stderr
        # git 的原始訊息必須透出來，否則使用者無從診斷
        assert "dubious ownership" in result.stderr

    def test_anw_eg_006_localised_git_still_detects_non_repo(self, tmp_path: Path) -> None:
        """ANW-EG-006: 非英文語系下仍須正確識別 not-a-repo（LC_ALL=C 鎖定訊息語言）。

        fail-open 靠比對 git 的 "not a git repository" 訊息。git 會依語系翻譯該訊息，
        若不鎖 LC_ALL=C，中文環境下比對落空 -> 合法的非 git 安裝會被誤擋。
        """
        shim = tmp_path / "shim"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/bin/bash\n"
            'if [ "${LC_ALL:-}" = "C" ]; then\n'
            '  echo "fatal: not a git repository (or any of the parent directories): .git" >&2\n'
            "else\n"
            '  echo "fatal: 不是 git 版本庫" >&2\n'
            "fi\n"
            "exit 128\n",
            encoding="utf-8",
        )
        (shim / "git").chmod(0o755)

        plain = tmp_path / "plain"
        plain.mkdir()
        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env['PATH']}"
        env["LC_ALL"] = "zh_TW.UTF-8"
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(plain), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 0, f"中文語系下誤擋合法的非 git 安裝：{result.stderr!r}"

    def test_anw_st_003_main_repo_subdir_passes(self, tmp_path: Path) -> None:
        """ANW-ST-003: 從主 repo 的「子目錄」呼叫必須放行。

        這條釘住的是 mob review 中被實測反駁的一個提案（直接比對 raw rev-parse 輸出、
        不做正規化）。實測：主 repo 子目錄下 --git-dir 回絕對路徑、--git-common-dir
        回 "../.git"，兩者不等 -> 那個提案會誤擋主 repo 的安裝。提案者已撤回。
        """
        repo = _make_repo(tmp_path / "repo")
        subdir = repo / "scripts"
        subdir.mkdir()

        result = _run(["bash", str(GUARD), str(subdir), "install"])
        assert result.returncode == 0, f"主 repo 子目錄被誤擋：{result.stderr!r}"
        assert result.stderr == ""

    def test_anw_st_004_symlinked_main_repo_subdir_passes(self, tmp_path: Path) -> None:
        """ANW-ST-004: 經 symlink 路徑進入主 repo 子目錄時必須放行（需 pwd -P）。

        由 mob review 的 codex voice 指出、經實測確認：git 對兩個 flag 回傳的路徑
        分屬不同命名空間。symlink 化的 main repo 子目錄下：
          rev-parse --git-dir        -> /private/var/.../real/.git （實體絕對路徑）
          rev-parse --git-common-dir -> ../.git                    （相對）
        相對路徑經「邏輯」pwd 正規化得到 /var/.../link/.git，與前者不等 -> 誤擋主 repo。
        pwd -P 把兩者解析到實體路徑才可比。macOS 的 /var -> /private/var 即為此類
        symlink，故非理論風險。

        本測試經突變驗證：把 _abs_git_path 的 `pwd -P` 改回 `pwd` 會讓它失敗。
        """
        repo = _make_repo(tmp_path / "real")
        (repo / "scripts").mkdir()
        link = tmp_path / "link"
        link.symlink_to(repo)

        result = _run(["bash", str(GUARD), str(link / "scripts"), "install"])
        assert result.returncode == 0, f"symlink 路徑下的主 repo 子目錄被誤擋：{result.stderr!r}"
        assert result.stderr == ""

    def test_anw_dt_006_worktree_under_symlinked_main_still_blocked(self, tmp_path: Path) -> None:
        """ANW-DT-006: 主 repo 經 symlink 存取時，worktree 仍須被擋下。

        pwd -P 的另一面：正規化不可過度到把 worktree 也解析成與 main 相同而漏擋。
        """
        repo = _make_repo(tmp_path / "real")
        link = tmp_path / "link"
        link.symlink_to(repo)
        wt = tmp_path / "wt"
        added = _run(["git", "-C", str(link), "worktree", "add", "-q", "-b", "feat", str(wt)])
        assert added.returncode == 0, added.stderr

        result = _run(["bash", str(GUARD), str(wt), "install"])
        assert result.returncode == 1, "symlink 化 main 底下的 worktree 未被擋下"
        assert "worktree" in result.stderr

    def test_anw_eg_007_empty_git_output_fails_loud(self, tmp_path: Path) -> None:
        """ANW-EG-007: git 回傳空字串時必須 fail loud，不可讓 "" = "" 相等而放行。"""
        shim = tmp_path / "shim"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/bin/bash\n"
            'for a in "$@"; do\n'
            '  if [ "$a" = "--git-dir" ] || [ "$a" = "--git-common-dir" ]; then\n'
            '    echo ""\n'
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "exit 0\n",
            encoding="utf-8",
        )
        (shim / "git").chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env['PATH']}"
        result = subprocess.run(  # nosec B603
            ["bash", str(GUARD), str(tmp_path), "install"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        assert result.returncode == 1, "git 回傳空路徑時被放行"
        assert "[FAIL]" in result.stderr

    def test_anw_vl_002_missing_dir_fails_loud(self, tmp_path: Path) -> None:
        """ANW-VL-002: $DIR 不存在必須 fail loud（舊版是靜默 exit 0）。"""
        result = _run(["bash", str(GUARD), str(tmp_path / "nope"), "install"])
        assert result.returncode == 1
        assert "[FAIL]" in result.stderr
        assert result.stdout == ""

    @pytest.mark.parametrize("args", [[], ["only-one-arg"]])
    def test_anw_vl_001_missing_args_fail(self, args: list[str]) -> None:
        """ANW-VL-001: 參數不足必須 exit 1 並說明用法，不可預設放行。"""
        result = _run(["bash", str(GUARD), *args])
        assert result.returncode == 1
        assert "[FAIL]" in result.stderr
        assert result.stdout == ""


class TestMakefileWiring:
    """防護必須實際接在 target 上，且是第一個動作。

    腳本正確但沒接上 Makefile 等於沒修 —— 這類「寫了但沒生效」正是 issue #232
    主體的成因（register_skill_repo.py 早就寫好，只是那台機器沒跑過）。
    """

    # promote：會 mv 檔案後委派 install-one，guard 必須在 mv 之前。
    # install-scheduler / install-handover-hooks：走 Python 而非 symlink，但同樣把
    # 自我定位的 repo 路徑寫進全域狀態（LaunchAgent plist / settings.json hook）。
    # 不能只靠 install-all 串接 install 來擋——make -j 會平行跑 prerequisites。
    GUARDED_TARGETS = [
        "install",
        "install-project",
        "install-one",
        "install-force-one",
        "promote",
        "install-scheduler",
        "install-handover-hooks",
    ]

    @staticmethod
    def _recipe_lines(target: str) -> list[str]:
        """取出單一 target 的 recipe 行——**不排除任何行**，含 @# 註解行。

        刻意不跳過 @# 註解：rule 11 要求「guard 是 recipe 的第一行」是**字面的**
        不變量，跳過註解等於把它偷偷降級成較弱的「第一個可執行動作」，測試於是
        掩蓋了違規（由 mob review 的 codex voice 指出——當時四個 target 的 guard
        前面都擺了 @# 說明行，測試卻全綠）。說明文字現已移到 target 宣告之上，
        因此字面規則可以成立而不需任何但書。

        必須在 recipe 區塊結尾停止：Make 的 recipe 以「第一個非 tab 開頭的非空行」
        作結。掃到檔尾的話，若某 target 的 recipe 被整個刪除，就會撿到下一個 target
        的第一行——而下一個 target 的第一行剛好也是 guard，於是測試在「guard 被移除」
        這個它唯一該抓到的情境下給出假綠燈。
        """
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        lines = makefile.splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith(f"{target}:")), None)
        assert start is not None, f"Makefile 找不到 target：{target}"

        recipe: list[str] = []
        for line in lines[start + 1 :]:
            if not line.strip():
                continue
            if not line.startswith("\t"):
                break  # recipe 區塊結束
            recipe.append(line.strip())
        return recipe

    @pytest.mark.parametrize("target", GUARDED_TARGETS)
    def test_anw_dt_002_guard_is_wired_into_target(self, target: str) -> None:
        """ANW-DT-002: 每個會寫全域狀態的 target 都必須呼叫 guard。"""
        recipe = self._recipe_lines(target)
        assert any("assert_not_worktree.sh" in line for line in recipe), (
            f"{target} 未接上 assert_not_worktree.sh"
        )

    @pytest.mark.parametrize("target", GUARDED_TARGETS)
    def test_anw_dt_003_guard_is_first_recipe_line(self, target: str) -> None:
        """ANW-DT-003: guard 必須是 recipe 的第一個執行動作。

        install 會先建 skill symlink 才處理 resolver；promote 會先 mv 檔案。
        guard 放太後面的話，失敗時全域目錄或工作區已經被改過了。
        """
        recipe = self._recipe_lines(target)
        assert recipe, f"{target} 沒有 recipe"
        assert "assert_not_worktree.sh" in recipe[0], (
            f"{target} 的第一個動作不是 guard，而是：{recipe[0]}"
        )

    @pytest.mark.parametrize("target", GUARDED_TARGETS)
    def test_anw_dt_004_guard_path_is_quoted(self, target: str) -> None:
        """ANW-DT-004: guard 的執行路徑必須加引號。

        `@$(CURDIR)/scripts/...` 未加引號時，checkout 路徑含空格會被 make 斷詞成
        多個 shell word -> "command not found"。codex 與 agy 在 R1 獨立指出同一點。
        """
        recipe = self._recipe_lines(target)
        guard_line = next(line for line in recipe if "assert_not_worktree.sh" in line)
        assert '"$(CURDIR)/scripts/assert_not_worktree.sh"' in guard_line, (
            f"{target} 的 guard 路徑未加引號：{guard_line}"
        )

    def test_anw_dt_009_install_all_prereqs_are_each_guarded(self) -> None:
        """ANW-DT-009: install-all 的每個會寫全域狀態的 prerequisite 都要自己有 guard。

        不可依賴「install 排在前面會先中止」——GNU make 的 -j 會**平行**跑
        prerequisites，install-scheduler 可能在 install 的 guard 失敗前就寫完
        LaunchAgent plist。此點由 mob review 的 codex voice 指出，並同時證偽了
        CLAUDE.md 原本「install-all 因串接 install 而安全」的宣稱。
        """
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        line = next(ln for ln in makefile.splitlines() if ln.startswith("install-all:"))
        prereqs = line.split(":", 1)[1].split("##")[0].split()

        # 這些 prerequisite 會寫全域狀態，每個都必須自帶 guard
        global_state_prereqs = {
            "install",
            "install-project",
            "install-scheduler",
            "install-handover-hooks",
        }
        for p in prereqs:
            if p in global_state_prereqs:
                assert p in self.GUARDED_TARGETS, (
                    f"install-all 的 prerequisite {p} 會寫全域狀態卻未列入 guard 清單"
                )

    @pytest.mark.parametrize("target", ["install-one", "install-force-one", "promote"])
    def test_anw_dt_005_skill_targets_pass_skill_arg_in_message(self, target: str) -> None:
        """ANW-DT-005: 需要 SKILL= 的 target 必須把該引數帶進 guard 的建議指令。

        否則 [FAIL] 訊息會叫使用者跑 `make install-one`，照抄立刻失敗於缺少 SKILL。

        issue #237 起腳本改收「完整指令」而非 target 名（它多了非 make 的呼叫者），
        故這裡連 `make ` 前綴一起斷言——建議指令要能整行照抄。
        """
        recipe = self._recipe_lines(target)
        guard_line = next(line for line in recipe if "assert_not_worktree.sh" in line)
        assert f'"make {target} SKILL=$(SKILL)"' in guard_line, (
            f"{target} 未把 SKILL= 帶進 guard 訊息：{guard_line}"
        )

    @pytest.mark.parametrize("target", GUARDED_TARGETS)
    def test_anw_dt_006_guard_command_arg_is_copy_pasteable(self, target: str) -> None:
        """ANW-DT-006: 每個 target 傳給 guard 的第二個引數必須是可照抄的完整指令。

        issue #237：腳本原本硬編 `make ${TARGET}` 前綴，只收 target 名。加入 Python
        呼叫端後那個前綴會讓 `uv run python -m ...` 的呼叫者印出一條照抄必失敗的假
        指令，故前綴移到呼叫端。這個測試釘住新契約——若有人把 `make ` 漏掉，[FAIL]
        訊息會變成「不可執行 install-scheduler」並建議 `cd <main> && install-scheduler`，
        照抄即 command not found。
        """
        recipe = self._recipe_lines(target)
        guard_line = next(line for line in recipe if "assert_not_worktree.sh" in line)
        assert '"make ' in guard_line, (
            f"{target} 傳給 guard 的指令未含 `make ` 前綴，[FAIL] 訊息會給出無法照抄的"
            f"指令：{guard_line}"
        )

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


def _make_repo(root: Path) -> Path:
    """建立一個有 initial commit 的 git repo（git worktree add 需要至少一個 commit）。"""
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main", str(root)])
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
        R1 獨立收斂到這個 Critical。

        本測試用一個「拒絕 --path-format」的 git shim 模擬舊 git。修法改用 cd+pwd
        正規化，完全不依賴該 flag，所以舊 git 上 gate 正常運作（而非被擋死）。
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

    # promote 也在列：它會 mv 檔案後委派 install-one，guard 必須在 mv 之前。
    GUARDED_TARGETS = [
        "install",
        "install-project",
        "install-one",
        "install-force-one",
        "promote",
    ]

    @staticmethod
    def _recipe_lines(target: str) -> list[str]:
        """取出單一 target 的 recipe 執行行（不含純註解行）。

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
            if line.strip().startswith("@#"):
                continue  # 純註解行
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

    @pytest.mark.parametrize("target", ["install-one", "install-force-one", "promote"])
    def test_anw_dt_005_skill_targets_pass_skill_arg_in_message(self, target: str) -> None:
        """ANW-DT-005: 需要 SKILL= 的 target 必須把該引數帶進 guard 的建議指令。

        否則 [FAIL] 訊息會叫使用者跑 `make install-one`，照抄立刻失敗於缺少 SKILL。
        """
        recipe = self._recipe_lines(target)
        guard_line = next(line for line in recipe if "assert_not_worktree.sh" in line)
        assert f'"{target} SKILL=$(SKILL)"' in guard_line, (
            f"{target} 未把 SKILL= 帶進 guard 訊息：{guard_line}"
        )

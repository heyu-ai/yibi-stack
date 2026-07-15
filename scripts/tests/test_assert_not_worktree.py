"""assert_not_worktree.sh 的行為測試。

這支腳本擋的是一個「安靜壞掉」的失敗鏈（issue #232 附帶發現）：
在 worktree 裡跑 make install -> 全域 symlink 指向 worktree ->
分支合併後 worktree 被刪 -> 所有 skill 失效。

Makefile 既有的安裝後 gate 在結構上擋不住這個 case：它比對
`resolve-skill-repo 輸出 == $(CURDIR)`，而 worktree 裡兩者本來就相等。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
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

    @pytest.mark.parametrize(
        "target",
        ["install", "install-project", "install-one", "install-force-one"],
    )
    def test_anw_dt_002_guard_is_wired_into_target(self, target: str) -> None:
        """ANW-DT-002: 四個會寫全域 symlink 的 target 都必須呼叫 guard。"""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        expected = f'assert_not_worktree.sh "$(CURDIR)" {target}\n'
        assert expected in makefile, f"{target} 未接上 assert_not_worktree.sh"

    @pytest.mark.parametrize(
        "target",
        ["install", "install-project", "install-one", "install-force-one"],
    )
    def test_anw_dt_003_guard_is_first_recipe_line(self, target: str) -> None:
        """ANW-DT-003: guard 必須是 recipe 的第一個執行動作。

        install 會先建 skill symlink 才處理 resolver；guard 放太後面的話，
        失敗時 ~/.claude/skills/ 與 ~/.agents/ 已經被寫入 worktree 路徑了。
        """
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        lines = makefile.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
        # 跳過純註解行（@# 開頭），找第一個真正執行的指令
        recipe = [
            line.strip()
            for line in lines[start + 1 :]
            if line.startswith("\t") and not line.strip().startswith("@#")
        ]
        assert recipe, f"{target} 沒有 recipe"
        assert "assert_not_worktree.sh" in recipe[0], (
            f"{target} 的第一個動作不是 guard，而是：{recipe[0]}"
        )

"""check_always_loaded_growth.py 的行為測試（合成 git repo fixture）。

`has_paths_key()` / `_parse_base_arg()` 為純函式，直接對合成文字斷言。`net_growth()`
及其輔助函式呼叫 git subprocess，用暫存 git repo + monkeypatch `REPO_ROOT`/`RULES_DIR`
測試 base..working 的淨增計算——特別是 untracked 新檔、刪除、rescope 三種成員資格
變化（PR #339 mob review 找出的計算缺口：過去只算「目前仍是 always-loaded 的檔案」
交集內的逐行 diff，會漏掉這三種情境）。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_always_loaded_growth as calg  # noqa: E402


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=False
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(root), *args])


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", str(root)])
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")


def _write_rule(root: Path, name: str, content: str) -> Path:
    rules_dir = root / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    p = rules_dir / name
    p.write_text(content, encoding="utf-8")
    return p


# --- has_paths_key: 純函式 ---


class TestHasPathsKey:
    def test_no_frontmatter_returns_false(self) -> None:
        assert calg.has_paths_key("# no frontmatter\ncontent\n") is False

    def test_paths_key_present_returns_true(self) -> None:
        assert calg.has_paths_key('---\npaths: ["tasks/**"]\n---\ncontent\n') is True

    def test_paths_key_absent_returns_false(self) -> None:
        assert calg.has_paths_key("---\nname: foo\n---\ncontent\n") is False

    def test_indented_paths_is_not_top_level(self) -> None:
        text = "---\nmetadata:\n  paths: foo\n---\ncontent\n"
        assert calg.has_paths_key(text) is False

    def test_missing_closing_delimiter_returns_false(self) -> None:
        text = "---\npaths: foo\ncontent without closing delimiter\n"
        assert calg.has_paths_key(text) is False

    def test_mutation_group1_equality_survives_check(self) -> None:
        """鎖住 PR #339 mob review 指出的存活 mutation：
        `match.group(1) == "paths"` 若改成 `!= "paths"`，任何非 paths 的 top-level
        key（如 name:）都會被誤判成 paths:-scoped，導致該檔從 always-loaded 清單消失。
        """
        assert calg.has_paths_key("---\nname: foo\n---\ncontent\n") is False
        assert calg.has_paths_key("---\npaths: foo\n---\ncontent\n") is True

    def test_globs_key_is_not_paths_key(self) -> None:
        # 拼法錯誤（globs: 而非 paths:）不應被誤判為有 paths: key（見 PR #250 已知陷阱）
        assert calg.has_paths_key("---\nglobs: foo\n---\ncontent\n") is False


# --- _parse_base_arg: 純函式 ---


class TestParseBaseArg:
    def test_no_base_returns_none(self) -> None:
        assert calg._parse_base_arg([]) is None

    def test_space_separated_form(self) -> None:
        assert calg._parse_base_arg(["--base", "origin/main"]) == "origin/main"

    def test_equals_form(self) -> None:
        """回歸：`--base=<ref>` 過去完全不被任何比對式匹配，靜默落回 baseline 模式。"""
        assert calg._parse_base_arg(["--base=origin/main"]) == "origin/main"

    def test_equals_form_empty_value_raises(self) -> None:
        with pytest.raises(ValueError):
            calg._parse_base_arg(["--base="])

    def test_space_form_missing_value_raises(self) -> None:
        with pytest.raises(ValueError):
            calg._parse_base_arg(["--base"])

    def test_unknown_arg_raises(self) -> None:
        with pytest.raises(ValueError):
            calg._parse_base_arg(["--bogus", "x"])


# --- net_growth: 對暫存 git repo，涵蓋三種成員資格情境 ---


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    _init_repo(root)
    _write_rule(root, "01-always.md", "---\n---\nalways-loaded content line\n")
    _write_rule(root, "02-scoped.md", '---\npaths: ["tasks/**"]\n---\nscoped content line\n')
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    monkeypatch.setattr(calg, "REPO_ROOT", root)
    monkeypatch.setattr(calg, "RULES_DIR", root / ".claude" / "rules")
    return root


class TestNetGrowth:
    def test_no_change_is_zero(self, repo: Path) -> None:
        files = calg.always_loaded_files()
        assert calg.net_growth("HEAD", files) == 0

    def test_added_line_in_existing_always_loaded_file_counts(self, repo: Path) -> None:
        p = repo / ".claude" / "rules" / "01-always.md"
        p.write_text(p.read_text(encoding="utf-8") + "one more line\n", encoding="utf-8")
        files = calg.always_loaded_files()
        assert calg.net_growth("HEAD", files) == 1

    def test_untracked_new_always_loaded_file_counts(self, repo: Path) -> None:
        """回歸：untracked 新檔過去因 `git diff --numstat` 看不到 untracked 檔而計 0。"""
        _write_rule(repo, "03-new.md", "---\n---\nline one\nline two\n")
        files = calg.always_loaded_files()
        growth = calg.net_growth("HEAD", files)
        assert growth > 0, "untracked 新增 always-loaded 檔必須計入淨增，不可為 0"

    def test_deleted_always_loaded_file_counts_as_negative(self, repo: Path) -> None:
        """回歸：刪除既有 always-loaded 檔案時，其行數過去被完全忽略而非計入淨減。"""
        (repo / ".claude" / "rules" / "01-always.md").unlink()
        files = calg.always_loaded_files()
        growth = calg.net_growth("HEAD", files)
        assert growth < 0, "刪除既有 always-loaded 檔必須計入淨減"

    def test_rescoped_file_no_longer_counts_its_content(self, repo: Path) -> None:
        """回歸：always-loaded 檔案改成 paths:-scoped 後，整份行數應退出 always-loaded
        面計入淨減，而非因為「目前已不是 always-loaded 檔」就完全不被比較。
        """
        p = repo / ".claude" / "rules" / "01-always.md"
        p.write_text('---\npaths: ["x/**"]\n---\nalways-loaded content line\n', encoding="utf-8")
        files = calg.always_loaded_files()
        growth = calg.net_growth("HEAD", files)
        assert growth < 0, "由 always-loaded 轉為 scoped 應計入淨減"


class TestMainBaseEqualsForm:
    def test_base_equals_form_reaches_check_mode(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """回歸：`--base=<ref>` 過去被 main() 靜默忽略，落回 baseline 模式並 exit 0
        （即使實際上是要做 check 模式）。"""
        exit_code = calg.main(["--base=HEAD"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "淨增行數" in captured.out

    def test_unknown_arg_exits_2(self, repo: Path) -> None:
        assert calg.main(["--bogus"]) == 2


class TestGitUnavailable:
    def test_run_git_wraps_missing_binary_as_runtime_error(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回歸：git 不可用（FileNotFoundError）過去未被捕捉，導致 main() 以未捕捉例外
        的方式結束（exit 1），與文件宣稱的 exit 2（設定錯誤）矛盾。"""

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(calg.subprocess, "run", _boom)
        with pytest.raises(RuntimeError):
            calg._run_git("status")


class TestGitShowFailurePropagates:
    """回歸（Codex Round 2 re-review 發現）：`_always_loaded_paths_at_ref` /
    `_line_count_at_ref` 過去吞掉 `git show` 的 RuntimeError，當成「該 ref 下讀不到
    此檔」保守跳過或回傳 0。但 `_run_git` 的 RuntimeError 也涵蓋 git 逾時 / 缺失 /
    物件損毀等真正的執行失敗——`ls-tree` 剛列出的路徑理論上不會讀不到，吞掉例外會讓
    這些真正的故障被誤判成「檔案不存在」而悄悄漏算，違反本檔案文件宣稱的 exit 2 契約。
    """

    def test_always_loaded_paths_at_ref_propagates_show_failure(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_run_git = calg._run_git

        def _fake_run_git(*args: str) -> str:
            if args and args[0] == "show":
                raise RuntimeError("simulated git show failure")
            return real_run_git(*args)

        monkeypatch.setattr(calg, "_run_git", _fake_run_git)
        with pytest.raises(RuntimeError):
            calg._always_loaded_paths_at_ref("HEAD")

    def test_line_count_at_ref_propagates_show_failure(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_run_git(*_args: str) -> str:
            raise RuntimeError("simulated git show failure")

        monkeypatch.setattr(calg, "_run_git", _fake_run_git)
        with pytest.raises(RuntimeError):
            calg._line_count_at_ref("HEAD", "01-always.md")

    def test_net_growth_surfaces_show_failure_as_exit_2_via_main(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """端對端確認：git show 故障最終讓 main() 回傳 2（設定錯誤），而不是靜默算出
        一個看似合理但錯誤的淨增數字。"""
        # 先製造一個 base_paths - current_paths 的情境（刪除既有 always-loaded 檔），
        # 這樣 net_growth 一定會呼叫 _line_count_at_ref。
        (repo / ".claude" / "rules" / "01-always.md").unlink()

        real_run_git = calg._run_git

        def _fake_run_git(*args: str) -> str:
            if args and args[0] == "show":
                raise RuntimeError("simulated git show failure")
            return real_run_git(*args)

        monkeypatch.setattr(calg, "_run_git", _fake_run_git)
        assert calg.main(["--base", "HEAD"]) == 2

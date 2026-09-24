"""CITEPATH-* tests for scripts/check_cited_paths.py。

驗證從 markdown inline code 抽出路徑引用、對單一目標 repo 檢查存在與否、以及 exit code 契約。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
"""

import importlib.util
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parent.parent / "check_cited_paths.py"
_spec = importlib.util.spec_from_file_location("check_cited_paths", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
check_cited_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_cited_paths)


def _make_repo(root: Path) -> Path:
    """建立一個最小的假 repo：scripts/、tasks/nightly_agent/drafter.py、CLAUDE.md。"""
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "lint.py").write_text("x", encoding="utf-8")
    (root / "tasks" / "nightly_agent").mkdir(parents=True)
    (root / "tasks" / "nightly_agent" / "drafter.py").write_text("x", encoding="utf-8")
    (root / "CLAUDE.md").write_text("x", encoding="utf-8")
    return root


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestExtractCandidates:
    def test_citepath_ep_001_path_with_extension_is_candidate(self, tmp_path: Path) -> None:
        """CITEPATH-EP-001: 含副檔名的路徑，即使第一段目錄不存在也要檢查"""
        repo = _make_repo(tmp_path)
        got = check_cited_paths.extract_candidates("見 `config/financial_accounts.toml`", repo)
        assert got == ["config/financial_accounts.toml"]

    def test_citepath_ep_002_dir_with_trailing_slash_is_candidate(self, tmp_path: Path) -> None:
        """CITEPATH-EP-002: 結尾斜線的目錄引用要檢查"""
        repo = _make_repo(tmp_path)
        assert check_cited_paths.extract_candidates("`scripts/cron/`", repo) == ["scripts/cron/"]

    def test_citepath_ep_003_no_ext_path_under_existing_top_dir(self, tmp_path: Path) -> None:
        """CITEPATH-EP-003: 無副檔名、第一段是既有頂層目錄的路徑要檢查"""
        repo = _make_repo(tmp_path)
        got = check_cited_paths.extract_candidates("`tasks/nightly_agent`", repo)
        assert got == ["tasks/nightly_agent"]

    def test_citepath_ep_004_line_suffix_is_stripped(self, tmp_path: Path) -> None:
        """CITEPATH-EP-004: `path:line` 與 `path:start-end` 去掉行號後檢查"""
        repo = _make_repo(tmp_path)
        text = "`tasks/nightly_agent/drafter.py:191` 與 `CLAUDE.md:316-326`"
        got = check_cited_paths.extract_candidates(text, repo)
        assert got == ["tasks/nightly_agent/drafter.py", "CLAUDE.md"]

    def test_citepath_ep_005_non_path_tokens_are_ignored(self, tmp_path: Path) -> None:
        """CITEPATH-EP-005: remote ref、owner/repo、npm scope、版本號、URL、flag、絕對路徑都不算"""
        repo = _make_repo(tmp_path)
        text = (
            "`origin/main` `heyu-ai/yibi-stack` `@anthropic-ai/claude-code` `2.1.274` "
            "`https://x.com/a.md` `--park` `/Users/me/a.md` `~/a.md` `+32/-4` `3/3` "
            "`OTEL_LOG_MANAGED_SETTINGS=0` `claude plugin install x`"
        )
        assert check_cited_paths.extract_candidates(text, repo) == []

    def test_citepath_ep_006_fenced_code_is_skipped(self, tmp_path: Path) -> None:
        """CITEPATH-EP-006: fenced code block 內的路徑不抽取（多為示範指令）"""
        repo = _make_repo(tmp_path)
        text = "```bash\n`missing/a.py`\n```\n`also/missing.py`\n"
        assert check_cited_paths.extract_candidates(text, repo) == ["also/missing.py"]

    def test_citepath_ep_008_schemeless_url_is_ignored(self, tmp_path: Path) -> None:
        """CITEPATH-EP-008: 沒寫 scheme 的網址（第一段像網域、repo 內不存在）不算路徑"""
        repo = _make_repo(tmp_path)
        text = "`raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`"
        assert check_cited_paths.extract_candidates(text, repo) == []

    def test_citepath_ep_009_dotted_first_segment_that_exists_is_kept(self, tmp_path: Path) -> None:
        """CITEPATH-EP-009: 第一段含點但存在於 repo（例如 .claude/、a.b/）仍要檢查"""
        repo = _make_repo(tmp_path)
        (repo / "my.pkg").mkdir()
        text = "`.claude/rules/x.md` `my.pkg/missing.py`"
        got = check_cited_paths.extract_candidates(text, repo)
        assert got == [".claude/rules/x.md", "my.pkg/missing.py"]

    def test_citepath_ep_007_duplicates_are_reported_once(self, tmp_path: Path) -> None:
        """CITEPATH-EP-007: 同一路徑出現多次只列一次，保留首次出現順序"""
        repo = _make_repo(tmp_path)
        text = "`b/x.md` `a/y.md` `b/x.md`"
        assert check_cited_paths.extract_candidates(text, repo) == ["b/x.md", "a/y.md"]


class TestExistsInRepo:
    def test_citepath_ex_001_existing_and_missing_paths(self, tmp_path: Path) -> None:
        """CITEPATH-EX-001: 存在的路徑為 True，既有目錄下不存在的路徑為 False"""
        repo = _make_repo(tmp_path)
        assert check_cited_paths.exists_in_repo("tasks/nightly_agent/drafter.py", repo)
        assert check_cited_paths.exists_in_repo("scripts/", repo)
        assert not check_cited_paths.exists_in_repo("scripts/cron/", repo)

    def test_citepath_ex_002_glob_needs_at_least_one_match(self, tmp_path: Path) -> None:
        """CITEPATH-EX-002: glob 至少命中一個才算存在"""
        repo = _make_repo(tmp_path)
        assert check_cited_paths.exists_in_repo("tasks/**/*.py", repo)
        assert not check_cited_paths.exists_in_repo("tasks/**/*.sh", repo)

    def test_citepath_ex_003_bare_filename_found_anywhere(self, tmp_path: Path) -> None:
        """CITEPATH-EX-003: 不含斜線的檔名在 repo 任何深度存在即可"""
        repo = _make_repo(tmp_path)
        assert check_cited_paths.exists_in_repo("drafter.py", repo)
        assert not check_cited_paths.exists_in_repo("runner.py", repo)

    def test_citepath_ex_004_worktree_copies_do_not_count(self, tmp_path: Path) -> None:
        """CITEPATH-EX-004: 只存在於 .claude/worktrees/ 副本或 .git 的檔名不算存在"""
        repo = _make_repo(tmp_path)
        wt = repo / ".claude" / "worktrees" / "feat" / "tasks"
        wt.mkdir(parents=True)
        (wt / "only_in_worktree.py").write_text("x", encoding="utf-8")
        (repo / ".git").mkdir()
        (repo / ".git" / "only_in_git.py").write_text("x", encoding="utf-8")
        assert not check_cited_paths.exists_in_repo("only_in_worktree.py", repo)
        assert not check_cited_paths.exists_in_repo("only_in_git.py", repo)

    def test_citepath_ex_005_numbered_prefix_shorthand(self, tmp_path: Path) -> None:
        """CITEPATH-EX-005: `.claude/rules/13` 這種編號簡寫，同層有 `13-*` 即算存在；沒有就算缺"""
        repo = _make_repo(tmp_path)
        rules = repo / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "13-bash-anti-patterns.md").write_text("x", encoding="utf-8")
        assert check_cited_paths.exists_in_repo(".claude/rules/13", repo)
        assert not check_cited_paths.exists_in_repo(".claude/rules/12", repo)
        assert not check_cited_paths.exists_in_repo(".claude/rules/1", repo)


class TestMain:
    def test_citepath_mn_001_all_present_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-001: 全部存在時 exit 0，逐條印 [OK]"""
        repo = _make_repo(tmp_path / "repo")
        doc = _write(tmp_path / "doc.md", "`CLAUDE.md` 與 `scripts/lint.py`")
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "[OK] CLAUDE.md" in out
        assert "[OK] scripts/lint.py" in out

    def test_citepath_mn_002_issue_458_shape_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-002: 重現 #458——引用另一個 repo 的路徑，必須 exit 1 並點名兩條"""
        repo = _make_repo(tmp_path / "repo")
        body = (
            "- `scripts/cron/*.sh` **未直接呼叫 `claude`**\n"
            "- 但 `CLAUDE.md` 與 `skills/monthly-financial-sync/SKILL.md` 等排程 runbook\n"
        )
        doc = _write(tmp_path / "issue.md", body)
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 1
        captured = capsys.readouterr()
        assert "[MISSING] scripts/cron/*.sh" in captured.out
        assert "[MISSING] skills/monthly-financial-sync/SKILL.md" in captured.out
        assert "[OK] CLAUDE.md" in captured.out
        assert "[FAIL]" in captured.err

    def test_citepath_mn_003_no_candidates_warns_and_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-003: 完全沒有路徑引用時 exit 0，但在 stderr 印 [WARN]，不可靜默"""
        repo = _make_repo(tmp_path / "repo")
        doc = _write(tmp_path / "doc.md", "純文字，沒有任何路徑。")
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 0
        assert "[WARN]" in capsys.readouterr().err

    def test_citepath_mn_005_expected_absent_marker_waives_only_listed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-005: `<!-- expected-absent: ... -->` 只放行明列的路徑，其他缺的仍 exit 1"""
        repo = _make_repo(tmp_path / "repo")
        body = (
            "<!-- expected-absent: .mcp.json scheduled_tasks.json -->\n"
            "本 repo 實測無 `.mcp.json` 與 `scheduled_tasks.json`，但 `scripts/cron/` 應該存在\n"
        )
        doc = _write(tmp_path / "doc.md", body)
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 1
        out = capsys.readouterr().out
        assert "[ABSENT-OK] .mcp.json" in out
        assert "[ABSENT-OK] scheduled_tasks.json" in out
        assert "[MISSING] scripts/cron/" in out

    def test_citepath_mn_006_expected_absent_path_that_exists_is_flagged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-006: 宣告為 expected-absent 卻實際存在時 exit 1——宣告本身錯了"""
        repo = _make_repo(tmp_path / "repo")
        doc = _write(
            tmp_path / "doc.md", "<!-- expected-absent: CLAUDE.md -->\n本 repo 沒有 `CLAUDE.md`\n"
        )
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 1
        assert "[STALE-ABSENT] CLAUDE.md" in capsys.readouterr().out

    def test_citepath_mn_004_bad_arguments_exit_two(self, tmp_path: Path) -> None:
        """CITEPATH-MN-004: 檔案或 repo 不存在時 exit 2（使用錯誤，不可與「有缺路徑」混同）"""
        repo = _make_repo(tmp_path / "repo")
        doc = _write(tmp_path / "doc.md", "`CLAUDE.md`")
        assert check_cited_paths.main([str(tmp_path / "nope.md"), "--repo", str(repo)]) == 2
        assert check_cited_paths.main([str(doc), "--repo", str(tmp_path / "no-repo")]) == 2

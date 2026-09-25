"""CITEPATH-* tests for scripts/check_cited_paths.py。

驗證路徑抽取（inline code、markdown 連結、fence 規則）、以 git ls-files 判斷存在、
expected-absent 宣告，以及 exit code 契約（0／1／2／3）。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
fixture repo 是真的 git repo（git init + git add），因為「存在」以 git 版控為準。
"""

import importlib.util
import subprocess  # nosec B404
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parent.parent / "check_cited_paths.py"
_spec = importlib.util.spec_from_file_location("check_cited_paths", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
check_cited_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_cited_paths)

_BASE_FILES = (
    "scripts/lint.py",
    "scripts/cron/a.sh",
    "tasks/nightly_agent/drafter.py",
    "CLAUDE.md",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=60
    )


def _make_repo(root: Path, files: tuple[str, ...] = _BASE_FILES) -> Path:
    """建立 git repo 並 git add 指定檔案（不需 commit：ls-files 讀的是 index）。"""
    root.mkdir(parents=True, exist_ok=True)
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    return root


def _index(files: tuple[str, ...] = _BASE_FILES, remotes: tuple[str, ...] = ()) -> object:
    return check_cited_paths.RepoIndex(files=set(files), remotes=set(remotes))


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _cands(text: str, index: object | None = None) -> list[str]:
    return check_cited_paths.extract_candidates(text, index or _index())[0]


class TestExtractCandidates:
    def test_citepath_ep_001_path_with_extension_is_candidate(self) -> None:
        """CITEPATH-EP-001: 含副檔名的路徑，即使第一段目錄不在 repo 也要檢查"""
        assert _cands("見 `config/financial_accounts.toml`") == ["config/financial_accounts.toml"]

    def test_citepath_ep_002_trailing_slash_dir_is_candidate_even_if_absent(self) -> None:
        """CITEPATH-EP-002: 結尾斜線的目錄引用一律檢查，第一段不存在也一樣（#458 形狀）"""
        got = _cands("`scripts/cron/` 與 `skills/monthly-financial-sync/`")
        assert got == ["scripts/cron/", "skills/monthly-financial-sync/"]

    def test_citepath_ep_003_no_ext_path_under_tracked_top_dir(self) -> None:
        """CITEPATH-EP-003: 無副檔名、第一段是已追蹤頂層目錄的兩段路徑要檢查"""
        assert _cands("`tasks/nightly_agent`") == ["tasks/nightly_agent"]

    def test_citepath_ep_004_location_suffixes_are_stripped(self) -> None:
        """CITEPATH-EP-004: `:行`、`:行:欄`、`:起-迄`、`#L12`、`#錨點`、`::node` 去掉後檢查"""
        text = (
            "`a/one.py:191` `a/two.md:316-326` `a/three.py:12:5` `a/four.py#L12` "
            "`a/five.md#section` `a/six.py::test_x`"
        )
        assert _cands(text) == [
            "a/one.py",
            "a/two.md",
            "a/three.py",
            "a/four.py",
            "a/five.md",
            "a/six.py",
        ]

    def test_citepath_ep_005_non_path_tokens_are_ignored(self) -> None:
        """CITEPATH-EP-005: remote ref、npm scope、版本號、網址、flag、絕對路徑、shell 片段都不算"""
        text = (
            "`origin/main` `@anthropic-ai/claude-code` `2.1.274` `https://x.com/a.md` `--park` "
            "`/Users/me/a.md` `~/a.md` `+32/-4` `3/3` `KEY=a/b.py` `$HOME/a.py` "
            "`python3` `tasks.mycelium`"
        )
        cands, skipped = check_cited_paths.extract_candidates(text, _index(remotes=("origin",)))
        assert cands == []
        assert skipped == []

    def test_citepath_ep_006_backtick_and_tilde_fences_are_skipped(self) -> None:
        """CITEPATH-EP-006: ``` 與 ~~~ fence 內的路徑都不抽取"""
        text = "```bash\n`in/a.py`\n```\n~~~\n`in/b.py`\n~~~\n`out/c.py`\n"
        assert _cands(text) == ["out/c.py"]

    def test_citepath_ep_007_duplicates_are_reported_once(self) -> None:
        """CITEPATH-EP-007: 同一路徑出現多次只列一次，保留首次出現順序"""
        assert _cands("`b/x.md` `a/y.md` `b/x.md`") == ["b/x.md", "a/y.md"]

    def test_citepath_ep_008_schemeless_url_ignored_but_dotted_dir_kept(self) -> None:
        """CITEPATH-EP-008: 第一段形似網域者不算路徑；`config.d/` 這種含點目錄仍要檢查"""
        text = "`raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md` `config.d/app.toml`"
        assert _cands(text) == ["config.d/app.toml"]

    def test_citepath_ep_009_dot_leading_first_segment_is_kept(self) -> None:
        """CITEPATH-EP-009: 以點開頭的第一段（`.claude/`）不會被當成網域排除"""
        assert _cands("`.claude/rules/x.md` `./scripts/lint.py`") == [
            ".claude/rules/x.md",
            "./scripts/lint.py",
        ]

    def test_citepath_ep_010_longer_fence_containing_shorter_fence_line(self) -> None:
        """CITEPATH-EP-010: 4 反引號 fence 內的 3 反引號行不會提前關閉 fence"""
        text = "````markdown\n```\n`in/a.py`\n```\n````\n`out/b.py`\n"
        assert _cands(text) == ["out/b.py"]

    def test_citepath_ep_011_tilde_fence_ignores_backtick_lines(self) -> None:
        """CITEPATH-EP-011: ~~~ fence 只會被 ~~~ 關閉，內含的 ``` 行不影響"""
        text = "~~~\n```\n`in/a.py`\n~~~\n`out/b.py`\n"
        assert _cands(text) == ["out/b.py"]

    def test_citepath_ep_012_backtick_info_string_line_is_not_a_fence(self) -> None:
        """CITEPATH-EP-012: 同一行開關的 ```bash x``` 是 inline code，不是 fence"""
        text = "```bash scripts/x.sh```\n`out/b.py`\n"
        assert _cands(text) == ["scripts/x.sh", "out/b.py"]

    def test_citepath_ep_013_inline_command_is_split_into_tokens(self) -> None:
        """CITEPATH-EP-013: inline code 內的整條指令依空白切開，抽出其中的路徑"""
        assert _cands("`python3 scripts/missing.py --x (see a/b.md)`") == [
            "scripts/missing.py",
            "a/b.md",
        ]

    def test_citepath_ep_014_unknown_extension_with_slash_is_candidate(self) -> None:
        """CITEPATH-EP-014: 含斜線者預設都檢查，副檔名不在清單內也一樣"""
        assert _cands("`lib/main.dart` `src/App.tsx` `x/y.weird`") == [
            "lib/main.dart",
            "src/App.tsx",
            "x/y.weird",
        ]

    def test_citepath_ep_015_three_segments_without_extension_always_checked(self) -> None:
        """CITEPATH-EP-015: 三段以上、沒有副檔名、第一段不存在的路徑也要檢查"""
        assert _cands("`skills/foo/bar`") == ["skills/foo/bar"]

    def test_citepath_ep_016_owner_repo_shape_is_skipped_not_dropped(self) -> None:
        """CITEPATH-EP-016: 兩段、無點、第一段非頂層項目者列入 skipped；頂層目錄下的仍檢查"""
        cands, skipped = check_cited_paths.extract_candidates(
            "`heyu-ai/yibi-stack` `scripts/cron`", _index()
        )
        assert cands == ["scripts/cron"]
        assert skipped == ["heyu-ai/yibi-stack"]

    def test_citepath_ep_017_known_extensionless_names(self) -> None:
        """CITEPATH-EP-017: `Makefile`、`Dockerfile` 算路徑；`gh`、`python3` 這類字詞不算"""
        assert _cands("`Makefile` `Dockerfile` `gh` `python3`") == ["Makefile", "Dockerfile"]

    def test_citepath_ep_018_bare_name_needs_known_extension(self) -> None:
        """CITEPATH-EP-018: 不含斜線的 token 要有已知副檔名；`tasks.mycelium` 不算、大寫副檔名算"""
        assert _cands("`settings.json` `tasks.mycelium` `README.MD`") == [
            "settings.json",
            "README.MD",
        ]

    def test_citepath_ep_019_markdown_link_targets(self) -> None:
        """CITEPATH-EP-019: markdown 相對連結要檢查；有 scheme 的網址與純錨點不算"""
        text = (
            "[a](scripts/missing.py) [b](docs/a.md#sec) [c](https://x.com/a.md) "
            "[d](#anchor) [e](<my%20dir/f.md>)"
        )
        assert _cands(text) == ["scripts/missing.py", "docs/a.md", "my dir/f.md"]

    def test_citepath_ep_020_multi_backtick_span(self) -> None:
        """CITEPATH-EP-020: 雙反引號包住的 inline code 也要抽取"""
        assert _cands("`` a/b.md `` 與 ``c/`d`.md``") == ["a/b.md"]

    def test_citepath_ep_021_crlf_lines(self) -> None:
        """CITEPATH-EP-021: CRLF 換行的 fence 與引用都能正確處理"""
        text = "```\r\n`in/a.py`\r\n```\r\n`out/b.py`\r\n"
        assert _cands(text) == ["out/b.py"]

    @pytest.mark.parametrize("ext", sorted(check_cited_paths._EXTS))
    def test_citepath_ep_022_every_known_extension_is_extracted_bare(self, ext: str) -> None:
        """CITEPATH-EP-022: 清單內每一個副檔名，不含斜線的檔名也會被抽出"""
        assert _cands(f"`name.{ext}`") == [f"name.{ext}"]

    def test_citepath_ep_023_expected_absent_inside_fence_is_ignored(self) -> None:
        """CITEPATH-EP-023: fence 內作為範例的 expected-absent 宣告不算數"""
        text = "```\n<!-- expected-absent: a.md -->\n```\n<!-- expected-absent: b.md c.md -->\n"
        assert check_cited_paths.parse_expected_absent(text) == ["b.md", "c.md"]

    def test_citepath_ep_024_expected_absent_inside_inline_code_is_ignored(self) -> None:
        """CITEPATH-EP-024: inline code 內作為範例的 expected-absent 宣告不算數"""
        text = "用 `<!-- expected-absent: <path> -->` 宣告\n<!-- expected-absent: real.md -->\n"
        assert check_cited_paths.parse_expected_absent(text) == ["real.md"]


class TestResolve:
    def _status(self, token: str, files: tuple[str, ...] = _BASE_FILES) -> str:
        return check_cited_paths.resolve(token, _index(files)).status

    def test_citepath_rs_001_existing_file_dir_and_missing(self) -> None:
        """CITEPATH-RS-001: 已追蹤的檔案與目錄為 ok，不存在者為 missing"""
        assert self._status("tasks/nightly_agent/drafter.py") == "ok"
        assert self._status("scripts/") == "ok"
        assert self._status("tasks/nightly_agent") == "ok"
        assert self._status("scripts/nope/") == "missing"
        assert self._status("scripts/nope.py") == "missing"

    def test_citepath_rs_002_trailing_slash_is_rooted_not_any_depth(self) -> None:
        """CITEPATH-RS-002: `cron/` 必須是根目錄下的目錄，不會對到 `scripts/cron/`"""
        assert self._status("cron/") == "missing"
        assert self._status("scripts/cron/") == "ok"
        assert self._status("scripts/lint.py/") == "missing"

    def test_citepath_rs_003_glob_with_slash(self) -> None:
        """CITEPATH-RS-003: `**` 可跨目錄；`tasks/**.py` 不會崩潰"""
        assert self._status("tasks/**/*.py") == "ok"
        assert self._status("tasks/**/*.sh") == "missing"
        assert self._status("tasks/**.py") == "ok"
        assert self._status("scripts/*.py") == "ok"
        assert self._status("scripts/*.sh") == "missing"

    def test_citepath_rs_004_bare_glob(self) -> None:
        """CITEPATH-RS-004: 不含斜線的 glob 比對檔名，須完整比對（`x.sh.bak` 不算 `*.sh`）"""
        assert self._status("*.py") == "ok"
        assert self._status("*.rs") == "missing"
        assert self._status("*.sh", ("a/x.sh.bak",)) == "missing"

    def test_citepath_rs_005_bare_filename_unique_ambiguous_missing(self) -> None:
        """CITEPATH-RS-005: 單獨檔名恰好一個才 ok；多個 ambiguous；沒有 missing"""
        res = check_cited_paths.resolve("drafter.py", _index())
        assert (res.status, res.matches) == ("ok", ["tasks/nightly_agent/drafter.py"])
        amb = check_cited_paths.resolve("SKILL.md", _index(("a/SKILL.md", "b/SKILL.md")))
        assert (amb.status, amb.matches) == ("ambiguous", ["a/SKILL.md", "b/SKILL.md"])
        assert self._status("runner.py") == "missing"

    def test_citepath_rs_006_case_must_match_exactly(self) -> None:
        """CITEPATH-RS-006: 大小寫必須逐字相同（macOS 檔案系統不分大小寫也不影響）"""
        assert self._status("Scripts/Lint.py") == "missing"
        assert self._status("claude.md") == "missing"

    def test_citepath_rs_007_numbered_prefix_shorthand(self) -> None:
        """CITEPATH-RS-007: `.claude/rules/13` 需同層有 `13-*.md`；非數字、`.orig`、父目錄不存在都不算"""
        files = (
            ".claude/rules/13-bash.md",
            ".claude/rules/12-old.md.orig",
            "scripts/lint-old.py",
            "docs/guide-v2.md",
        )
        assert self._status(".claude/rules/13", files) == "ok"
        assert self._status(".claude/rules/12", files) == "missing"
        assert self._status(".claude/rules/1", files) == "missing"
        assert self._status("scripts/lint", files) == "missing"
        assert self._status("docs/guide", files) == "missing"
        assert self._status("nope/dir/13", files) == "missing"

    def test_citepath_rs_008_parent_escape_is_outside(self) -> None:
        """CITEPATH-RS-008: 正規化後跳出 repo 的路徑為 outside；`./` 與內部 `..` 正常解析"""
        assert self._status("../sibling/CLAUDE.md") == "outside"
        assert self._status("scripts/../../x.md") == "outside"
        assert self._status("./scripts/lint.py") == "ok"
        assert self._status("scripts/cron/../lint.py") == "ok"


class TestLoadIndex:
    def test_citepath_li_001_only_tracked_files_count(self, tmp_path: Path) -> None:
        """CITEPATH-LI-001: 未追蹤、gitignored、其他 worktree 目錄下的檔案都不在 index"""
        repo = _make_repo(tmp_path / "repo")
        (repo / ".gitignore").write_text(".runtime/\n", encoding="utf-8")
        _git(repo, "add", ".gitignore")
        (repo / ".runtime").mkdir()
        (repo / ".runtime" / "state.json").write_text("x", encoding="utf-8")
        (repo / "untracked.md").write_text("x", encoding="utf-8")
        index = check_cited_paths.load_index(repo)
        assert "CLAUDE.md" in index.files
        assert ".runtime/state.json" not in index.files
        assert "untracked.md" not in index.files

    def test_citepath_li_002_remotes_are_loaded(self, tmp_path: Path) -> None:
        """CITEPATH-LI-002: git remote 名稱會讀進 index，用來排除 `origin/main`"""
        repo = _make_repo(tmp_path / "repo")
        _git(repo, "remote", "add", "origin", "https://example.com/x.git")
        assert check_cited_paths.load_index(repo).remotes == {"origin"}

    def test_citepath_li_003_non_repo_and_subdir_raise(self, tmp_path: Path) -> None:
        """CITEPATH-LI-003: 不是 git repo、或指到 repo 的子目錄，都丟 RuntimeError"""
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(RuntimeError, match="不是 git repo"):
            check_cited_paths.load_index(plain)
        repo = _make_repo(tmp_path / "repo")
        with pytest.raises(RuntimeError, match="根目錄"):
            check_cited_paths.load_index(repo / "scripts")


class TestMain:
    def _run(
        self, tmp_path: Path, body: str, files: tuple[str, ...] = _BASE_FILES
    ) -> tuple[int, Path]:
        repo = _make_repo(tmp_path / "repo", files)
        doc = _write(tmp_path / "doc.md", body)
        return check_cited_paths.main([str(doc), "--repo", str(repo)]), repo

    def test_citepath_mn_001_all_present_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-001: 全部存在時 exit 0；單獨檔名印出命中的完整路徑"""
        rc, _ = self._run(tmp_path, "`CLAUDE.md` `scripts/lint.py` `drafter.py`")
        assert rc == 0
        out = capsys.readouterr().out
        assert "[OK] CLAUDE.md -> CLAUDE.md" in out
        assert "[OK] scripts/lint.py" in out
        assert "[OK] drafter.py -> tasks/nightly_agent/drafter.py" in out

    def test_citepath_mn_002_issue_458_shape_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-002: 重現 #458——引用另一個 repo 的路徑，必須 exit 1 並點名兩條"""
        body = (
            "- `scripts/cron/*.sh` 與 `scripts/cron2/*.sh` **未直接呼叫 `claude`**\n"
            "- 但 `CLAUDE.md` 與 `skills/monthly-financial-sync/SKILL.md` 等排程 runbook\n"
        )
        rc, _ = self._run(tmp_path, body)
        assert rc == 1
        captured = capsys.readouterr()
        assert "[MISSING] scripts/cron2/*.sh" in captured.out
        assert "[MISSING] skills/monthly-financial-sync/SKILL.md" in captured.out
        assert "[OK] scripts/cron/*.sh" in captured.out
        assert "[FAIL]" in captured.err

    def test_citepath_mn_003_no_candidates_exits_three(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-003: 沒有任何引用也沒有宣告時 exit 3（無法判斷，不可當成通過）"""
        rc, _ = self._run(tmp_path, "純文字，沒有任何路徑。`gh` `python3`")
        assert rc == 3
        assert "[FAIL]" in capsys.readouterr().err

    def test_citepath_mn_004_bad_arguments_exit_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-004: 檔案不存在、repo 不是目錄、repo 不是 git repo 都 exit 2"""
        repo = _make_repo(tmp_path / "repo")
        doc = _write(tmp_path / "doc.md", "`CLAUDE.md`")
        plain = tmp_path / "plain"
        plain.mkdir()
        assert check_cited_paths.main([str(tmp_path / "nope.md"), "--repo", str(repo)]) == 2
        assert check_cited_paths.main([str(doc), "--repo", str(tmp_path / "no-repo")]) == 2
        assert check_cited_paths.main([str(doc), "--repo", str(plain)]) == 2
        assert "[FAIL]" in capsys.readouterr().err

    def test_citepath_mn_005_expected_absent_waives_only_listed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-005: `expected-absent` 只放行明列的路徑，其他缺的仍 exit 1"""
        body = (
            "<!-- expected-absent: .mcp.json scheduled_tasks.json -->\n"
            "本 repo 實測無 `.mcp.json` 與 `scheduled_tasks.json`，但 `scripts/nope/` 應該存在\n"
        )
        rc, _ = self._run(tmp_path, body)
        assert rc == 1
        out = capsys.readouterr().out
        assert "[ABSENT-OK] .mcp.json" in out
        assert "[ABSENT-OK] scheduled_tasks.json" in out
        assert "[MISSING] scripts/nope/" in out

    def test_citepath_mn_006_stale_absent_when_cited(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-006: 宣告為 expected-absent 且內文引用、卻實際存在時 exit 1"""
        rc, _ = self._run(
            tmp_path, "<!-- expected-absent: CLAUDE.md -->\n本 repo 沒有 `CLAUDE.md`\n"
        )
        assert rc == 1
        assert "[STALE-ABSENT] CLAUDE.md" in capsys.readouterr().out

    def test_citepath_mn_007_stale_absent_when_not_cited(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-007: 宣告的檔案存在但內文沒有用反引號引用，仍要 exit 1（AC-3）"""
        rc, _ = self._run(tmp_path, "<!-- expected-absent: CLAUDE.md -->\n本 repo 沒有 CLAUDE.md\n")
        assert rc == 1
        assert "[STALE-ABSENT] CLAUDE.md" in capsys.readouterr().out

    def test_citepath_mn_008_only_declarations_absent_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-008: 只有宣告、宣告的都不存在時 exit 0（有檢查到東西，不是 exit 3）"""
        rc, _ = self._run(tmp_path, "<!-- expected-absent: .mcp.json -->\n實測無此檔\n")
        assert rc == 0
        assert "[ABSENT-OK] .mcp.json" in capsys.readouterr().out

    def test_citepath_mn_009_non_utf8_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-009: 非 UTF-8 檔案 exit 2，不可噴 traceback 變成 exit 1"""
        repo = _make_repo(tmp_path / "repo")
        doc = tmp_path / "doc.md"
        doc.write_bytes(b"\xff\xfe `scripts/missing.py`")
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 2
        assert "[FAIL]" in capsys.readouterr().err

    def test_citepath_mn_010_unreadable_file_exits_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CITEPATH-MN-010: 檔案存在但讀取時 OSError（權限等），exit 2"""
        repo = _make_repo(tmp_path / "repo")
        doc = _write(tmp_path / "doc.md", "`CLAUDE.md`")
        real_read = Path.read_text

        def fake_read(self: Path, *args: object, **kwargs: object) -> str:
            if self == doc:
                raise PermissionError("denied")
            return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", fake_read)
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 2

    def test_citepath_mn_011_outside_path_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-011: `../` 指到旁邊 repo 的檔案時 exit 1，即使那個檔案存在"""
        _make_repo(tmp_path / "sibling", ("x.md",))
        rc, _ = self._run(tmp_path, "`../sibling/x.md`")
        assert rc == 1
        assert "[OUTSIDE] ../sibling/x.md" in capsys.readouterr().out

    def test_citepath_mn_012_ambiguous_bare_name_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-012: 單獨檔名同名多個時 exit 1，並列出所有命中"""
        rc, _ = self._run(tmp_path, "`SKILL.md`", ("a/SKILL.md", "b/SKILL.md"))
        assert rc == 1
        assert (
            "[AMBIGUOUS] SKILL.md（同名 2 個：a/SKILL.md, b/SKILL.md）" in capsys.readouterr().out
        )

    def test_citepath_mn_013_skipped_tokens_are_visible_and_do_not_fail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-013: owner/repo 形狀的 token 在 stderr 印 [SKIPPED]，本身不讓閘門失敗"""
        rc, _ = self._run(tmp_path, "`heyu-ai/yibi-stack` 的 `CLAUDE.md`")
        assert rc == 0
        assert "[SKIPPED] heyu-ai/yibi-stack" in capsys.readouterr().err

    def test_citepath_mn_014_untracked_file_is_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-014: 磁碟上有、但沒有 git add 的檔案判為 missing"""
        repo = _make_repo(tmp_path / "repo")
        (repo / "scripts" / "new.py").write_text("x", encoding="utf-8")
        doc = _write(tmp_path / "doc.md", "`scripts/new.py`")
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 1
        assert "[MISSING] scripts/new.py" in capsys.readouterr().out

    def test_citepath_mn_015_markdown_link_to_missing_file_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-015: markdown 連結指向不存在的檔案時 exit 1"""
        rc, _ = self._run(tmp_path, "見 [說明](docs/missing.md) 與 `CLAUDE.md`")
        assert rc == 1
        assert "[MISSING] docs/missing.md" in capsys.readouterr().out

    def test_citepath_mn_016_stale_absent_when_declared_name_is_ambiguous(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-016: 宣告的單獨檔名其實同名多個（代表存在），也算宣告過時"""
        rc, _ = self._run(
            tmp_path,
            "<!-- expected-absent: SKILL.md -->\n沒有 SKILL.md\n",
            ("a/SKILL.md", "b/SKILL.md"),
        )
        assert rc == 1
        assert "[STALE-ABSENT] SKILL.md" in capsys.readouterr().out

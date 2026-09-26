"""scripts/check_cited_paths.py 的 CITEPATH-* 測試。

驗證全文路徑抽取（程式碼／散文語境、連結目標、清理規則）、以 git ls-files 判斷存在、
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
        """CITEPATH-EP-005: remote ref、npm scope、版本號、網址、flag、絕對路徑、shell 片段都不算；
        `=` 是分隔字元，所以 `KEY=a/b.py` 仍會檢查等號右邊的路徑"""
        text = (
            "`origin/main` `@anthropic-ai/claude-code` `2.1.274` `https://x.com/a.md` `--park` "
            "`/Users/me/a.md` `~/a.md` `+32/-4` `3/3` `KEY=a/b.py` `$HOME/a.py` "
            "`python3` `tasks.mycelium` [m](mailto:a@b.c)"
        )
        cands, skipped = check_cited_paths.extract_candidates(text, _index(remotes=("origin",)))
        assert cands == ["a/b.py"]
        assert skipped == []

    def test_citepath_ep_006_fence_content_is_extracted(self) -> None:
        """CITEPATH-EP-006: fence 內容也抽取——不追蹤 fence，fence 判斷錯位就不可能藏起路徑"""
        text = "```bash\nbash in/a.sh\n```\n~~~\n`in/b.py`\n~~~\n`out/c.py`\n"
        assert _cands(text) == ["in/a.sh", "in/b.py", "out/c.py"]

    def test_citepath_ep_007_duplicates_are_reported_once(self) -> None:
        """CITEPATH-EP-007: 同一路徑出現多次只列一次，保留首次出現順序"""
        assert _cands("`b/x.md` `a/y.md` `b/x.md`") == ["b/x.md", "a/y.md"]

    def test_citepath_ep_008_domain_like_first_segment_is_checked(self) -> None:
        """CITEPATH-EP-008: 第一段形似網域者也要檢查（`Foo.app/`、無 scheme 網址），不可靜默略過"""
        text = (
            "`raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md` "
            "`config.d/app.toml` `Foo.app/Contents/Info.plist`"
        )
        assert _cands(text) == [
            "raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md",
            "config.d/app.toml",
            "Foo.app/Contents/Info.plist",
        ]

    def test_citepath_ep_009_dot_leading_first_segment_is_kept(self) -> None:
        """CITEPATH-EP-009: 以點開頭的第一段（`.claude/`）不會被當成網域排除"""
        assert _cands("`.claude/rules/x.md` `./scripts/lint.py`") == [
            ".claude/rules/x.md",
            "./scripts/lint.py",
        ]

    def test_citepath_ep_012_inline_triple_backticks_do_not_affect_other_tokens(self) -> None:
        """CITEPATH-EP-012: 行內的三反引號不影響同一行與下一行其他 token 的抽取"""
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
        assert set(_cands(text)) == {"scripts/missing.py", "docs/a.md", "my dir/f.md"}

    def test_citepath_ep_020_multi_backtick_span(self) -> None:
        """CITEPATH-EP-020: 雙反引號包住的 inline code 也要抽取；含反引號的路徑被切成片段各自檢查"""
        assert _cands("`` a/b.md `` 與 ``c/`d`.md``") == ["a/b.md", "c/"]

    def test_citepath_ep_021_line_breaks(self) -> None:
        """CITEPATH-EP-021: CRLF、CR 換行都能處理；NEL（U+0085）不是換行，但仍是空白分隔"""
        assert _cands("`in/a.py`\r\n`out/b.py`\r`out/c.py`\n") == [
            "in/a.py",
            "out/b.py",
            "out/c.py",
        ]
        assert _cands("See `a/b.md`.\x85```\n`newdir/x.md`\n") == ["a/b.md", "newdir/x.md"]

    @pytest.mark.parametrize("ext", sorted(check_cited_paths._EXTS))
    def test_citepath_ep_022_every_known_extension_is_extracted_bare(self, ext: str) -> None:
        """CITEPATH-EP-022: 清單內每一個副檔名，不含斜線的檔名也會被抽出"""
        assert _cands(f"`name.{ext}`") == [f"name.{ext}"]

    def test_citepath_ep_023_declaration_after_other_content_is_ignored(self) -> None:
        """CITEPATH-EP-023: fence 內或文件中段的 expected-absent 宣告不算數，只認開頭區塊"""
        text = "```\n<!-- expected-absent: a.md -->\n```\n\n<!-- expected-absent: b.md -->\n"
        assert check_cited_paths.parse_expected_absent(text) == []
        text = "<!-- expected-absent: b.md c.md -->\n\n內文\n\n<!-- expected-absent: d.md -->\n"
        assert check_cited_paths.parse_expected_absent(text) == ["b.md", "c.md"]

    def test_citepath_ep_024_example_declaration_in_body_is_ignored(self) -> None:
        """CITEPATH-EP-024: 內文示範的宣告寫法不算數；開頭區塊的宣告照常生效"""
        text = "<!-- expected-absent: real.md -->\n\n用 `<!-- expected-absent: <path> -->` 宣告\n"
        assert check_cited_paths.parse_expected_absent(text) == ["real.md"]

    def test_citepath_ep_025_code_span_wrapped_across_lines(self) -> None:
        """CITEPATH-EP-025: 段落內被換行切開的 inline code 仍要抽取（換行視為空白）"""
        assert _cands("見 `CLAUDE.md`\n執行 `python3\nscripts/missing.py --x` 後再跑") == [
            "CLAUDE.md",
            "scripts/missing.py",
        ]
        assert "missing.py" in _cands("see `scripts/\nmissing.py` here")

    def test_citepath_ep_026_link_text_wrapped_across_lines(self) -> None:
        """CITEPATH-EP-026: 連結文字跨行時，連結目標仍要抽取"""
        assert _cands("見 [週報產生器的說明文件\n與設定](docs/missing.md) 以及") == [
            "docs/missing.md"
        ]

    def test_citepath_ep_027_reference_link_definitions(self) -> None:
        """CITEPATH-EP-027: 參考式連結的定義行 `[ref]: path` 要抽取目標；含空白的路徑切成片段檢查"""
        text = '見 [說明][ref] 與 [其他][r2]\n\n[ref]: docs/missing.md\n  [r2]: <my dir/a.md> "t"\n'
        cands = _cands(text)
        assert "docs/missing.md" in cands
        assert "dir/a.md" in cands
        text = "見 [說明][r]\n\n[r]:\n  newdir/guide\n\n[^1]: 註腳內文不是連結目標\n"
        assert _cands(text) == ["newdir/guide"]

    def test_citepath_ep_028_parentheses_inside_path(self) -> None:
        """CITEPATH-EP-028: 路徑內含成對括號時不截斷（連結目標與 inline code 都一樣）"""
        assert sorted(_cands("[x](docs/a(1).md) 與 `x/b(2).py`")) == ["docs/a(1).md", "x/b(2).py"]

    def test_citepath_ep_029_link_with_title(self) -> None:
        """CITEPATH-EP-029: 帶 title 的連結 `[t](path "title")` 也要抽取目標"""
        text = "[t](docs/missing.md \"title\") [u](<a b.md> 'x')"
        cands = _cands(text)
        assert "docs/missing.md" in cands
        assert "b.md" in cands

    def test_citepath_ep_032_unclosed_fence_does_not_hide_rest(self) -> None:
        """CITEPATH-EP-032: fence 到文件結尾仍未關閉時，後文照常抽取"""
        assert _cands("見 `CLAUDE.md`\n```\n改 `scripts/missing.py`\n") == [
            "CLAUDE.md",
            "scripts/missing.py",
        ]

    def test_citepath_ep_033_dot_leading_two_segments_are_checked_not_skipped(self) -> None:
        """CITEPATH-EP-033: 以點開頭的兩段路徑（`.github/workflows`）要檢查，不落入 owner/repo 略過"""
        cands, skipped = check_cited_paths.extract_candidates("`.github/workflows`", _index())
        assert cands == [".github/workflows"]
        assert skipped == []

    def test_citepath_ep_034_known_extensionless_name_is_not_owner_repo(self) -> None:
        """CITEPATH-EP-034: 第二段是已知無副檔名檔名（`tools/Dockerfile`）時要檢查，不略過"""
        cands, skipped = check_cited_paths.extract_candidates("`tools/Dockerfile`", _index())
        assert cands == ["tools/Dockerfile"]
        assert skipped == []

    @pytest.mark.parametrize("name", sorted(check_cited_paths._EXTENSIONLESS_NAMES))
    def test_citepath_ep_035_every_extensionless_name_is_extracted_bare(self, name: str) -> None:
        """CITEPATH-EP-035: 清單內每一個已知無副檔名檔名，單獨出現也會被抽出"""
        assert _cands(f"`{name}`") == [name]

    def test_citepath_ep_036_declaration_inside_multiline_code_span_is_ignored(self) -> None:
        """CITEPATH-EP-036: 跨行 inline code 內的 expected-absent 範例宣告不算數"""
        text = "Example: `\n<!-- expected-absent: docs/missing.md -->\n\n`\n"
        assert check_cited_paths.parse_expected_absent(text) == []

    def test_citepath_ep_037_declarations_only_in_leading_block(self) -> None:
        """CITEPATH-EP-037: 宣告只認文件開頭、第 0 欄、只由宣告行與空白行組成的區塊"""
        parse = check_cited_paths.parse_expected_absent
        assert parse("前一行\n\n<!-- expected-absent: a.md -->\n") == []
        assert parse("<!-- expected-absent: a.md -->\n後一行\n") == ["a.md"]
        text = "\n\n<!-- expected-absent: a.md -->\n<!-- expected-absent: b.md -->\n\n內文\n"
        assert parse(text) == ["a.md", "b.md"]
        assert parse("    <!-- expected-absent: a.md -->\n") == []
        assert parse("<!-- expected-absent: b.md -->") == ["b.md"]

    def test_citepath_ep_038_prose_context_rules(self) -> None:
        """CITEPATH-EP-038: 散文中看得出是路徑的斜線 token 要檢查；其他斜線詞列 skipped；
        散文中的單獨檔名不查"""
        text = "修改 scripts/missing.py 與 tasks/x，另見 A/B 測試、Read/Write/Edit 與 SKILL.md"
        cands, skipped = check_cited_paths.extract_candidates(text, _index())
        assert cands == ["scripts/missing.py", "tasks/x"]
        assert skipped == ["A/B", "Read/Write/Edit"]

    def test_citepath_ep_039_escaped_and_stray_backticks_do_not_hide_paths(self) -> None:
        """CITEPATH-EP-039: 反斜線跳脫或落單的反引號不影響其他路徑的抽取"""
        assert _cands("Use \\` then `scripts/missing.py`.") == ["scripts/missing.py"]
        assert _cands("- 用 ` 分隔\n- 修改 `scripts/missing.py`") == ["scripts/missing.py"]

    def test_citepath_ep_040_link_targets_are_always_checked(self) -> None:
        """CITEPATH-EP-040: 連結目標不套 owner/repo 略過；巢狀括號、query string、巢狀中括號都抽得到"""
        text = (
            "[a](docs/a(b(c)).md) [b](scripts/x.py?plain=1) [the [docs]](scripts/y.py) "
            "[c](docs/guide)"
        )
        cands = _cands(text)
        assert "docs/a(b(c)).md" in cands
        assert "scripts/y.py" in cands
        assert "docs/guide" in cands
        assert any(c.startswith("scripts/x.py") for c in cands)

    def test_citepath_ep_041_sentence_punctuation_is_stripped(self) -> None:
        """CITEPATH-EP-041: 句尾句點、冒號、粗體星號不算進路徑；`..` 不被剝掉"""
        assert _cands("See scripts/a.py. Also **scripts/b.py** and `scripts/..`:") == [
            "scripts/a.py",
            "scripts/b.py",
            "scripts/..",
        ]

    def test_citepath_ep_042_prose_emphasis_is_stripped_but_globs_kept(self) -> None:
        """CITEPATH-EP-042: 散文的粗體、斜體、刪除線與句尾問號會剝掉；緊貼 `/` 的星號是 glob，保留"""
        text = (
            "**a/one.md 過時** *a/two.md* ~~a/three.md~~ a/four.md? "
            "Read **a/five.md**. 例如 dir/* 與 **/x.md"
        )
        cands, skipped = check_cited_paths.extract_candidates(text, _index())
        assert cands == ["a/one.md", "a/two.md", "a/three.md", "a/four.md", "a/five.md", "**/x.md"]
        assert skipped == ["dir/*"]

    def test_citepath_ep_043_cjk_is_trimmed_only_at_token_edges(self) -> None:
        """CITEPATH-EP-043: 中文不是硬分隔——路徑內的中文保留，只剝頭尾且不緊貼 `/` 的中文"""
        text = "改 `docs/說明.md` 與 `skills/月報/SKILL.md`，另修改scripts/x.py後即可，見docs/說明"
        cands, skipped = check_cited_paths.extract_candidates(text, _index())
        assert cands == ["docs/說明.md", "skills/月報/SKILL.md", "scripts/x.py"]
        assert skipped == ["docs/說明"]

    def test_citepath_ep_044_markdown_escapes_are_restored(self) -> None:
        """CITEPATH-EP-044: markdown 反斜線跳脫先還原，`foo\\_bar.md` 不會被當成 shell 片段略過"""
        assert _cands("見 newdir/foo\\_bar.md 與 `a\\*b/c.md`") == ["newdir/foo_bar.md", "a*b/c.md"]

    def test_citepath_ep_045_skipped_token_promoted_when_later_seen_as_path(self) -> None:
        """CITEPATH-EP-045: 先以散文出現被略過的 token，之後在連結中出現時改為檢查"""
        cands, skipped = check_cited_paths.extract_candidates(
            "see foo/bar, then [x](foo/bar)", _index()
        )
        assert cands == ["foo/bar"]
        assert skipped == []

    @pytest.mark.parametrize("sep", ["|", ",", ";", "{", "}", '"', "'", "!", "=", "「", "，"])
    def test_citepath_ep_046_every_hard_separator_splits(self, sep: str) -> None:
        """CITEPATH-EP-046: 每個硬分隔字元都會切開 token，網址或其他字串不會把路徑黏住吞掉"""
        assert "scripts/missing.py" in _cands(f"https://x.com{sep}scripts/missing.py")

    def test_citepath_ep_047_code_context_by_either_adjacent_backtick(self) -> None:
        """CITEPATH-EP-047: 只有前面或只有後面緊貼反引號，都算程式碼語境（三段以上會檢查）"""
        assert _cands("`newdir/sub/tool --x`") == ["newdir/sub/tool"]
        assert _cands("`--x newdir/sub/tool`") == ["newdir/sub/tool"]
        assert _cands("<newdir/sub/tool x>") == ["newdir/sub/tool"]

    def test_citepath_ep_048_middle_segment_dot_counts_in_prose(self) -> None:
        """CITEPATH-EP-048: 散文中只有中段含點（`newdir/v1.2/name`）也看得出是路徑"""
        assert _cands("改 newdir/v1.2/name 即可") == ["newdir/v1.2/name"]

    def test_citepath_ep_049_only_listed_schemes_are_ignored(self) -> None:
        """CITEPATH-EP-049: 只有明列的 scheme 排除；`note:path` 這種前綴仍要檢查"""
        assert _cands("[m](mailto:a@b.c) [t](TEL:123) note:scripts/missing.py") == [
            "note:scripts/missing.py"
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "> [r]: newdir/foo",
            "- [r]: newdir/foo",
            "1. item\n\n    [r]: newdir/foo",
            "[a\\]b]: newdir/foo",
            "[r]:\tnewdir/foo",
            "[r]:\n\tnewdir/foo",
            "[r]:\n> newdir/foo",
            "  [r]: newdir/foo",
            '<a href="newdir/foo">x</a>',
            "<img src='newdir/foo'>",
        ],
        ids=[
            "blockquote",
            "list",
            "continuation",
            "escaped-label",
            "tab-after-colon",
            "tab-next-line",
            "blockquote-next-line",
            "indented",
            "href",
            "src",
        ],
    )
    def test_citepath_ep_050_reference_and_html_targets_are_link_targets(self, text: str) -> None:
        """CITEPATH-EP-050: 任何容器內的參考式定義與 HTML href/src 目標都當連結目標檢查"""
        cands, skipped = check_cited_paths.extract_candidates(text, _index())
        assert "newdir/foo" in cands
        assert "newdir/foo" not in skipped

    def test_citepath_ep_051_cjk_kept_in_code_and_links(self) -> None:
        """CITEPATH-EP-051: 反引號與連結內的中文是路徑本身，不剝；散文中第一段為中文也保留"""
        assert _cands("`新增scripts/x.py` `scripts/cron月報`") == [
            "新增scripts/x.py",
            "scripts/cron月報",
        ]
        assert _cands("[x](docs/說明) 見 說明/x.md") == ["說明/x.md", "docs/說明"]

    @pytest.mark.parametrize("esc", ["\\<", "\\>", "\\|", "\\~", "\\[", "\\!"])
    def test_citepath_ep_052_every_escape_range_is_restored(self, esc: str) -> None:
        """CITEPATH-EP-052: `_ESCAPE_RE` 每個字元範圍的跳脫都會還原，反斜線不會讓路徑被當成 shell 片段"""
        assert "newdir/x.md" in _cands(f"見 {esc}newdir/x.md{esc} 即可")

    def test_citepath_ep_053_single_tilde_is_not_home(self) -> None:
        """CITEPATH-EP-053: 只有 `~/` 開頭算家目錄；單一 `~` 的刪除線會剝掉後照常檢查"""
        assert _cands("已移除 ~newdir/x.md~ 與 `~/home.md`") == ["newdir/x.md"]

    def test_citepath_ep_054_absolute_link_and_shell_chars_in_link(self) -> None:
        """CITEPATH-EP-054: 以 `/` 開頭的連結目標視為 repo 根目錄起算；連結目標含 `&` 仍檢查"""
        assert _cands("[x](/newdir/guide.md) [y](newdir/a&b.md) [z](//cdn.x/y)") == [
            "newdir/guide.md",
            "newdir/a&b.md",
        ]

    def test_citepath_ep_055_remote_name_only_excludes_ref_shapes(self) -> None:
        """CITEPATH-EP-055: 第一段是 remote 名稱時，只在看不出是路徑時排除"""
        index = _index(files=("upstream/patch.md",), remotes=("upstream", "origin"))
        cands, _ = check_cited_paths.extract_candidates(
            "`upstream/missing.md` `origin/main` `origin/v1.2/x`", index
        )
        assert cands == ["upstream/missing.md", "origin/v1.2/x"]

    def test_citepath_ep_056_query_and_second_clean_pass(self) -> None:
        """CITEPATH-EP-056: 連結目標的 `?query` 會去掉；清理反覆套用到不再變化；`_` 強調也剝掉"""
        cands = _cands("[x](scripts/a.py?plain=1) see **scripts/b.py.** and _scripts/c.py_")
        assert cands == ["scripts/b.py", "scripts/c.py", "scripts/a.py"]

    def test_citepath_ep_057_bom_does_not_hide_declarations(self) -> None:
        """CITEPATH-EP-057: 以 BOM 開頭的文件，開頭區塊的宣告照常生效"""
        text = "﻿<!-- expected-absent: a/b.md -->\n\n內文 `a/b.md`\n"
        assert check_cited_paths.parse_expected_absent(text) == ["a/b.md"]
        assert _cands(text) == ["a/b.md"]

    def test_citepath_ep_058_declaration_block_uses_commonmark_line_breaks(self) -> None:
        """CITEPATH-EP-058: 宣告行後接 NEL 再接內文時不算獨立的宣告行，宣告不生效"""
        text = "<!-- expected-absent: newdir/x.md -->\x85See `newdir/x.md`\n"
        assert check_cited_paths.parse_expected_absent(text) == []


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
        assert self._status("scripts/../..") == "outside"
        assert self._status("./scripts/lint.py") == "ok"
        assert self._status("scripts/cron/../lint.py") == "ok"

    def test_citepath_rs_009_trailing_slash_glob_must_match_a_directory(self) -> None:
        """CITEPATH-RS-009: `scripts/*/` 須命中目錄；只有檔案 `scripts/lint.py` 時為 missing"""
        assert self._status("scripts/*/") == "ok"
        assert self._status("scripts/*/", ("scripts/lint.py",)) == "missing"

    def test_citepath_rs_010_question_mark_glob_matches_one_non_slash_char(self) -> None:
        """CITEPATH-RS-010: `?` 只比對一個非 `/` 字元，含斜線與單獨檔名都一樣"""
        assert self._status("scripts/lint.p?") == "ok"
        assert self._status("scripts?lint.py") == "missing"
        assert self._status("lint.p?") == "ok"
        assert self._status("lint.p?", ("a/lint.pyc",)) == "missing"


class TestLoadIndex:
    def test_citepath_li_001_only_tracked_files_count(self, tmp_path: Path) -> None:
        """CITEPATH-LI-001: 未追蹤與 gitignored 的檔案都不在 index"""
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

    def test_citepath_li_004_inherited_git_dir_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CITEPATH-LI-004: 繼承的 GIT_DIR 指向另一個 repo 時，仍讀 --repo 自己的 index"""
        repo = _make_repo(tmp_path / "repo", ("a.md",))
        other = _make_repo(tmp_path / "other", ("x.md",))
        monkeypatch.setenv("GIT_DIR", str(other / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(other))
        files = check_cited_paths.load_index(repo).files
        assert files == {"a.md"}


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
            "<!-- expected-absent: .mcp.json scheduled_tasks.json -->\n\n"
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
            tmp_path, "<!-- expected-absent: CLAUDE.md -->\n\n本 repo 沒有 `CLAUDE.md`\n"
        )
        assert rc == 1
        assert "[STALE-ABSENT] CLAUDE.md" in capsys.readouterr().out

    def test_citepath_mn_007_stale_absent_when_not_cited(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-007: 宣告的檔案存在但內文沒有用反引號引用，仍要 exit 1（AC-6）"""
        rc, _ = self._run(
            tmp_path, "<!-- expected-absent: CLAUDE.md -->\n\n本 repo 沒有 CLAUDE.md\n"
        )
        assert rc == 1
        assert "[STALE-ABSENT] CLAUDE.md" in capsys.readouterr().out

    def test_citepath_mn_008_only_declarations_absent_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-008: 只有宣告、宣告的都不存在時 exit 0（有檢查到東西，不是 exit 3）"""
        rc, _ = self._run(tmp_path, "<!-- expected-absent: .mcp.json -->\n\n實測無此檔\n")
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
        rc, _ = self._run(tmp_path, "`heyu-ai/yibi-stack` 的 `CLAUDE.md`，另見 newdir/sub/tool")
        assert rc == 0
        err = capsys.readouterr().err
        assert (
            "[SKIPPED] heyu-ai/yibi-stack（形似 owner/repo，未檢查；若是路徑請寫到檔名或加結尾斜線）"
            in err
        )
        assert (
            "[SKIPPED] newdir/sub/tool（散文中看不出是路徑，未檢查；若是路徑請用反引號包住）" in err
        )

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
            "<!-- expected-absent: SKILL.md -->\n\n沒有 SKILL.md\n",
            ("a/SKILL.md", "b/SKILL.md"),
        )
        assert rc == 1
        assert "[STALE-ABSENT] SKILL.md" in capsys.readouterr().out

    def test_citepath_mn_017_declared_and_cited_absent_path_is_waived(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-017: 唯一缺的引用已宣告 expected-absent 時 exit 0，且不印 [MISSING]"""
        body = "<!-- expected-absent: .mcp.json -->\n\n本 repo 無 `.mcp.json`，見 `CLAUDE.md`\n"
        rc, _ = self._run(tmp_path, body)
        assert rc == 0
        out = capsys.readouterr().out
        assert "[MISSING] .mcp.json" not in out
        assert "[ABSENT-OK] .mcp.json" in out

    def test_citepath_mn_018_outside_path_cannot_be_declared_absent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-018: 跳出 repo 的路徑不可用 expected-absent 放行，仍印 [OUTSIDE] 並 exit 1"""
        _make_repo(tmp_path / "sibling", ("x.md",))
        body = "<!-- expected-absent: ../sibling/x.md -->\n\n見 `../sibling/x.md` 與 `CLAUDE.md`\n"
        rc, _ = self._run(tmp_path, body)
        assert rc == 1
        out = capsys.readouterr().out
        assert "[OUTSIDE] ../sibling/x.md" in out
        assert "[ABSENT-OK]" not in out

    def test_citepath_mn_019_unclosed_fence_still_checks_rest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CITEPATH-MN-019: fence 未關閉時後文照常檢查，缺席路徑讓閘門 exit 1"""
        rc, _ = self._run(tmp_path, "見 `CLAUDE.md`\n```\n改 `scripts/missing.py`\n")
        assert rc == 1
        assert "[MISSING] scripts/missing.py" in capsys.readouterr().out

    @pytest.mark.parametrize("failure", ["ls-files-rc", "remote-rc", "timeout", "oserror"])
    def test_citepath_mn_020_git_failures_exit_two(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        failure: str,
    ) -> None:
        """CITEPATH-MN-020: rev-parse 之後的 git 呼叫失敗（非零、逾時、OSError）一律 exit 2"""
        repo = _make_repo(tmp_path / "repo")
        doc = _write(tmp_path / "doc.md", "`CLAUDE.md`")
        real_run = subprocess.run

        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> object:
            if failure == "ls-files-rc" and "ls-files" in cmd:
                return subprocess.CompletedProcess(cmd, 128, "", "fatal: boom")
            if failure == "remote-rc" and "remote" in cmd:
                return subprocess.CompletedProcess(cmd, 128, "", "fatal: boom")
            if failure == "timeout" and "ls-files" in cmd:
                raise subprocess.TimeoutExpired(cmd, 60)
            if failure == "oserror" and "remote" in cmd:
                raise OSError("git vanished")
            return real_run(cmd, *args, **kwargs)  # type: ignore[call-overload]

        monkeypatch.setattr(check_cited_paths.subprocess, "run", fake_run)
        assert check_cited_paths.main([str(doc), "--repo", str(repo)]) == 2
        assert "[FAIL]" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "body",
        [
            "見 `CLAUDE.md`\n執行 `python3\nscripts/missing.py --x`\n",
            "見 [說明][ref] 與 `CLAUDE.md`\n\n[ref]: docs/missing.md\n",
            "1. `CLAUDE.md`\n   ```bash\n   echo\n    ```\n2. 改 `scripts/missing.py`\n",
            "`tasks/nightly_agent/*/` 與 `CLAUDE.md`\n",
            "`Foo.app/Contents/Info.plist` 與 `CLAUDE.md`\n",
            "- 用 ` 分隔欄位\n- 修改 `scripts/missing.py`\n\n見 `CLAUDE.md`\n",
            "# 標題含 ` 符號\n修改 `scripts/missing.py`\n\n見 `CLAUDE.md`\n",
            "```markdown\n- item\n\n    ```\n    x\n    ```\n```\n\nSee `scripts/missing.py`.\n\n"
            "```bash\necho hi\n```\n\nAlso `CLAUDE.md`.\n",
            "`CLAUDE.md` [details](docs/a(b(c)).md)\n",
            "`CLAUDE.md` [details][ref]\n\n[ref]:\n  docs/missing.md\n",
            "See [the [docs]](scripts/missing.py) and `CLAUDE.md`.\n",
            "Use \\` then `scripts/missing.py`.\n\nSee `CLAUDE.md`.\n",
            "See [x](scripts/missing.py?plain=1) and `CLAUDE.md`.\n",
            "修改 scripts/missing.py 即可，見 `CLAUDE.md`\n",
            "Example: `\n<!-- expected-absent: docs/missing.md -->\n`\n\n`docs/missing.md` `CLAUDE.md`\n",
            "`CLAUDE.md`\n\n[details][ref]\n\n[ref]: missing.md\n",
            "`CLAUDE.md` [details](<newdir/foo>)\n",
            "`CLAUDE.md` [x]( newdir/foo )\n",
            "`CLAUDE.md` [x](\nnewdir/foo)\n",
            "`CLAUDE.md`\n\n[x][r]\n\n[r]:\n  newdir/foo\n",
            "```markdown\n\t```\n\tx\n\t```\n```\nSee `scripts/missing.py`.\n\n"
            "```bash\necho hi\n```\n\nAlso `CLAUDE.md`.\n",
            "See `CLAUDE.md`.\n\n- ```bash\n  run.sh\n  ```\n\nSee `newdir/sub/missing.md`.\n\n"
            "```bash\necho hi\n```\n",
            "`CLAUDE.md`\n\n   ```md\n      ```\n   ```\n\nSee `scripts/missing.py`.\n\n"
            "```bash\necho hi\n```\n",
            "See `CLAUDE.md`.\x85```\nSee `newdir/sub/missing.md`.\n```\n",
            "Declare like this:\n\n    <!-- expected-absent: scripts/missing.py -->\n\n"
            "Then edit `scripts/missing.py` and `CLAUDE.md`.\n",
            "`CLAUDE.md`\n\n**agent/drafter.py 已過時**\n",
            "`CLAUDE.md` Read *scripts/lint.p* now\n",
            "`CLAUDE.md` Is it scripts/lint.p? yes\n",
            "`CLAUDE.md` and ~~newdir/x.md~~ here\n",
            "`CLAUDE.md`\n\nnewdir/foo\\_bar.md\n",
            "改 `scripts/說明.md` 與 `CLAUDE.md`\n",
            "`CLAUDE.md`\n\n`新增scripts/lint.py`\n",
            "`CLAUDE.md` and `scripts/cron月報`\n",
            "`CLAUDE.md`\n\n> [details][r]\n>\n> [r]: newdir/guide\n",
            "`CLAUDE.md`\n\n- [r]: newdir/guide\n",
            "`CLAUDE.md` [g][a\\]b]\n\n[a\\]b]: newdir/guide\n",
            '`CLAUDE.md` <a href="newdir/sub/tool">tool</a>\n',
            "`CLAUDE.md` [x](/newdir/guide.md)\n",
        ],
        ids=[
            "wrapped-span",
            "reference-link",
            "list-fence",
            "dir-glob",
            "domain-like",
            "stray-backtick-list",
            "stray-backtick-heading",
            "fence-deep-closer",
            "nested-parens",
            "refdef-next-line",
            "nested-brackets",
            "escaped-backtick",
            "query-string",
            "prose-path",
            "decl-in-span",
            "refdef-bare-name",
            "angle-link",
            "spaced-link",
            "newline-link",
            "refdef-next-line-2seg",
            "tab-fence",
            "list-marker-fence",
            "indented-opener-fence",
            "nel-fence",
            "decl-in-indented-code",
            "unbalanced-bold",
            "italic-glob",
            "prose-question-glob",
            "strikethrough",
            "escaped-underscore",
            "cjk-in-path",
            "cjk-prefix-in-code",
            "cjk-suffix-in-code",
            "blockquote-refdef",
            "list-refdef",
            "escaped-label-refdef",
            "html-href",
            "absolute-link",
        ],
    )
    def test_citepath_mn_021_formerly_fail_open_shapes_now_exit_one(
        self, tmp_path: Path, body: str
    ) -> None:
        """CITEPATH-MN-021: 歷輪 review 重現的 fail-open 形狀，缺席路徑都要讓閘門 exit 1"""
        rc, _ = self._run(tmp_path, body)
        assert rc == 1

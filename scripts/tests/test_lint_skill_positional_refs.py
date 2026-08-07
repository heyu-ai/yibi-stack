"""lint_skill_positional_refs.py 的契約測試（issue #386；PR #387 mob review 後擴充）。

三層，各自守不同的東西：

1. **`scan_text()` 的逐行述詞** —— 哪些字面形式該報 / 不該報。
2. **fence 辨識** —— 哪些 fence 形狀算 shell。第一版用跨檔 regex，mob review 實測它同時
   漏報（`~~~bash` / info-string / `zsh` / 未閉合）與誤報（外層四反引號內的 ```bash 字面
   示例被當真 fence）。
3. **掃描面與聚合** —— `_targets()` 掃到誰、`scan_text()` 有沒有把每個 fence / 每個違規都
   累積、`main()` 的退出碼。第一版**整層沒測**：`pr-test-analyzer` 實跑 15 個突變，其中
   5 個存活（刪掉 `commands/*.md` 掃描面、只掃第一個 fence、只回報第一個違規、把排除規則
   的呼叫端改成絕對路徑、拿掉 symlink 去重）都是 24 個測試全綠。

**負向對照是重點測試，不是正向的那一條**——一個會對正確程式碼開火的 lint 會被人關掉，
於是等同不存在（rule 11 對 `lint_shell_subshell_exit.py` 已記載同一件事）。

斷言一律走純函式的合成輸入，不對真實檔案的當前內容斷言——真實檔案會漂移。

Test ID 規則見 .claude/rules/09-test-conventions.md（該 rule `paths:` 限 `tasks/**/tests/**`，
在此不會自動載入，故編號慣例在此以顯式引用維持）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lint_skill_positional_refs import (  # noqa: E402
    _MIN_SCAN_SURFACE,
    _is_excluded,
    _targets,
    main,
    scan_text,
)


def _fence(body: str, lang: str = "bash") -> str:
    return f"prose before\n\n```{lang}\n{body}\n```\n\nprose after\n"


# --------------------------------------------------------------------------- #
# 1. 逐行述詞：哪些字面形式該報
# --------------------------------------------------------------------------- #


class TestDetectsBarePositional:
    @pytest.mark.parametrize("n", list(range(10)))
    def test_lspr_dt_002_every_single_digit_is_flagged(self, n: int) -> None:
        """LSPR-DT-002: `$0`-`$9` 全數涵蓋

        `$0` 也必須擋：探針（Claude Code 2.1.218，`/probe ALPHA BETA GAMMA`）顯示
        positional binding 是 **0-based**，`$0` 渲染成第一個 argument token。而
        `SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)` 正是 rule 13 給讀者複製的形狀。
        """
        hits = scan_text(_fence(f'val="${n}"'))
        assert len(hits) == 1, f"${n} 未被偵測"

    def test_lspr_dt_003_line_number_points_at_the_offending_line(self) -> None:
        """LSPR-DT-003: 回報的行號必須指向違規行本身"""
        text = _fence('first_line=ok\nsecond_line=ok\nbad="$1"')
        hits = scan_text(text)
        assert len(hits) == 1
        assert text.splitlines()[hits[0][0] - 1].strip() == 'bad="$1"'

    def test_lspr_dt_007_double_dollar_is_a_real_defect_not_a_false_positive(self) -> None:
        """LSPR-DT-007: `$$1` 必須被擋——探針證明它是真缺陷

        mob review 曾建議加 `(?<!\\$)` 把 `$$1` 當成誤報排除（理由：bash 中 `$$1` 是
        `${PID}1`）。探針推翻了它：`/probe ALPHA BETA GAMMA` 下 `$$1` 渲染成 **`$BETA`**
        ——內層 `$1` 照樣被替換。加上那個 lookbehind 會開一個洞。
        """
        hits = scan_text(_fence("f=/tmp/x.$$1"))
        assert len(hits) == 1, "$$1 的內層 $1 會被 substitution 換掉，必須擋"


# --------------------------------------------------------------------------- #
# 負向對照：以下每一條都是「不得誤報」
# --------------------------------------------------------------------------- #


class TestDoesNotFalsePositive:
    def test_lspr_eg_001_braced_form_is_the_prescribed_fix(self) -> None:
        """LSPR-EG-001: `${N}` 是本 lint 建議的修法，絕對不能被自己報成違規"""
        assert scan_text(_fence('local key="${0}" type="${1}"')) == []

    def test_lspr_eg_002_escaped_form_is_also_valid(self) -> None:
        """LSPR-EG-002: 官方跳脫形式渲染為字面 `$N`，合法，不得誤報"""
        assert scan_text(_fence(r'local key="\$1"')) == []

    def test_lspr_eg_003_double_digit_is_not_substituted(self) -> None:
        """LSPR-EG-003: `$10` 以上實測不被替換

        原本此斷言的理由是從官方「digit」一詞**推論**而來。探針
        （`/probe ALPHA BETA GAMMA`）實測 `$10` -> `$10`、`$12` -> `$12`，claim 現在有依據。
        """
        assert scan_text(_fence('v="$10"')) == []
        assert scan_text(_fence('v="$12"')) == []

    def test_lspr_eg_004_outside_fence_is_not_scanned(self) -> None:
        """LSPR-EG-004: fence 外的 `$N` 屬散文層，不在本 lint 範圍"""
        text = '說明：呼叫時第一個參數是 $1。\n\n```bash\nv="${1}"\n```\n'
        assert scan_text(text) == []

    def test_lspr_eg_005_non_shell_fence_is_not_scanned(self) -> None:
        """LSPR-EG-005: 非 shell fence 的 `$1` 語意不同（jq / regex backreference 等）"""
        for lang in ("python", "json", "text", "jq"):
            assert scan_text(_fence('v = "$1"', lang=lang)) == [], f"{lang} fence 不該被掃"

    def test_lspr_eg_006_other_dollar_forms_are_not_flagged(self) -> None:
        """LSPR-EG-006: `$VAR` / `$@` / `$#` / `$?` 都不是位置參數"""
        body = 'v="$HOME"\nall="$@"\nn="$#"\nrc="$?"\narr="${arr[@]}"'
        assert scan_text(_fence(body)) == []

    def test_lspr_eg_007_arguments_placeholder_is_deliberately_allowed(self) -> None:
        """LSPR-EG-007: `$ARGUMENTS` 實測會被替換，但刻意放行

        它在 SKILL.md 內幾乎總是刻意使用（skill 就是要拿到引數），擋它會對正確用法開火。
        這是**已知未涵蓋**而非疏漏，docstring 有記錄。
        """
        assert scan_text(_fence('args="$ARGUMENTS"')) == []


# --------------------------------------------------------------------------- #
# 2. fence 辨識：第一版的 regex 同時漏報與誤報
# --------------------------------------------------------------------------- #


class TestFenceRecognition:
    @pytest.mark.parametrize("lang", ["bash", "sh", "zsh", "shell", "shell-session", "console"])
    def test_lspr_dt_004_all_shell_fence_languages_are_scanned(self, lang: str) -> None:
        """LSPR-DT-004: 六種 shell fence 標記都要掃（`zsh` / `shell-session` 為 mob review 補）"""
        assert len(scan_text(_fence('v="$1"', lang=lang))) == 1, f"```{lang} fence 未被掃描"

    def test_lspr_dt_008_info_string_metadata_does_not_hide_the_fence(self) -> None:
        """LSPR-DT-008: info string 只取第一個 token 判語言

        第一版 regex 在語言後緊接 `\\n`，任何 metadata（` ```bash title="x" `）都會讓整個
        fence 消失——同樣的 bug 藏在裡面照樣放行。
        """
        text = 'x\n\n```bash title="example"\nlocal key="$1"\n```\n'
        assert len(scan_text(text)) == 1

    def test_lspr_dt_009_tilde_fence_is_recognised(self) -> None:
        """LSPR-DT-009: `~~~bash` 是合法的 Markdown fence，同樣要掃"""
        text = 'x\n\n~~~bash\nlocal key="$1"\n~~~\n'
        assert len(scan_text(text)) == 1

    def test_lspr_eg_008_literal_fence_inside_a_longer_fence_is_not_scanned(self) -> None:
        """LSPR-EG-008: 外層較長分隔符內的 ```bash **字面示例**不得被當成真 fence

        這是誤報方向：一份講解 SKILL.md 寫法的文件，會用四反引號外層包住一個 ```bash
        字面例。第一版 regex 會匹配內層並把示例當成違規。狀態機以「同字元且長度 >= 開頭」
        判定關閉，內層較短的分隔符關不掉外層，故示例被正確留在外層內容裡。
        """
        text = 'x\n\n````text\n```bash\nv="$1"\n```\n````\n'
        assert scan_text(text) == []

    def test_lspr_dt_016_shorter_inner_delimiter_does_not_close_a_longer_fence(self) -> None:
        """LSPR-DT-016: 較短的分隔符不得關閉較長的外層 fence（CommonMark 語意）

        這條專門釘住 `len(delim) >= len(open_delim)` 那個條件，而**這個 fixture 換過兩次**
        ——本 PR 的突變驗證兩度發現前一版是等價突變：

        1. 初版外層用 `text`（非 shell），拿不拿掉長度檢查都不回報。
        2. 第二版外層改 shell、內層放 ```text，但 Round 2 加上「closing fence 不得帶
           info string」之後，那個 fixture 已改由 info-string 條件擋住，長度檢查再次冗餘。

        現在的 fixture 讓**裸的** ``` （無 info string，故通過 info 條件）出現在較長的
        ````bash 內：只有長度檢查能阻止它提前關閉外層。拿掉後 `more="$2"` 會逃出掃描面。
        """
        text = 'x\n\n````bash\nv="$1"\n```\nmore="$2"\n````\n'
        hits = scan_text(text)
        assert len(hits) == 2, "較短的裸分隔符不得關閉較長的外層 fence（CommonMark）"
        assert [h[1].strip() for h in hits] == ['v="$1"', 'more="$2"']

    def test_lspr_dt_017_info_string_line_does_not_close_a_fence(self) -> None:
        """LSPR-DT-017: 帶 info string 的行不得關閉 fence（CommonMark；Round 2 Critical）

        Round 2 由 codex 與 agy 各自命中、lead 重現：狀態機原本拿**開頭**的 pattern 兼作
        結尾判定，於是 ` ```text ` 會關掉等長的 ```bash fence，後續 shell 內容整段逃出掃描
        面——fail-open。
        """
        text = '```bash\necho ok\n```text\nbad="$1"\n```\n'
        hits = scan_text(text)
        assert len(hits) == 1, "帶 info string 的行不是合法的 closing fence"
        assert hits[0][1].strip() == 'bad="$1"'

    def test_lspr_dt_018_heredoc_literal_fence_does_not_close(self) -> None:
        """LSPR-DT-018: heredoc 內的字面 ```bash 同樣不得關閉外層 fence（Round 2 Critical 變體）"""
        text = "```bash\ncat << 'EOF'\n```bash\nv=\"$1\"\n```\nEOF\n```\n"
        assert len(scan_text(text)) == 1

    def test_lspr_eg_010_indented_code_block_is_not_a_fence(self) -> None:
        """LSPR-EG-010: 縮排 >= 4 空格是 indented code block，不是 fence（Round 2 Critical）

        誤報方向：一份用縮排展示 fence 寫法的文件會被整段誤掃。CommonMark 只允許 0-3 空格
        的 fence 縮排。
        """
        text = 'text:\n\n    ```bash\n    value="$1"\n    ```\n'
        assert scan_text(text) == []

    def test_lspr_dt_019_double_backslash_before_dollar_is_not_escaped(self) -> None:
        """LSPR-DT-019: `\\\\$1`（字面反斜線 + `$1`）必須被擋（Round 2 Important）

        單字元 lookbehind `(?<!\\\\)` 只看前一個字元，會把 `\\\\$1` 誤判為已跳脫而放行，
        但 `$1` 照樣被替換。改為在 Python 端數反斜線奇偶。
        """
        assert len(scan_text('```bash\nv="\\\\$1"\n```\n')) == 1
        # 對照：奇數個反斜線才是真的跳脫
        assert scan_text('```bash\nv="\\$1"\n```\n') == []
        assert len(scan_text('```bash\nv="\\\\\\\\$1"\n```\n')) == 1

    def test_lspr_dt_010_unclosed_shell_fence_is_still_scanned(self) -> None:
        """LSPR-DT-010: 未閉合的 shell fence 要掃到檔尾，不是靜默跳過整段"""
        text = 'x\n\n```bash\nlocal key="$1"\n'
        assert len(scan_text(text)) == 1

    def test_lspr_eg_009_inline_backticks_do_not_truncate_the_fence(self) -> None:
        """LSPR-EG-009: 行內三反引號不得提前關閉 fence

        第一版的結束分隔符未錨定行首，`echo '```'` 之後的內容整段逃掉。
        """
        text = "x\n\n```bash\necho 'a```b'\nlocal key=\"$1\"\n```\n"
        assert len(scan_text(text)) == 1


# --------------------------------------------------------------------------- #
# 3. 聚合：每個 fence、每個違規都要累積（第一版此層全無測試，M3/M4 存活）
# --------------------------------------------------------------------------- #


class TestAggregation:
    def test_lspr_dt_011_violation_in_a_later_fence_is_found(self) -> None:
        """LSPR-DT-011: 不是只掃第一個 fence

        存活突變 M3（`list(_FENCE.finditer(text))[:1]`）24 測試全綠。實測 43/59 個現有目標
        有多個 ```bash fence，屬主流形狀而非邊緣案例。
        """
        text = 'x\n\n```bash\nclean=1\n```\n\ny\n\n```bash\nbad="$1"\n```\n'
        hits = scan_text(text)
        assert len(hits) == 1
        assert hits[0][1].strip() == 'bad="$1"'

    def test_lspr_dt_012_multiple_violations_in_one_fence_are_all_reported(self) -> None:
        """LSPR-DT-012: 同一個 fence 內的每個違規都要回報

        存活突變 M4（`return violations[:1]`）24 測試全綠，`main()` 的「共 N 處」會少算。
        """
        text = 'x\n\n```bash\na="$1"\nb="$2"\n```\n'
        assert len(scan_text(text)) == 2


# --------------------------------------------------------------------------- #
# 4. 掃描面：排除規則、檔案類別、去重
# --------------------------------------------------------------------------- #


class TestScanSurface:
    def test_lspr_dt_005_exclusion_is_relative_not_absolute_substring(self) -> None:
        """LSPR-DT-005: 排除以「相對於掃描根」判斷，不可拿絕對路徑做子字串比對

        在 linked worktree 內執行時，repo 根本身就是 `<main>/.claude/worktrees/<name>`。
        用絕對路徑子字串排除的話，每個檔案都會被跳過，掃描面歸零而 lint 照樣回報乾淨。
        """
        assert _is_excluded(Path(".claude/worktrees/foo/SKILL.md")) is True
        assert _is_excluded(Path("plugins/cache/x/SKILL.md")) is True
        assert _is_excluded(Path("plugins/growth/skills/x/SKILL.md")) is False
        assert _is_excluded(Path("skills/x/SKILL.md")) is False

    def test_lspr_dt_013_exclusion_is_applied_to_the_relative_path(self, tmp_path: Path) -> None:
        """LSPR-DT-013: `_targets()` 必須把**相對**路徑餵給 `_is_excluded`

        存活突變 M2（改傳絕對路徑）讓排除變成 no-op，24 測試全綠。`LSPR-DT-006` 對它結構性
        失明，因為 M2 讓掃描面**變大**而該斷言是「不得過小」。這裡改用「被排除的檔案不得
        出現在結果裡」正面斷言。
        """
        (tmp_path / ".claude" / "worktrees" / "wt").mkdir(parents=True)
        (tmp_path / ".claude" / "worktrees" / "wt" / "SKILL.md").write_text("x", encoding="utf-8")
        (tmp_path / "skills" / "real").mkdir(parents=True)
        (tmp_path / "skills" / "real" / "SKILL.md").write_text("x", encoding="utf-8")

        names = {str(p.relative_to(tmp_path)) for p in _targets(tmp_path)}
        assert names == {"skills/real/SKILL.md"}

    def test_lspr_dt_014_both_declared_file_classes_are_in_scope(self, tmp_path: Path) -> None:
        """LSPR-DT-014: `SKILL.md` 與 `commands/*.md` 兩類都要掃

        存活突變 M1（刪 `or "commands" in path.parts`）讓目標從 59 掉到 44——`commands/*.md`
        佔 25% 掃描面卻零覆蓋，24 測試全綠。M15（限定 `plugins` 路徑）同理。
        """
        (tmp_path / "skills" / "a").mkdir(parents=True)
        (tmp_path / "skills" / "a" / "SKILL.md").write_text("x", encoding="utf-8")
        (tmp_path / "commands").mkdir()
        (tmp_path / "commands" / "foo.md").write_text("x", encoding="utf-8")
        (tmp_path / "plugins" / "p" / "commands").mkdir(parents=True)
        (tmp_path / "plugins" / "p" / "commands" / "bar.md").write_text("x", encoding="utf-8")
        (tmp_path / "README.md").write_text("x", encoding="utf-8")

        names = {str(p.relative_to(tmp_path)) for p in _targets(tmp_path)}
        assert names == {
            "skills/a/SKILL.md",
            "commands/foo.md",
            "plugins/p/commands/bar.md",
        }, "兩個宣告的檔案類別都必須在掃描面內，且不得掃到一般 .md"

    def test_lspr_dt_015_symlinked_duplicates_are_deduplicated(self, tmp_path: Path) -> None:
        """LSPR-DT-015: 指向同一實體檔案的 symlink 不得被回報兩次

        存活突變 M13（`seen.add(path)`）24 測試全綠。repo-root 的 `commands/*.md` 多為指向
        `plugins/*/commands/*.md` 的 symlink，不去重會讓 `total` 灌水。
        """
        (tmp_path / "plugins" / "p" / "commands").mkdir(parents=True)
        real = tmp_path / "plugins" / "p" / "commands" / "x.md"
        real.write_text("x", encoding="utf-8")
        (tmp_path / "commands").mkdir()
        (tmp_path / "commands" / "x.md").symlink_to(real)

        assert len(_targets(tmp_path)) == 1

    def test_lspr_dt_006_real_checkout_surface_is_above_the_floor(self) -> None:
        """LSPR-DT-006: 真實 checkout 的掃描面必須高於下限

        「gate 有沒有真的在看東西」與「看到的東西乾不乾淨」是兩件事。少了這條，一個把自己
        掃成空集合的 lint 會永遠是綠的。
        """
        assert len(_targets(REPO_ROOT)) >= _MIN_SCAN_SURFACE


# --------------------------------------------------------------------------- #
# 5. main() 的退出碼契約（第一版完全未測，M「return 1 -> return 0」存活）
# --------------------------------------------------------------------------- #


def _make_tree(root: Path, skill_body: str) -> None:
    """造一棵剛好高於掃描面下限的樹，第一個 SKILL.md 帶指定內容。"""
    for i in range(_MIN_SCAN_SURFACE + 1):
        d = root / "skills" / f"s{i}"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(skill_body if i == 0 else "clean\n", encoding="utf-8")


class TestMainExitContract:
    def test_lspr_st_002_clean_tree_exits_zero_and_reports_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LSPR-ST-002: 乾淨的樹 exit 0，且 stdout 印出掃描檔數讓綠燈可被證偽"""
        _make_tree(tmp_path, "clean\n")
        monkeypatch.chdir(tmp_path)
        assert main([]) == 0
        assert str(_MIN_SCAN_SURFACE + 1) in capsys.readouterr().out

    def test_lspr_st_003_violation_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LSPR-ST-003: 有違規 exit 1

        存活突變：把 `return 1` 改成 `return 0`，第一版 24 個測試全綠，hook 變成 fail-open。
        sibling 慣例（`test_lint_skill_scope.py` / `test_lint_rule_frontmatter.py` /
        `test_lint_skill_overlap.py`）都有 `assert main() == 1`。
        """
        _make_tree(tmp_path, '```bash\nlocal key="$1"\n```\n')
        monkeypatch.chdir(tmp_path)
        assert main([]) == 1
        assert "[FAIL]" in capsys.readouterr().err

    def test_lspr_st_004_empty_scan_surface_exits_two_not_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LSPR-ST-004: 掃描面塌陷 exit 2，不是回報乾淨

        第一版在此情境印零輸出、exit 0——「乾淨」與「什麼都沒掃」無法區分。這正是本 PR
        宣稱修好的那個失敗形狀，卻在 gate 自己身上重演。
        """
        (tmp_path / "empty").mkdir()
        monkeypatch.chdir(tmp_path)
        assert main([]) == 2
        assert "掃描面" in capsys.readouterr().err

    def test_lspr_st_005_unreadable_file_exits_two_not_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LSPR-ST-005: 讀取失敗 exit 2，與「發現違規」的 exit 1 分開

        rule 13「`|| exit 0` / `|| true` Turns a Real Result Into a Silent Skip」要編碼的區別
        正是「failed to run」vs「ran and found something」；共用同一個退出碼會讓呼叫端分不出來。
        """
        missing = tmp_path / "nope" / "SKILL.md"
        assert main([str(missing)]) == 2
        assert "無法讀取" in capsys.readouterr().err

    def test_lspr_st_007_invalid_utf8_exits_two_not_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LSPR-ST-007: 非 UTF-8 檔案 exit 2，不是讓 UnicodeDecodeError 逸出（Round 2 Important）

        `read_text(encoding="utf-8")` 對含 `0xff` 的檔案丟 `UnicodeDecodeError`——那是
        `ValueError` 不是 `OSError`，只接 `OSError` 會讓它逸出成 traceback 並以 exit 1 結束，
        把工具失敗混進「發現違規」。
        """
        bad = tmp_path / "SKILL.md"
        bad.write_bytes(b"```bash\nv=\xff\n```\n")
        assert main([str(bad)]) == 2
        assert "無法讀取" in capsys.readouterr().err

    def test_lspr_st_008_fix_advice_is_printed_even_when_reads_fail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LSPR-ST-008: 同時有讀取失敗與違規時，修法建議仍要印出（Round 2 NIT）

        原本 `if read_errors: return 2` 排在建議之前，使用者只看到讀取失敗、拿不到怎麼修。
        """
        good = tmp_path / "SKILL.md"
        good.write_text('```bash\nv="$1"\n```\n', encoding="utf-8")
        missing = tmp_path / "nope" / "SKILL.md"

        assert main([str(missing), str(good)]) == 2
        err = capsys.readouterr().err
        assert "braced form" in err, "有違規時修法建議不得因讀取失敗而被吞掉"
        assert "無法讀取" in err

    def test_lspr_st_006_unreadable_file_does_not_abort_the_scan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LSPR-ST-006: 一個檔案讀不到，後面的檔案仍要被掃

        第一版在迴圈內 `return 1`，後面的檔案完全沒被看過。
        """
        good = tmp_path / "SKILL.md"
        good.write_text('```bash\nlocal key="$1"\n```\n', encoding="utf-8")
        missing = tmp_path / "nope" / "SKILL.md"

        assert main([str(missing), str(good)]) == 2
        err = capsys.readouterr().err
        assert "無法讀取" in err
        assert "SKILL.md:2" in err, "讀取失敗不得中止掃描，後續檔案的違規仍須回報"

    def test_lspr_st_001_repo_is_clean(self) -> None:
        """LSPR-ST-001: 真實 repo 零違規（煙霧測試，會隨檔案內容漂移）"""
        offenders: list[str] = []
        for path in _targets(REPO_ROOT):
            for line_no, line in scan_text(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")
        assert offenders == [], "shell fence 內仍有裸位置參數：\n" + "\n".join(offenders)

"""lint_skill_positional_refs.py 的契約測試（issue #386）。

**負向對照是這裡的重點測試，不是正向的那一條。** 一個會對正確程式碼開火的 lint 會被人
關掉，於是等同不存在——rule 11 對 `lint_shell_subshell_exit.py` 已記載同一件事。所以
`${N}`、`\\$N`、`$10`、fence 外的 `$N`、非 shell fence 的 `$N` 各有一個「不得誤報」的案例。

斷言一律走純函式 `scan_text()` 的合成輸入，不對真實檔案的當前內容斷言——真實檔案會漂移，
合成輸入才是可靠的對照。真實檔案只用在「repo 現況乾淨」那一條煙霧測試上。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lint_skill_positional_refs import _is_excluded, _targets, scan_text  # noqa: E402


def _fence(body: str, lang: str = "bash") -> str:
    return f"prose before\n\n```{lang}\n{body}\n```\n\nprose after\n"


# --------------------------------------------------------------------------- #
# 正向：真正的違規必須被抓到
# --------------------------------------------------------------------------- #


class TestDetectsBarePositional:
    def test_lspr_dt_001_bare_dollar_one_is_flagged(self) -> None:
        """LSPR-DT-001: shell fence 內的裸 $1 是違規（issue #386 的實際 bug 形狀）"""
        hits = scan_text(_fence('local key="$1" type="$2"'))
        assert len(hits) == 1
        assert "$1" in hits[0][1]

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8, 9])
    def test_lspr_dt_002_every_single_digit_is_flagged(self, n: int) -> None:
        """LSPR-DT-002: $1-$9 全數涵蓋

        逐一參數化而非只測 $1：官方 substitution 的作用對象是單一數字，漏掉任何一個
        都會讓那個位置靜默逃過。
        """
        hits = scan_text(_fence(f'val="${n}"'))
        assert len(hits) == 1, f"${n} 未被偵測"

    def test_lspr_dt_003_line_number_points_at_the_offending_line(self) -> None:
        """LSPR-DT-003: 回報的行號必須指向違規行本身，否則使用者要自己找"""
        body = 'first_line=ok\nsecond_line=ok\nbad="$1"'
        text = _fence(body)
        hits = scan_text(text)
        assert len(hits) == 1
        line_no = hits[0][0]
        assert text.splitlines()[line_no - 1].strip() == 'bad="$1"'

    @pytest.mark.parametrize("lang", ["bash", "sh", "shell", "console"])
    def test_lspr_dt_004_all_shell_fence_languages_are_scanned(self, lang: str) -> None:
        """LSPR-DT-004: 四種 shell fence 標記都要掃，否則換個標記就繞過"""
        hits = scan_text(_fence('v="$1"', lang=lang))
        assert len(hits) == 1, f"```{lang} fence 未被掃描"


# --------------------------------------------------------------------------- #
# 負向對照：以下每一條都是「不得誤報」——這些才是這個 lint 能不能活下來的關鍵
# --------------------------------------------------------------------------- #


class TestDoesNotFalsePositive:
    def test_lspr_eg_001_braced_form_is_the_prescribed_fix(self) -> None:
        """LSPR-EG-001: ${N} 是本 lint 建議的修法，絕對不能被自己報成違規

        這條若紅，lint 會把照著它的建議修好的檔案再次擋下來——直接摧毀它的可信度。
        """
        assert scan_text(_fence('local key="${1}" type="${2}"')) == []

    def test_lspr_eg_002_escaped_form_is_also_valid(self) -> None:
        """LSPR-EG-002: 跳脫形式已探針確認渲染為字面 $N，是合法寫法，不得誤報

        本 repo 建議 ${N}（原始檔可直接複製），但 \\$N 並非錯誤，lint 不該替使用者
        做風格裁決。
        """
        assert scan_text(_fence(r'local key="\$1"')) == []

    def test_lspr_eg_003_double_digit_is_not_flagged(self) -> None:
        """LSPR-EG-003: $10 以上不在 substitution 作用範圍，且不可從中切出 $1 誤報"""
        assert scan_text(_fence('v="$10"')) == []
        assert scan_text(_fence('v="$12"')) == []

    def test_lspr_eg_004_outside_fence_is_not_scanned(self) -> None:
        """LSPR-EG-004: fence 外的 $N 屬散文層，不在本 lint 範圍

        散文裡寫 `$1` 說明用法是正常的；把它一併擋掉會讓 lint 對正確文件開火。
        """
        text = '說明：呼叫時第一個參數是 $1，第二個是 $2。\n\n```bash\nv="${1}"\n```\n'
        assert scan_text(text) == []

    def test_lspr_eg_005_non_shell_fence_is_not_scanned(self) -> None:
        """LSPR-EG-005: 非 shell fence 的 $1 語意不同（jq / regex backreference 等）"""
        for lang in ("python", "json", "text", "jq"):
            assert scan_text(_fence('v = "$1"', lang=lang)) == [], f"{lang} fence 不該被掃"

    def test_lspr_eg_006_other_dollar_forms_are_not_flagged(self) -> None:
        """LSPR-EG-006: $VAR / $@ / $# / $? 都不是位置參數，不得誤報"""
        body = 'v="$HOME"\nall="$@"\nn="$#"\nrc="$?"\narr="${arr[@]}"'
        assert scan_text(_fence(body)) == []


# --------------------------------------------------------------------------- #
# 掃描面：排除規則不可讓整個掃描面歸零
# --------------------------------------------------------------------------- #


class TestScanSurface:
    def test_lspr_dt_005_exclusion_is_relative_not_absolute_substring(self) -> None:
        """LSPR-DT-005: 排除以「相對於掃描根」判斷，不可拿絕對路徑做子字串比對

        在 linked worktree 內執行時，repo 根本身就是 `<main>/.claude/worktrees/<name>`。
        用絕對路徑子字串排除的話，**每一個**檔案都會被跳過，掃描面歸零而 lint 照樣回報
        乾淨——這是本檔第一版的實際 bug，由正向對照（把 SKILL.md 還原成壞形狀，lint 竟
        放行）抓到。rule 11 對 assert_not_worktree.sh 已記載同一類錯誤。
        """
        # 相對路徑在被排除目錄底下 -> 排除
        assert _is_excluded(Path(".claude/worktrees/foo/SKILL.md")) is True
        assert _is_excluded(Path("plugins/cache/x/SKILL.md")) is True
        # 一般路徑 -> 不排除，即使它的絕對路徑可能位於某個 worktree 內
        assert _is_excluded(Path("plugins/growth/skills/x/SKILL.md")) is False
        assert _is_excluded(Path("skills/x/SKILL.md")) is False

    def test_lspr_dt_006_scan_surface_is_not_empty_in_this_checkout(self) -> None:
        """LSPR-DT-006: 掃描面不得為空——空掃描面的「零違規」沒有資訊量

        這條是對「gate 有沒有真的在看東西」的斷言，與「看到的東西乾不乾淨」分開。
        少了它，一個把自己掃成空集合的 lint 會永遠是綠的。
        """
        targets = _targets(REPO_ROOT)
        assert len(targets) > 20, (
            f"掃描面只有 {len(targets)} 個檔案，疑似排除規則過寬導致掃描面塌陷"
        )
        names = {t.name for t in targets}
        assert "SKILL.md" in names


# --------------------------------------------------------------------------- #
# 煙霧測試：repo 現況
# --------------------------------------------------------------------------- #


def test_lspr_st_001_repo_is_clean_after_the_fix() -> None:
    """LSPR-ST-001: 修完之後 repo 內應為零違規

    這條是煙霧測試而非契約——它會隨檔案內容漂移。真正的行為斷言在上面的合成輸入。
    """
    # 刻意呼叫 _targets() 而不是自己重寫一次 traversal。第一版就是在這裡複製了掃描邏輯，
    # 於是 script 的排除 bug 修好之後，測試裡的那份副本仍帶著同一個 bug——lint 已擋下壞輸入，
    # 這條測試卻還是綠的。單一實作是唯一能讓兩者不分岔的方式。
    offenders: list[str] = []
    for path in _targets(REPO_ROOT):
        for line_no, line in scan_text(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")
    assert offenders == [], "shell fence 內仍有裸位置參數：\n" + "\n".join(offenders)

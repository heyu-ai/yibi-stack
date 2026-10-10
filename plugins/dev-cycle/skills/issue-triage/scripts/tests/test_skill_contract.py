"""SKILL.md 文字契約測試（change: add-issue-triage-staleness-review）。

OBSOLETE、STALE-CANDIDATE、過期分層、豁免、寬限期、優先級這些規則，執行者是「讀 runbook 的 agent」，
pytest 無法驗證它在任意未來的 issue 上會不會遵守。這份測試只做 `[doc]` 層：斷言 runbook **有明文寫**
這條規則，並防止有人「順手」改掉（例如把新的優先序改回舊的、把 FAQ 的「降優先」寫回來）。

讀者不得把這裡的 PASS 誤讀為行為證明；執行期行為列在 testplan.md 的 Manual Verification。

每個測試以 docstring 的 `spec:`／`tc:` 行綁定到 testplan 的 TC。自檢：`ITS-EG-014` 對每個錨點做突變
（把它從文字中移除），斷言檢查器會變紅；一個永遠回報「沒問題」的檢查器在這裡會被抓到。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[2] / "SKILL.md"

# 錨點以「單一職責」分組；key 對應 testplan 的 TC。字串必須與 SKILL.md 逐字相同。
ANCHORS: dict[str, list[str]] = {
    "ITS-DT-001": [
        "包含只盤點 Jira bug",
        "bash ~/.agents/skills/issue-triage/scripts/check-baseline.sh",
        "不要回退到本機的 origin/main",
    ],
    "ITS-DT-002": [
        "## 證據基準",
        "origin/main@<BASELINE_SHA 完整 40 字元>",
    ],
    "ITS-DT-003": [
        "`close-<n>.md` 最後一行必須是 `<!-- issue-triage:close <今天日期> -->`",
        "`update-<n>.md` 最後一行必須是 `<!-- issue-triage:update-scope <今天日期> -->`",
        "`merge-<b>.md` 最後一行必須是 `<!-- issue-triage:merge <今天日期> -->`",
        "`stale-<n>.md` 最後一行必須是 `<!-- issue-triage:stale-notice <今天日期> -->`",
        "另一個帳號貼出的標記一律算人為活動",
    ],
    "ITS-DT-004": [
        "| 0 | 少於 30 天 |",
        "| 1 | 30 到 89 天 |",
        "| 2 | 90 到 179 天 |",
        "| 3 | 180 天以上 |",
        "29 天是 tier 0、30 天是 tier 1、89 天是 tier 1、"
        "90 天是 tier 2、179 天是 tier 2、180 天是 tier 3",
        "**都生效**",
        "premise-unverified",
        "KEEP 必須引用「前提仍成立」的正向證據",
    ],
    "ITS-DT-005": [
        "**OBSOLETE 的證據標準**",
        "零命中的搜尋沒有資訊量",
        "必須有**正向對照**",
        "該症狀的結論是 UNCLEAR，**不構成 OBSOLETE**",
        "只有**部分**未解症狀失去前提時，verdict 是 UPDATE-SCOPE",
        "建議關閉原因一律是 `not planned`",
    ],
    "ITS-DT-006": [
        "寬限期 **14 天**",
        "已辨識的 stale notice",
        "notice 之後沒有實質人為活動",
        "**絕不**：僅憑天數建議關閉",
        "**寫入前必須重新呼叫** `last-human-activity.sh",
        "有新活動就放棄這筆",
    ],
    "ITS-DT-007": [
        "`assignees` 非空",
        "`dueOn` 為 null 的 milestone 沒有期限，不豁免",
        "OWNER、MEMBER 或 COLLABORATOR",
        "路人（NONE、CONTRIBUTOR 等）的 keep-open 留言不構成豁免",
        "有 security 相關 label",
    ],
    "ITS-DT-008": [
        "**MERGE > CLOSE > OBSOLETE > UPDATE-SCOPE > STALE-CANDIDATE > KEEP**",
    ],
    "ITS-DT-009": [
        "久未更新不降低優先級",
        "review-urgency: <N> 天無人為活動",
        "不影響「做這件事有多急」",
    ],
    "ITS-DT-010": [
        "排程與 webhook 情境即使看到 STALE-CANDIDATE 也只進報告、不貼任何留言",
        "只在 `--apply` 且逐項確認後才執行",
        "**無互動確認者（排程 / webhook）即使帶 `--apply` 也不執行寫入**",
    ],
    "ITS-DT-011": [
        "Jira bug 不適用本節",
        "（僅 GitHub issue）",
    ],
    "ITS-DT-012": [
        "過期檢視不可用",
        "不得升為 STALE-CANDIDATE 或 OBSOLETE",
        "不要當成「有人為活動」",
    ],
    "ITS-DT-013": [
        "多半是 issue 寫錯路徑",
        "`NOT_APPLICABLE`",
        "**「沒有漂移訊號」與「不適用」都不是前提仍成立的證據**",
        "**不是**消失的證據",
    ],
}

# 舊版措辭：任何一個出現在 SKILL.md 就代表有人把已被推翻的規則寫回來
FORBIDDEN: list[str] = [
    "MERGE > CLOSE > UPDATE-SCOPE > KEEP",
    "KEEP 並降優先",
    "長期無活動 |",
]


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _missing(text: str, tc_id: str) -> list[str]:
    return [a for a in ANCHORS[tc_id] if a not in text]


def _forbidden_hits(text: str) -> list[str]:
    return [f for f in FORBIDDEN if f in text]


def _section(text: str, start: str, end: str) -> str:
    """取 start 標題到 end 標題之間的文字；任一標題不存在就讓測試明確失敗。"""
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


class TestSkillContract:
    def test_its_dt_001_baseline_runs_before_any_code_verification(self) -> None:
        """Step 1c 在 Step 2 之前，且 Jira-only 與單一項目執行同樣適用。

        spec: issue-triage-evidence-baseline#jira-only-run
        tc: ITS-DT-001
        """
        text = _skill_text()
        assert _missing(text, "ITS-DT-001") == []
        assert text.index("check-baseline.sh") < text.index("## Step 2")
        for code in range(6):
            assert f"\n| {code} | " in _section(text, "### 1c.", "## Step 2")

    def test_its_dt_002_report_header_records_the_baseline(self) -> None:
        """報告模板的第一個區塊是證據基準，且在「來源」之前。

        spec: issue-triage-evidence-baseline#report-header
        tc: ITS-DT-002
        """
        text = _skill_text()
        assert _missing(text, "ITS-DT-002") == []
        report = _section(text, "# Issue Triage -- <repo slug>", "若 `$OUT` 落在")
        assert report.index("## 證據基準") < report.index("## 來源")

    def test_its_dt_003_every_comment_template_carries_the_marker(self) -> None:
        """8a、8b、8d、8i 各自明寫標記，另一帳號貼出的標記算人為活動。

        spec: issue-triage-staleness-review#closing-note-carries-the-marker
        spec: issue-triage-staleness-review#scope-update-carries-the-marker
        tc: ITS-DT-003
        """
        assert _missing(_skill_text(), "ITS-DT-003") == []

    def test_its_dt_004_tier_table_and_boundaries(self) -> None:
        """分層表四列、邊界整數判定、fast 與 deep 都生效、premise-unverified。

        spec: issue-triage-staleness-review#tier-2-keep-requires-affirmative-evidence
        spec: issue-triage-staleness-review#tier-2-keep-without-affirmative-evidence-is-flagged
        spec: issue-triage-staleness-review#tier-1-collects-drift-only
        tc: ITS-DT-004
        """
        assert _missing(_skill_text(), "ITS-DT-004") == []

    def test_its_dt_005_obsolete_needs_a_positive_control(self) -> None:
        """OBSOLETE 的證據標準：零命中不是證據、需要正向對照、部分失去前提是 UPDATE-SCOPE。

        spec: issue-triage-staleness-review#premise-artifacts-removed-with-positive-control
        spec: issue-triage-staleness-review#zero-hits-without-positive-control
        spec: issue-triage-staleness-review#partial-loss-of-premise
        tc: ITS-DT-005
        """
        assert _missing(_skill_text(), "ITS-DT-005") == []

    def test_its_dt_006_stale_candidate_grace_period_state_machine(self) -> None:
        """寬限期 14 天、notice 之後無人為活動才建議關閉、寫入前重新量測、絕不僅憑天數。

        spec: issue-triage-staleness-review#first-stale-candidate
        spec: issue-triage-staleness-review#grace-period-elapsed-without-response
        spec: issue-triage-staleness-review#human-responds-during-grace-period
        spec: issue-triage-staleness-review#age-alone-never-closes
        spec: issue-triage-staleness-review#reply-arrives-between-the-verdict-and-the-write
        tc: ITS-DT-006
        """
        assert _missing(_skill_text(), "ITS-DT-006") == []

    def test_its_dt_007_exemptions(self) -> None:
        """五種豁免；dueOn 為 null 的 milestone 不豁免；路人的 keep-open 不構成豁免。

        spec: issue-triage-staleness-review#assigned-issue-is-exempt
        spec: issue-triage-staleness-review#keep-open-comment-from-a-non-maintainer
        tc: ITS-DT-007
        """
        assert _missing(_skill_text(), "ITS-DT-007") == []

    def test_its_dt_008_verdict_precedence(self) -> None:
        """新優先序在場，舊的三段優先序不得出現。

        spec: issue-triage-staleness-review#all-symptoms-done-and-premise-also-gone
        spec: issue-triage-staleness-review#duplicate-of-another-issue-and-stale
        tc: ITS-DT-008
        """
        text = _skill_text()
        assert _missing(text, "ITS-DT-008") == []
        assert "MERGE > CLOSE > UPDATE-SCOPE > KEEP" not in text

    def test_its_dt_009_inactivity_does_not_lower_priority(self) -> None:
        """久未更新不降優先、改標 review-urgency；FAQ 與 Step 6 不再互相矛盾。

        spec: issue-triage-staleness-review#old-severe-bug-keeps-its-priority
        tc: ITS-DT-009
        """
        text = _skill_text()
        assert _missing(text, "ITS-DT-009") == []
        assert "KEEP 並降優先" not in text
        priority = _section(text, "## Step 6", "## Step 7")
        assert "| **時效** | 有 deadline" in priority
        assert "長期無活動" not in priority.split("| **時效**", 1)[1].split("\n", 1)[0]

    def test_its_dt_010_new_write_actions_stay_opt_in(self) -> None:
        """OBSOLETE 關閉、stale notice、寬限期滿關閉都只在 --apply 且逐項確認後；排程只進報告。

        spec: issue-triage-staleness-review#scheduled-run
        spec: issue-triage-staleness-review#apply-run-with-confirmation
        tc: ITS-DT-010
        """
        assert _missing(_skill_text(), "ITS-DT-010") == []

    def test_its_dt_011_staleness_verdicts_are_github_only(self) -> None:
        """OBSOLETE 與 STALE-CANDIDATE 只適用 GitHub issue，Jira bug 不套用。

        spec: issue-triage-staleness-review#old-jira-bug
        tc: ITS-DT-011
        """
        assert _missing(_skill_text(), "ITS-DT-011") == []

    def test_its_dt_012_unavailable_data_fails_safe(self) -> None:
        """過期資料取不到的 issue 不得升級，且不得把缺資料當成人為活動。

        spec: issue-triage-staleness-review#comment-lookup-fails-for-one-issue
        tc: ITS-DT-012
        """
        assert _missing(_skill_text(), "ITS-DT-012") == []

    def test_its_dt_013_no_drift_signal_is_not_evidence(self) -> None:
        """never-existed 與 NOT_APPLICABLE 都不是前提的證據（前者多半是寫錯路徑）。

        spec: issue-triage-staleness-review#never-existed-path-is-not-evidence-of-absence
        spec: issue-triage-staleness-review#issue-references-no-paths
        tc: ITS-DT-013
        """
        assert _missing(_skill_text(), "ITS-DT-013") == []


class TestSelfCheck:
    @pytest.mark.parametrize(
        ("tc_id", "anchor"),
        [(tc_id, a) for tc_id, anchors in ANCHORS.items() for a in anchors],
    )
    def test_its_eg_014_removing_any_anchor_turns_the_checker_red(
        self, tc_id: str, anchor: str
    ) -> None:
        """突變自檢：把任一錨點從真實 SKILL.md 的**所有出現處**移除，檢查器必須回報它。

        「規則被刪掉」的模型是該句在 runbook 裡完全消失；有些錨點出現在多處
        （例如報告模板與決策表各一次），只移除第一處不算刪掉規則。
        一個永遠回報「沒問題」的檢查器在這裡會被抓到；
        錨點若在原文中根本不存在，也會先在前面的測試失敗。

        spec: issue-triage-staleness-review#age-alone-never-closes
        tc: ITS-EG-014
        """
        text = _skill_text()
        assert anchor in text, f"{tc_id} 的錨點不在 SKILL.md：{anchor!r}"
        mutated = text.replace(anchor, "")
        assert _missing(mutated, tc_id) == [anchor]

    @pytest.mark.parametrize("forbidden", FORBIDDEN)
    def test_its_eg_015_forbidden_wording_is_detected(self, forbidden: str) -> None:
        """正向對照：把舊措辭注入真實 SKILL.md，檢查器必須抓到；原文本身必須是乾淨的。

        spec: issue-triage-staleness-review#old-severe-bug-keeps-its-priority
        tc: ITS-EG-015
        """
        text = _skill_text()
        assert _forbidden_hits(text) == [], "SKILL.md 含已被推翻的舊措辭"
        assert _forbidden_hits(text + "\n" + forbidden) == [forbidden]

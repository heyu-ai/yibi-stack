"""SKILL.md 文字契約測試（change: add-issue-triage-staleness-review）。

OBSOLETE、STALE-CANDIDATE、過期分層、豁免、寬限期、優先級這些規則，執行者是「讀 runbook 的 agent」，
pytest 無法驗證它在任意未來的 issue 上會不會遵守。這份測試只做 `[doc]` 層：斷言 runbook **有明文寫**
這條規則，並防止有人「順手」改掉（例如把新的優先序改回舊的、把 FAQ 的「降優先」寫回來）。

讀者不得把這裡的 PASS 誤讀為行為證明；執行期行為列在 testplan.md 的 Manual Verification。

每個錨點都綁定到「負責它的段落」（SCOPES）：同一句話在別的段落出現不算數，否則把決策表的列改掉、
而報告模板或 FAQ 剛好有同一句，檢查器仍然是綠的。每個錨點在它的段落內必須恰好出現一次
（ITS-EG-016），這樣「移除它」才有明確的意義。

每個測試以 docstring 的 `spec:`／`tc:` 行綁定到 testplan 的 TC。自檢：`ITS-EG-014` 對每個錨點的
每一個出現處逐一做突變（一次只移除一處），斷言只有「負責段落內的那一處」會讓檢查器變紅；
一個永遠回報「沒問題」的檢查器在這裡會被抓到。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[2] / "SKILL.md"

# 段落名稱 -> (起始字串, 結束字串)。起始字串本身屬於該段落，結束字串不屬於；
# 結束為 None 表示到文件尾端。任一端點找不到（例如標題被刪掉），
# 都視為該段落的所有錨點遺失。
SCOPES: dict[str, tuple[str, str | None]] = {
    "baseline": ("### 1c.", "## Step 2"),
    "staleness": ("### 3d′. 過期檢視輸入", "### 3e. Verdict"),
    "tiers": ("#### 過期分層", "#### 程式碼漂移訊號"),
    "drift": ("#### 程式碼漂移訊號", "#### 豁免"),
    "exemptions": ("#### 豁免", "#### triage 標記"),
    "marker": ("#### triage 標記", "### 3e. Verdict"),
    "verdicts": ("### 3e. Verdict", "**OBSOLETE 的證據標準**"),
    "obsolete": ("**OBSOLETE 的證據標準**", "**STALE-CANDIDATE 與寬限期**"),
    "grace": ("**STALE-CANDIDATE 與寬限期**", "## Step 4"),
    "priority": ("## Step 6", "## Step 7"),
    "report": ("# Issue Triage -- <repo slug>", "若 `$OUT` 落在"),
    "writes": ("## Step 8", "## FAQ"),
}

Anchor = tuple[str, str]  # (段落名稱, 逐字文字)

# 錨點以「單一職責」分組；key 對應 testplan 的 TC。字串必須與 SKILL.md 逐字相同。
ANCHORS: dict[str, list[Anchor]] = {
    "ITS-DT-001": [
        ("baseline", "包含只盤點 Jira bug"),
        ("baseline", "bash ~/.agents/skills/issue-triage/scripts/check-baseline.sh"),
        ("baseline", "不要回退到本機的 origin/main"),
    ],
    "ITS-DT-002": [
        ("report", "## 證據基準"),
        ("report", "origin/main@<BASELINE_SHA 完整 40 字元>"),
    ],
    "ITS-DT-003": [
        ("writes", "`close-<n>.md` 最後一行必須是 `<!-- issue-triage:close <今天日期> -->`"),
        (
            "writes",
            "`update-<n>.md` 最後一行必須是 `<!-- issue-triage:update-scope <今天日期> -->`",
        ),
        ("writes", "`merge-<b>.md` 最後一行必須是 `<!-- issue-triage:merge <今天日期> -->`"),
        (
            "writes",
            "`stale-<n>.md` 最後一行必須是 `<!-- issue-triage:stale-notice <今天日期> -->`",
        ),
        ("writes", "（8a、8b、8d、8g、8h、8i、8j）內文最後一行都必須帶 triage 標記"),
        ("writes", "**貼在 GitHub issue 上的那則留言**"),
        ("writes", "同樣必須是 `<!-- issue-triage:merge <今天日期> -->`"),
        ("staleness", "另一個帳號貼出的標記一律算人為活動"),
        ("staleness", "內文的**最後一個非空行**恰好是一個完整的 triage 標記"),
        ("staleness", "種類不是已知的四種（例如 `stale-notice-foo`）"),
        ("marker", "標記必須是該則留言的**最後一個非空行**"),
    ],
    "ITS-DT-004": [
        ("tiers", "| 0 | 少於 30 天 |"),
        ("tiers", "| 1 | 30 到 89 天 |"),
        ("tiers", "| 2 | 90 到 179 天 |"),
        ("tiers", "| 3 | 180 天以上 |"),
        (
            "tiers",
            "29 天是 tier 0、30 天是 tier 1、89 天是 tier 1、"
            "90 天是 tier 2、179 天是 tier 2、180 天是 tier 3",
        ),
        ("tiers", "**都生效**"),
        ("tiers", "premise-unverified"),
        ("tiers", "KEEP 必須引用「前提仍成立」的正向證據"),
    ],
    "ITS-DT-005": [
        ("obsolete", "零命中的搜尋沒有資訊量"),
        ("obsolete", "必須有**正向對照**"),
        ("obsolete", "該症狀的結論是 UNCLEAR，**不構成 OBSOLETE**"),
        ("obsolete", "只有**部分**未解症狀失去前提時，verdict 是 UPDATE-SCOPE"),
        ("obsolete", "建議關閉原因一律是 `not planned`"),
    ],
    "ITS-DT-006": [
        (
            "grace",
            "| 沒有已辨識的 stale notice | 提議貼 stale notice：詢問是否仍需要，"
            "說明寬限期 **14 天**",
        ),
        (
            "grace",
            "| 有已辨識的 stale notice，距今不滿 14 天 "
            "| 不動作（寬限期內），報告列為「寬限期中」 |",
        ),
        (
            "grace",
            "| 有已辨識的 stale notice，距今 14 天以上，"
            "且 notice 之後沒有實質人為活動（最後人為活動時間不晚於 notice 時間） "
            "| 提議以 `not planned` 關閉 |",
        ),
        ("grace", "| notice 之後有實質人為活動 | 當作沒有 notice 重新評估"),
        (
            "grace",
            "**絕不**：僅憑天數建議關閉、在沒有先前 stale notice 的情況下建議關閉、"
            "在 notice 未滿 14 天時建議關閉",
        ),
        ("writes", "**寫入前必須重新呼叫** `last-human-activity.sh"),
        ("writes", "有新活動就放棄這筆"),
    ],
    "ITS-DT-007": [
        ("exemptions", "`assignees` 非空"),
        ("exemptions", "`dueOn` 為 null 的 milestone 沒有期限，不豁免"),
        ("exemptions", "OWNER、MEMBER 或 COLLABORATOR"),
        ("exemptions", "路人（NONE、CONTRIBUTOR 等）的 keep-open 留言不構成豁免"),
        ("exemptions", "有 security 相關 label"),
    ],
    "ITS-DT-008": [
        ("verdicts", "**MERGE > CLOSE > OBSOLETE > UPDATE-SCOPE > STALE-CANDIDATE > KEEP**"),
    ],
    "ITS-DT-009": [
        ("priority", "久未更新不降低優先級"),
        ("priority", "review-urgency: <N> 天無人為活動"),
        ("priority", "不影響「做這件事有多急」"),
    ],
    "ITS-DT-010": [
        ("writes", "排程與 webhook 情境即使看到 STALE-CANDIDATE 也只進報告、不貼任何留言"),
        ("writes", "只在 `--apply` 且逐項確認後才執行"),
        ("writes", "**無互動確認者（排程 / webhook）即使帶 `--apply` 也不執行寫入**"),
    ],
    "ITS-DT-011": [
        ("staleness", "Jira bug 不適用本節"),
        ("verdicts", "（僅 GitHub issue） | **OBSOLETE** |"),
        ("verdicts", "（僅 GitHub issue） | **STALE-CANDIDATE** |"),
        ("report", "## 前提已消失（OBSOLETE，建議以 not planned 關閉；僅 GitHub issue）"),
        ("report", "## 過期候選（STALE-CANDIDATE；僅 GitHub issue）"),
    ],
    "ITS-DT-012": [
        # last-human-activity.sh 的 exit 1、3、4
        ("staleness", "不要當成「有人為活動」"),
        ("staleness", "同一次執行內**第二次**出現 exit 3 時"),
        ("staleness", "`[FAIL] gh API 連續失敗，停止過期檢視`"),
        ("staleness", "所有需要呼叫腳本的 issue 都標「過期檢視不可用」"),
        ("staleness", "**標「過期檢視不可用」的 issue**"),
        ("staleness", "缺資料不是「有人為活動」，也不是「沒有漂移」"),
        # staleness-signals.sh 的 exit 1、3
        (
            "drift",
            "| 1 | 腳本自身的未預期錯誤 | 該 issue 標「過期檢視不可用」，"
            "不得升為 STALE-CANDIDATE 或 OBSOLETE；不要當成「沒有漂移」 |",
        ),
        ("drift", "| 3 | 不在 git repo 內，或找不到 origin/main | 該 issue 標「過期檢視不可用」"),
        # 決策表的 guard
        (
            "verdicts",
            "| **guard** | **任一過期資料取不到**（最後人為活動時間或漂移訊號，見 3d′） "
            "| **過期檢視不可用** | 該 issue 不得成為 OBSOLETE 或 STALE-CANDIDATE",
        ),
        ("report", "## 過期檢視不可用"),
    ],
    "ITS-DT-013": [
        ("drift", "多半是 issue 寫錯路徑"),
        ("drift", "`NOT_APPLICABLE`"),
        ("drift", "**「沒有漂移訊號」與「不適用」都不是前提仍成立的證據**"),
        ("drift", "**不是**消失的證據"),
    ],
    "ITS-DT-014": [
        (
            "verdicts",
            "| **guard** | **Step 1 / Step 2 的必要前置呼叫失敗**"
            "（`gh auth status`、`gh repo view`、`check-baseline.sh` 非 0、`gh issue list`） "
            "| **STOP** |",
        ),
        (
            "verdicts",
            "| **guard** | **任一症狀 = UNCLEAR** | **視同 NOT DONE** "
            "| 不得 CLOSE，也不得 OBSOLETE；落 KEEP 或 UPDATE-SCOPE |",
        ),
        ("verdicts", "| 1 | 與另一 open issue/bug 覆蓋同一主題（含跨系統） | **MERGE** |"),
        (
            "verdicts",
            "| 2 | 所有症狀 DONE，且（若綁 change）tasks.md 全 `[x]`，且無 keep-open | **CLOSE** |",
        ),
        ("verdicts", "| 3 | 留言有 close-authorization 且無未解症狀 | **CLOSE** |"),
        (
            "verdicts",
            "| 4 | 所有未解症狀的前提皆已證實不存在於基準（見下方「OBSOLETE 的證據標準」），"
            "且無豁免（僅 GitHub issue） | **OBSOLETE** | 留言說明前提消失與證據，"
            "以 `not planned` 關閉（不是 `completed`） |",
        ),
        (
            "verdicts",
            "| 5 | 部分症狀 DONE、部分 NOT DONE，或只有部分症狀失去前提 | **UPDATE-SCOPE** |",
        ),
        ("verdicts", "| 6 | 原本會落在第 7 或第 8 列、tier 3（無人為活動 180 天以上）、"),
        ("verdicts", "前提未被證實消失、無豁免（僅 GitHub issue）"),
        ("verdicts", "| 7 | 全部症狀 NOT DONE | **KEEP** |"),
        ("verdicts", "| 8 | 症狀無法從 repo 內部驗證 | **KEEP (external)** |"),
        ("verdicts", "| +附加 | 缺 type label / label 過期 / 狀態不符 | **RELABEL**（正交） |"),
    ],
}

# 舊版措辭：任何一個出現在 SKILL.md 就代表有人把已被推翻的規則寫回來
FORBIDDEN: list[str] = [
    "MERGE > CLOSE > UPDATE-SCOPE > KEEP",
    "KEEP 並降優先",
    "長期無活動 |",
    "任一前置呼叫失敗",
    "連續失敗代表認證或網路問題",
]

_ALL_ANCHORS: list[tuple[str, str, str]] = [
    (tc_id, scope, text) for tc_id, anchors in ANCHORS.items() for scope, text in anchors
]


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _bounds(text: str, scope: str) -> tuple[int, int]:
    """段落 [i, j) 的位置；端點找不到時丟 ValueError。"""
    start, end = SCOPES[scope]
    i = text.index(start)
    j = len(text) if end is None else text.index(end, i + len(start))
    return i, j


def _section(text: str, start: str, end: str) -> str:
    """取 start 標題到 end 標題之間的文字；任一標題不存在就讓測試明確失敗。"""
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


def _missing(text: str, tc_id: str) -> list[str]:
    """回報 tc_id 下，在「負責段落」內找不到的錨點；段落端點本身不見時，該段落的錨點全數遺失。"""
    missing: list[str] = []
    for scope, anchor in ANCHORS[tc_id]:
        try:
            i, j = _bounds(text, scope)
        except ValueError:
            missing.append(anchor)
            continue
        if anchor not in text[i:j]:
            missing.append(anchor)
    return missing


def _forbidden_hits(text: str) -> list[str]:
    return [f for f in FORBIDDEN if f in text]


def _positions(text: str, needle: str) -> list[int]:
    found: list[int] = []
    start = text.find(needle)
    while start != -1:
        found.append(start)
        start = text.find(needle, start + 1)
    return found


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
        """8a、8b、8d、8g、8i 各自明寫標記；標記是最後一個非空行的完整標記；
        另一帳號貼出的算人為活動。

        spec: issue-triage-staleness-review#closing-note-carries-the-marker
        spec: issue-triage-staleness-review#scope-update-carries-the-marker
        spec: issue-triage-staleness-review#merge-note-carries-the-marker
        spec: issue-triage-staleness-review#incomplete-marker-is-human-activity
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
        """寬限期 14 天（表格每一列）、notice 之後無人為活動才建議關閉、
        寫入前重新量測、絕不僅憑天數。

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
        """過期資料取不到的 issue 不得升級；每個腳本的失敗 exit code 都有對應的分支與數字門檻。

        spec: issue-triage-staleness-review#comment-lookup-fails-for-one-issue
        spec: issue-triage-staleness-review#repeated-comment-lookup-failure
        spec: issue-triage-staleness-review#drift-lookup-fails-for-one-issue
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

    def test_its_dt_014_every_verdict_row_has_its_own_anchor(self) -> None:
        """決策表的 guard 與每一列都有逐列錨點，改掉單一欄位（天數、not planned、無豁免）會變紅。

        spec: issue-triage-staleness-review#all-symptoms-done-and-premise-also-gone
        spec: issue-triage-staleness-review#premise-artifacts-removed-with-positive-control
        spec: issue-triage-staleness-review#first-stale-candidate
        tc: ITS-DT-014
        """
        assert _missing(_skill_text(), "ITS-DT-014") == []


class TestSelfCheck:
    @pytest.mark.parametrize(
        ("tc_id", "scope", "anchor"),
        _ALL_ANCHORS,
        ids=[f"{tc}-{i}" for i, (tc, _, _) in enumerate(_ALL_ANCHORS)],
    )
    def test_its_eg_014_removing_any_single_occurrence_turns_the_checker_red_only_in_scope(
        self, tc_id: str, scope: str, anchor: str
    ) -> None:
        """突變自檢：一次只移除錨點的一個出現處。

        移除「負責段落內」的那一處，檢查器必須回報它；移除段落外的出現處，檢查器不得受影響
        （否則錨點其實沒有綁定到負責的段落）。一個永遠回報「沒問題」的檢查器會在前一種情況被抓到，
        一個沒有段落綁定的檢查器會在後一種情況被抓到。

        spec: issue-triage-staleness-review#age-alone-never-closes
        tc: ITS-EG-014
        """
        text = _skill_text()
        i, j = _bounds(text, scope)
        positions = _positions(text, anchor)
        assert positions, f"{tc_id} 的錨點不在 SKILL.md：{anchor!r}"
        in_scope = [p for p in positions if i <= p and p + len(anchor) <= j]
        assert len(in_scope) == 1, f"錨點在 {scope} 段落內必須恰好出現一次：{anchor!r}"
        for p in positions:
            mutated = text[:p] + text[p + len(anchor) :]
            missing = _missing(mutated, tc_id)
            if p in in_scope:
                assert anchor in missing, f"移除負責段落內的錨點，檢查器仍是綠的：{anchor!r}"
            else:
                assert anchor not in missing, f"段落外的出現處影響了檢查結果：{anchor!r}"

    @pytest.mark.parametrize(("tc_id", "scope", "anchor"), _ALL_ANCHORS)
    def test_its_eg_016_every_anchor_is_unique_inside_its_scope(
        self, tc_id: str, scope: str, anchor: str
    ) -> None:
        """每個錨點在它的負責段落內恰好出現一次；多於一次時，移除其中一處不算「規則被刪掉」。

        spec: issue-triage-staleness-review#age-alone-never-closes
        tc: ITS-EG-016
        """
        text = _skill_text()
        i, j = _bounds(text, scope)
        assert text[i:j].count(anchor) == 1, f"{tc_id}／{scope}：{anchor!r}"

    @pytest.mark.parametrize("forbidden", FORBIDDEN)
    def test_its_eg_015_forbidden_wording_is_detected(self, forbidden: str) -> None:
        """正向對照：把舊措辭注入真實 SKILL.md，檢查器必須抓到；原文本身必須是乾淨的。

        spec: issue-triage-staleness-review#old-severe-bug-keeps-its-priority
        tc: ITS-EG-015
        """
        text = _skill_text()
        assert _forbidden_hits(text) == [], "SKILL.md 含已被推翻的舊措辭"
        assert _forbidden_hits(text + "\n" + forbidden) == [forbidden]

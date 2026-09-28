"""check_pr_line_budget.py 的行為測試。

`parse_budget()` / `file_delta()` / `evaluate()` 為純函式，直接斷言。`collect()` 與
`main()` 會呼叫 gh，改以 monkeypatch 替換 `fetch_file` / `fetch_open_prs`。
情境資料取自 2026-09-28 的真實協調：main 上 SKILL.md 1340 行、budget 1340，
#494 -16、#495 +3、#474 +15（branch budget 1355）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_pr_line_budget as cplb  # noqa: E402

SKILL = cplb.DEFAULT_FILE
BUDGET_FILE = cplb.DEFAULT_BUDGET_FILE


# --- parse_budget: 純函式 ---


class TestParseBudget:
    def test_plain_assignment_returns_int(self) -> None:
        assert cplb.parse_budget("LINE_BUDGET = 1340\n", "LINE_BUDGET") == 1340

    def test_annotated_assignment_with_comment_returns_int(self) -> None:
        text = "x = 1\nLINE_BUDGET: int = 1355  # raised for #474\n"
        assert cplb.parse_budget(text, "LINE_BUDGET") == 1355

    def test_missing_var_returns_none(self) -> None:
        assert cplb.parse_budget("OTHER = 1\n", "LINE_BUDGET") is None

    def test_indented_assignment_is_not_top_level(self) -> None:
        assert cplb.parse_budget("def f():\n    LINE_BUDGET = 9\n", "LINE_BUDGET") is None

    def test_prefixed_name_does_not_match(self) -> None:
        assert cplb.parse_budget("OLD_LINE_BUDGET = 9\n", "LINE_BUDGET") is None


# --- file_delta: 純函式 ---


class TestFileDelta:
    def test_matching_path_returns_additions_minus_deletions(self) -> None:
        files = [{"path": SKILL, "additions": 27, "deletions": 43}]
        assert cplb.file_delta(files, SKILL) == -16

    def test_untouched_path_returns_none(self) -> None:
        files = [{"path": "other.md", "additions": 1, "deletions": 0}]
        assert cplb.file_delta(files, SKILL) is None

    def test_missing_counts_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="additions/deletions"):
            cplb.file_delta([{"path": SKILL, "additions": None, "deletions": 1}], SKILL)


# --- evaluate: 純函式 ---


def _pr(number: int, delta: int, budget: int) -> cplb.PrDelta:
    return cplb.PrDelta(number=number, head_ref=f"b{number}", delta=delta, budget=budget)


class TestEvaluate:
    def test_2026_09_28_wave_flags_only_495_standalone(self) -> None:
        report = cplb.evaluate(
            1340, 1340, [_pr(494, -16, 1340), _pr(495, 3, 1340), _pr(474, 15, 1355)]
        )
        assert report.combined_lines == 1342
        assert report.combined_budget == 1355
        assert report.violations == ("#495 單獨 merge 後 1343 行，超過 merge 後生效的 budget 1340",)

    def test_combined_over_max_budget_is_flagged(self) -> None:
        report = cplb.evaluate(1330, 1340, [_pr(1, 6, 1340), _pr(2, 6, 1340)])
        assert report.combined_lines == 1342
        assert any("全部 merge 後 1342 行" in v for v in report.violations)
        # 單獨 merge 各自 1336 行，都在 budget 內
        assert len(report.violations) == 1

    def test_exactly_at_budget_is_not_a_violation(self) -> None:
        report = cplb.evaluate(1337, 1340, [_pr(1, 3, 1340)])
        assert report.violations == ()

    def test_no_prs_uses_main_budget(self) -> None:
        report = cplb.evaluate(1340, 1340, [])
        assert report.combined_lines == 1340
        assert report.combined_budget == 1340
        assert report.violations == ()


# --- collect / main: monkeypatch gh ---


def _fake_file(files: dict[tuple[str, str], str]):
    def fetch(path: str, ref: str) -> str:
        try:
            return files[(path, ref)]
        except KeyError as e:
            raise RuntimeError(f"gh api 失敗：{ref}:{path} 不存在") from e

    return fetch


@pytest.fixture
def wave(monkeypatch: pytest.MonkeyPatch) -> None:
    files = {
        (SKILL, "main"): "x\n" * 1340,
        (BUDGET_FILE, "main"): "LINE_BUDGET = 1340\n",
        (BUDGET_FILE, "feat-494"): "LINE_BUDGET = 1340\n",
        (BUDGET_FILE, "feat-495"): "LINE_BUDGET = 1340\n",
        (BUDGET_FILE, "feat-474"): "LINE_BUDGET = 1355\n",
    }
    prs = [
        {
            "number": 494,
            "headRefName": "feat-494",
            "files": [{"path": SKILL, "additions": 27, "deletions": 43}],
        },
        {
            "number": 495,
            "headRefName": "feat-495",
            "files": [{"path": SKILL, "additions": 3, "deletions": 0}],
        },
        {
            "number": 474,
            "headRefName": "feat-474",
            "files": [
                {"path": SKILL, "additions": 16, "deletions": 1},
                {"path": BUDGET_FILE, "additions": 1, "deletions": 1},
            ],
        },
        {
            "number": 493,
            "headRefName": "feat-493",
            "files": [{"path": "Makefile", "additions": 2, "deletions": 2}],
        },
    ]
    monkeypatch.setattr(cplb, "fetch_file", _fake_file(files))
    monkeypatch.setattr(cplb, "fetch_open_prs", lambda: prs)


class TestCollect:
    def test_skips_prs_not_touching_file(self, wave: None) -> None:
        report = cplb.collect(SKILL, BUDGET_FILE, "LINE_BUDGET", "main")
        assert [pr.number for pr in report.prs] == [494, 495, 474]

    def test_reads_each_branch_budget(self, wave: None) -> None:
        report = cplb.collect(SKILL, BUDGET_FILE, "LINE_BUDGET", "main")
        assert {pr.number: pr.budget for pr in report.prs} == {494: 1340, 495: 1340, 474: 1355}

    def test_stale_branch_budget_ignored_when_pr_does_not_touch_budget_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 實測（2026-09-28，#497）：branch 從舊 main 分出，上面的 LINE_BUDGET 還是 1340，
        # 但 PR 沒改 budget 檔，merge 後生效的是 main 的 1355。不可因此誤報。
        files = {
            (SKILL, "main"): "x\n" * 1346,
            (BUDGET_FILE, "main"): "LINE_BUDGET = 1355\n",
            (BUDGET_FILE, "stale"): "LINE_BUDGET = 1340\n",
        }
        prs = [
            {
                "number": 497,
                "headRefName": "stale",
                "files": [{"path": SKILL, "additions": 4, "deletions": 4}],
            }
        ]
        monkeypatch.setattr(cplb, "fetch_file", _fake_file(files))
        monkeypatch.setattr(cplb, "fetch_open_prs", lambda: prs)
        report = cplb.collect(SKILL, BUDGET_FILE, "LINE_BUDGET", "main")
        assert report.prs[0].budget == 1355
        assert report.violations == ()


class TestMain:
    def test_violation_exits_1_and_reports_to_stderr(
        self, wave: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cplb.main([]) == 1
        captured = capsys.readouterr()
        assert "#495 單獨 merge 後 1343 行" in captured.err
        assert "全部 merge 後：1342 行（最大 budget 1355）" in captured.out

    def test_all_within_budget_exits_0(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = {(SKILL, "main"): "x\n" * 1300, (BUDGET_FILE, "main"): "LINE_BUDGET = 1340\n"}
        monkeypatch.setattr(cplb, "fetch_file", _fake_file(files))
        monkeypatch.setattr(cplb, "fetch_open_prs", lambda: [])
        assert cplb.main([]) == 0
        assert "[OK]" in capsys.readouterr().out

    def test_missing_budget_var_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = {(SKILL, "main"): "x\n", (BUDGET_FILE, "main"): "OTHER = 1\n"}
        monkeypatch.setattr(cplb, "fetch_file", _fake_file(files))
        monkeypatch.setattr(cplb, "fetch_open_prs", lambda: [])
        assert cplb.main([]) == 2
        assert "找不到 LINE_BUDGET" in capsys.readouterr().err

    def test_gh_failure_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(path: str, ref: str) -> str:
            raise RuntimeError("gh api 失敗（exit 1）：HTTP 404")

        monkeypatch.setattr(cplb, "fetch_file", boom)
        assert cplb.main([]) == 2
        assert "HTTP 404" in capsys.readouterr().err

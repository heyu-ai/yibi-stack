"""測試 token_usage_service：transcript 定位、usage 加總、成本計算、optimization notes。

測試環境的 tmp_path 不是 git repo，_project_slug_for_cwd() 會在 `git -C <dir>
rev-parse` 失敗時 fallback 成「escape 該目錄路徑本身」——這個 fallback 行為是
確定性的，測試直接用同一條轉換規則建構假的 `~/.claude/projects/<slug>/` 目錄，
不需要 mock subprocess。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tasks.mycelium.token_usage_service import (
    TokenUsageReport,
    UsageAccumulator,
    _accumulate_usage_by_model,
    _count_tool_uses,
    _find_subagent_transcripts,
    _generate_optimization_notes,
    _model_cost,
    _normalize_model_id,
    compute_auto_token_fields,
    compute_token_usage_report,
    find_current_transcript,
)


def _slug_for(cwd: Path) -> str:
    """跟 _project_slug_for_cwd() 在非 git 目錄下的 fallback 行為一致（測試用）。"""
    return re.sub(r"[/\\]", "-", str(cwd))


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _assistant_message(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_5m: int = 0,
    cache_creation_1h: int = 0,
    cwd: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "message": {
            "role": "assistant",
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read_tokens,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": cache_creation_5m,
                    "ephemeral_1h_input_tokens": cache_creation_1h,
                },
            },
        }
    }
    if cwd is not None:
        record["cwd"] = cwd
    return record


def _tool_use_message(*tool_names: str, cwd: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name} for name in tool_names],
        }
    }
    if cwd is not None:
        record["cwd"] = cwd
    return record


class TestNormalizeModelId:
    def test_toksvc_dt_001_exact_match_passthrough(self) -> None:
        """TOKSVC-DT-001：定價表已有的 model id 原樣回傳。"""
        assert _normalize_model_id("claude-sonnet-5") == "claude-sonnet-5"

    def test_toksvc_dt_002_context_mode_suffix_stripped(self) -> None:
        """TOKSVC-DT-002：`[1m]` 這類 context-mode 後綴會被去掉。"""
        assert _normalize_model_id("claude-opus-4-8[1m]") == "claude-opus-4-8"

    def test_toksvc_dt_003_dated_snapshot_prefix_matched(self) -> None:
        """TOKSVC-DT-003：dated snapshot（如 -20251001）比對回 undated 定價表 key。"""
        assert _normalize_model_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5"

    def test_toksvc_dt_004_unknown_model_passthrough(self) -> None:
        """TOKSVC-DT-004：定價表沒有的 model 原樣回傳（讓呼叫端判斷 unpriced）。"""
        assert _normalize_model_id("claude-unknown-9000") == "claude-unknown-9000"


class TestFindCurrentTranscript:
    def test_toksvc_st_001_found_single_match(self, tmp_path: Path) -> None:
        """TOKSVC-ST-001：cwd 相符且唯一時回傳 found。"""
        working_dir = (tmp_path / "repo").resolve()
        projects_dir = tmp_path / "projects"
        slug = _slug_for(working_dir)
        transcript = projects_dir / slug / "session-a.jsonl"
        _write_jsonl(
            transcript,
            [_assistant_message("claude-sonnet-5", cwd=str(working_dir))],
        )

        result = find_current_transcript(working_dir, projects_dir=projects_dir)
        assert result.status == "found"
        assert result.path == transcript

    def test_toksvc_st_002_not_found_when_project_dir_missing(self, tmp_path: Path) -> None:
        """TOKSVC-ST-002：project transcript 目錄不存在時回傳 not_found。"""
        working_dir = (tmp_path / "repo").resolve()
        result = find_current_transcript(working_dir, projects_dir=tmp_path / "projects")
        assert result.status == "not_found"

    def test_toksvc_st_003_not_found_when_no_cwd_match(self, tmp_path: Path) -> None:
        """TOKSVC-ST-003：有 transcript 但 cwd 不相符時回傳 not_found。"""
        working_dir = (tmp_path / "repo").resolve()
        other_dir = (tmp_path / "other-repo").resolve()
        projects_dir = tmp_path / "projects"
        slug = _slug_for(working_dir)
        _write_jsonl(
            projects_dir / slug / "session-a.jsonl",
            [_assistant_message("claude-sonnet-5", cwd=str(other_dir))],
        )

        result = find_current_transcript(working_dir, projects_dir=projects_dir)
        assert result.status == "not_found"

    def test_toksvc_eg_001_ambiguous_when_mtimes_close(self, tmp_path: Path) -> None:
        """TOKSVC-EG-001：兩個候選檔案 mtime 太接近時回傳 ambiguous，不硬猜。"""
        working_dir = (tmp_path / "repo").resolve()
        projects_dir = tmp_path / "projects"
        slug = _slug_for(working_dir)
        record = [_assistant_message("claude-sonnet-5", cwd=str(working_dir))]
        _write_jsonl(projects_dir / slug / "session-a.jsonl", record)
        _write_jsonl(projects_dir / slug / "session-b.jsonl", record)

        result = find_current_transcript(
            working_dir, projects_dir=projects_dir, ambiguity_window_seconds=3600.0
        )
        assert result.status == "ambiguous"


class TestAccumulateUsageByModel:
    def test_toksvc_st_004_sums_across_multiple_records(self, tmp_path: Path) -> None:
        """TOKSVC-ST-004：同一 model 多筆記錄的 usage 會加總。"""
        path = tmp_path / "t.jsonl"
        _write_jsonl(
            path,
            [
                _assistant_message("claude-sonnet-5", input_tokens=100, output_tokens=10),
                _assistant_message("claude-sonnet-5", input_tokens=50, output_tokens=5),
            ],
        )
        result = _accumulate_usage_by_model(path)
        assert result["claude-sonnet-5"].input_tokens == 150
        assert result["claude-sonnet-5"].output_tokens == 15

    def test_toksvc_st_005_separates_by_model(self, tmp_path: Path) -> None:
        """TOKSVC-ST-005：不同 model 的 usage 分開累加。"""
        path = tmp_path / "t.jsonl"
        _write_jsonl(
            path,
            [
                _assistant_message("claude-sonnet-5", input_tokens=100),
                _assistant_message("claude-opus-4-8", input_tokens=200),
            ],
        )
        result = _accumulate_usage_by_model(path)
        assert set(result) == {"claude-sonnet-5", "claude-opus-4-8"}

    def test_toksvc_eg_002_legacy_flat_cache_creation_folds_into_5m(self, tmp_path: Path) -> None:
        """TOKSVC-EG-002：舊格式的攤平 cache_creation_input_tokens 保守歸入 5m 分桶。"""
        path = tmp_path / "t.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-5",
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_creation_input_tokens": 999,
                        },
                    }
                }
            ],
        )
        result = _accumulate_usage_by_model(path)
        assert result["claude-sonnet-5"].cache_creation_5m_tokens == 999
        assert result["claude-sonnet-5"].cache_creation_1h_tokens == 0

    def test_toksvc_eg_003_malformed_line_skipped(self, tmp_path: Path) -> None:
        """TOKSVC-EG-003：無法解析的行被跳過，不中斷掃描。"""
        path = tmp_path / "t.jsonl"
        path.write_text(
            "not json\n" + json.dumps(_assistant_message("claude-sonnet-5", input_tokens=1)) + "\n",
            encoding="utf-8",
        )
        result = _accumulate_usage_by_model(path)
        assert result["claude-sonnet-5"].input_tokens == 1


class TestModelCost:
    def test_toksvc_st_006_priced_model_formula(self) -> None:
        """TOKSVC-ST-006：定價表內的 model 依公式計算成本（含 cache 倍率）。"""
        acc = UsageAccumulator(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=1_000_000,
            cache_creation_5m_tokens=1_000_000,
            cache_creation_1h_tokens=1_000_000,
        )
        # claude-sonnet-5: input=3.00, output=15.00 ($/1M)
        breakdown = _model_cost("claude-sonnet-5", acc)
        expected = (
            3.00
            + (1_000_000 * 3.00 * 1.25) / 1_000_000
            + (1_000_000 * 3.00 * 2.0) / 1_000_000
            + (1_000_000 * 3.00 * 0.1) / 1_000_000
            + 15.00
        )
        assert breakdown.priced is True
        assert breakdown.cost_usd is not None
        assert abs(breakdown.cost_usd - expected) < 1e-9

    def test_toksvc_dt_005_unpriced_model_returns_none_cost(self) -> None:
        """TOKSVC-DT-005：定價表沒有的 model，cost_usd=None、priced=False。"""
        breakdown = _model_cost("claude-unknown-9000", UsageAccumulator(input_tokens=100))
        assert breakdown.priced is False
        assert breakdown.cost_usd is None


class TestCountToolUses:
    def test_toksvc_st_007_counts_mutating_and_read_only(self, tmp_path: Path) -> None:
        """TOKSVC-ST-007：正確分類 mutating 與 read_only tool call。"""
        path = tmp_path / "agent-x.jsonl"
        _write_jsonl(path, [_tool_use_message("Read", "Grep", "Write")])
        counts = _count_tool_uses(path)
        assert counts == {"mutating": 1, "read_only": 2, "total": 3}


class TestFindSubagentTranscripts:
    def test_toksvc_st_008_finds_sibling_subagents_dir(self, tmp_path: Path) -> None:
        """TOKSVC-ST-008：subagent transcript 位於 `<main stem>/subagents/agent-*.jsonl`。"""
        main = tmp_path / "session-a.jsonl"
        main.write_text("", encoding="utf-8")
        agent_path = tmp_path / "session-a" / "subagents" / "agent-abc123.jsonl"
        _write_jsonl(agent_path, [_assistant_message("claude-opus-4-8")])

        found = _find_subagent_transcripts(main)
        assert found == [agent_path]

    def test_toksvc_st_009_no_subagents_dir_returns_empty(self, tmp_path: Path) -> None:
        """TOKSVC-ST-009：沒有 subagents 目錄時回傳空 list。"""
        main = tmp_path / "session-a.jsonl"
        main.write_text("", encoding="utf-8")
        assert _find_subagent_transcripts(main) == []


class TestGenerateOptimizationNotes:
    def test_toksvc_dt_006_flags_expensive_model_with_zero_mutating(self) -> None:
        """TOKSVC-DT-006：昂貴 model + 零 mutating tool call → 產生 best-effort 建議。"""
        notes = _generate_optimization_notes(
            [
                {
                    "model": "claude-opus-4-8",
                    "agent_type": "Explore",
                    "tool_counts": {"mutating": 0, "read_only": 5, "total": 5},
                }
            ]
        )
        assert len(notes) == 1
        assert "[best-effort]" in notes[0]
        assert "claude-opus-4-8" in notes[0]

    def test_toksvc_dt_007_no_note_when_mutating_present(self) -> None:
        """TOKSVC-DT-007：有 mutating tool call 時不產生建議（可能有正當理由用貴的 model）。"""
        notes = _generate_optimization_notes(
            [
                {
                    "model": "claude-opus-4-8",
                    "agent_type": "general-purpose",
                    "tool_counts": {"mutating": 2, "read_only": 3, "total": 5},
                }
            ]
        )
        assert notes == []

    def test_toksvc_dt_008_no_note_for_cheap_model(self) -> None:
        """TOKSVC-DT-008：便宜 model（非 opus/fable/mythos 家族）不觸發建議。"""
        notes = _generate_optimization_notes(
            [
                {
                    "model": "claude-sonnet-5",
                    "agent_type": "Explore",
                    "tool_counts": {"mutating": 0, "read_only": 5, "total": 5},
                }
            ]
        )
        assert notes == []

    def test_toksvc_eg_004_no_note_when_zero_tool_calls(self) -> None:
        """TOKSVC-EG-004：完全沒有 tool call 的 subagent 不觸發建議（無法判斷是否讀取類）。"""
        notes = _generate_optimization_notes(
            [
                {
                    "model": "claude-opus-4-8",
                    "agent_type": "unknown",
                    "tool_counts": {"mutating": 0, "read_only": 0, "total": 0},
                }
            ]
        )
        assert notes == []


class TestComputeTokenUsageReport:
    def test_toksvc_st_010_merges_main_and_subagent_usage(self, tmp_path: Path) -> None:
        """TOKSVC-ST-010：計算結果合併主 transcript 與所有 subagent transcript 的用量。"""
        working_dir = (tmp_path / "repo").resolve()
        projects_dir = tmp_path / "projects"
        slug = _slug_for(working_dir)
        main = projects_dir / slug / "session-a.jsonl"
        _write_jsonl(
            main,
            [_assistant_message("claude-sonnet-5", input_tokens=100, cwd=str(working_dir))],
        )
        _write_jsonl(
            projects_dir / slug / "session-a" / "subagents" / "agent-x.jsonl",
            [_assistant_message("claude-opus-4-8", input_tokens=50)],
        )

        report = compute_token_usage_report(working_dir, projects_dir=projects_dir)
        assert report.status == "computed"
        assert report.total_input_tokens == 150
        models = {row["model"] for row in report.by_model}
        assert models == {"claude-sonnet-5", "claude-opus-4-8"}

    def test_toksvc_eg_007_synthetic_zero_usage_model_ignored(self, tmp_path: Path) -> None:
        """TOKSVC-EG-007：`<synthetic>`（Claude Code 內部零用量標記）不觸發 computed_partial。

        真實觀察到的資料：Claude Code 會在 transcript 插入
        `model="<synthetic>"`、usage 全 0 的記錄——不是真的 API 呼叫，不該被當成
        「未定價的 model」而讓整份報告降級成 computed_partial。
        """
        working_dir = (tmp_path / "repo").resolve()
        projects_dir = tmp_path / "projects"
        slug = _slug_for(working_dir)
        _write_jsonl(
            projects_dir / slug / "session-a.jsonl",
            [
                _assistant_message("claude-sonnet-5", input_tokens=10, cwd=str(working_dir)),
                _assistant_message("<synthetic>", input_tokens=0, output_tokens=0),
            ],
        )

        report = compute_token_usage_report(working_dir, projects_dir=projects_dir)
        assert report.status == "computed"
        assert report.warning is None
        assert {row["model"] for row in report.by_model} == {"claude-sonnet-5"}

    def test_toksvc_dt_009_unpriced_model_marks_computed_partial(self, tmp_path: Path) -> None:
        """TOKSVC-DT-009：出現定價表沒有的 model 時，status=computed_partial + warning。"""
        working_dir = (tmp_path / "repo").resolve()
        projects_dir = tmp_path / "projects"
        slug = _slug_for(working_dir)
        _write_jsonl(
            projects_dir / slug / "session-a.jsonl",
            [_assistant_message("claude-unknown-9000", input_tokens=10, cwd=str(working_dir))],
        )

        report = compute_token_usage_report(working_dir, projects_dir=projects_dir)
        assert report.status == "computed_partial"
        assert report.warning is not None
        assert "claude-unknown-9000" in report.warning

    def test_toksvc_eg_005_unavailable_when_not_found(self, tmp_path: Path) -> None:
        """TOKSVC-EG-005：找不到 transcript 時回傳 unavailable（不是 lookup 內部用的
        not_found，那個字串不是合法的 TokenUsageSource 值），不 raise。"""
        working_dir = (tmp_path / "repo").resolve()
        report = compute_token_usage_report(working_dir, projects_dir=tmp_path / "projects")
        assert report.status == "unavailable"
        assert isinstance(report, TokenUsageReport)

    def test_toksvc_eg_006_session_effort_from_env(self, tmp_path: Path, monkeypatch) -> None:
        """TOKSVC-EG-006：session_effort 讀取 $CLAUDE_EFFORT 環境變數。"""
        monkeypatch.setenv("CLAUDE_EFFORT", "high")
        working_dir = (tmp_path / "repo").resolve()
        projects_dir = tmp_path / "projects"
        slug = _slug_for(working_dir)
        _write_jsonl(
            projects_dir / slug / "session-a.jsonl",
            [_assistant_message("claude-sonnet-5", input_tokens=1, cwd=str(working_dir))],
        )

        report = compute_token_usage_report(working_dir, projects_dir=projects_dir)
        assert report.session_effort == "high"


class TestComputeAutoTokenFields:
    def test_toksvc_dt_010_disabled_returns_empty_dict(self, tmp_path: Path) -> None:
        """TOKSVC-DT-010：enabled=False 時直接回傳空 dict，不呼叫任何計算。"""
        assert compute_auto_token_fields(tmp_path, False) == {}

    def test_toksvc_st_011_computed_returns_all_fields(self, tmp_path: Path, monkeypatch) -> None:
        """TOKSVC-ST-011：status=computed 時回傳完整的 8 個欄位 + token_usage_source。"""
        report = TokenUsageReport(
            status="computed",
            total_input_tokens=10,
            total_output_tokens=2,
            total_cache_read_tokens=1,
            total_cache_creation_tokens=1,
            total_cost_usd=0.001,
            by_model=[{"model": "claude-sonnet-5"}],
            session_effort="high",
            optimization_notes=["note"],
        )
        monkeypatch.setattr(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            lambda *a, **k: report,
        )
        fields = compute_auto_token_fields(tmp_path, True)
        assert fields["token_usage_source"] == "computed"
        assert fields["token_input_tokens"] == 10
        assert fields["token_total_cost_usd"] == 0.001
        assert fields["session_effort"] == "high"

    def test_toksvc_st_012_ambiguous_returns_only_source(self, tmp_path: Path, monkeypatch) -> None:
        """TOKSVC-ST-012：status=ambiguous/unavailable 時只回傳 token_usage_source。"""
        report = TokenUsageReport(status="ambiguous", warning="並行 session")
        monkeypatch.setattr(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            lambda *a, **k: report,
        )
        fields = compute_auto_token_fields(tmp_path, True)
        assert fields == {"token_usage_source": "ambiguous"}

    def test_toksvc_eg_007_internal_exception_returns_empty_dict(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """TOKSVC-EG-007：compute_token_usage_report 本身 raise 時回傳空 dict，不往外拋。"""

        def _raise(*a: object, **k: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr("tasks.mycelium.token_usage_service.compute_token_usage_report", _raise)
        assert compute_auto_token_fields(tmp_path, True) == {}

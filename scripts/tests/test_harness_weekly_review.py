"""HWR: harness-weekly-review 的量測、建議與週對週比對測試。

Test ID 規則見 .claude/rules/09-test-conventions.md。

覆蓋對映：
- rule `paths:` 解析（清單式、inline、無 frontmatter、跨行陷阱）：HWR-DT-001
- hook 指令 → hook 名稱（run-hook launcher、直接呼叫、inline）：HWR-DT-002
- 建議分類（保險型 vs 低訊號、涵蓋不足時抑制、錯誤率、秒級計時門檻、silent block、
  gate 未接 CI、rule 過重、段落已有 gate）：HWR-DT-003..010
- hook-events 彙總與秒級解析度偵測：HWR-ST-001
- transcript 阻擋抽取（兩種形狀、uuid 去重、只收本 repo 與 worktree）：HWR-ST-002
- collect → report 端對端（快照、報告、lesson 候選）：HWR-ST-003
- 週對週比對（new／persisting／resolved／升級）：HWR-ST-004
- 非 git repo 與缺快照 fail loud：HWR-VL-001..002
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    REPO_ROOT
    / "plugins"
    / "harness"
    / "skills"
    / "harness-weekly-review"
    / "scripts"
    / "harness_review.py"
)
_spec = importlib.util.spec_from_file_location("harness_review", _SCRIPT_PATH)
assert _spec and _spec.loader
hr = importlib.util.module_from_spec(_spec)
sys.modules["harness_review"] = hr
_spec.loader.exec_module(hr)


def make_thresholds(**kwargs: object) -> argparse.Namespace:
    defaults = {
        "min_calls": 20,
        "error_rate": 0.05,
        "slow_p95_ms": 1000,
        "slow_total_ms": 60000,
        "noisy_failures": 20,
        "heavy_rule_chars": 8000,
        "min_rule_score": 12,
        "max_rule_candidates": 10,
        "gate_days": 90,
        "ignore_jobs": r"/ CI Status$",
    }
    return argparse.Namespace(**{**defaults, **kwargs})


def make_event_stats(**kwargs: object) -> dict[str, object]:
    defaults = {
        "calls": 50,
        "pass": 50,
        "warn": 0,
        "block": 0,
        "error": 0,
        "total_ms": 500,
        "p95_ms": 10,
        "error_rate": 0.0,
        "error_sample": None,
    }
    return {**defaults, **kwargs}


def make_snapshot(**overrides: object) -> dict[str, object]:
    snap: dict[str, object] = {
        "window": {"gate_since": "2026-07-01T00:00:00+00:00"},
        "hooks": {
            "inventory": {"registered": {}, "on_disk": [], "unregistered": []},
            "events": {"files": 1, "hooks": {}, "resolution": "ms", "covers_window": True},
            "transcript": {"hooks": {}},
        },
        "ci": {"inventory": {"gates": []}, "failures": {"jobs": {}}, "measured": True},
        "rules": {"files": [], "candidates": []},
    }
    for key, value in overrides.items():
        section, _, sub = key.partition("__")
        target = snap[section]
        if sub:
            for part in sub.split("__")[:-1]:
                target = target[part]  # type: ignore[index]
            target[sub.split("__")[-1]] = value  # type: ignore[index]
        else:
            snap[section] = value
    return snap


def rec_kinds(recs: list[dict[str, object]]) -> dict[str, str]:
    return {str(r["target"]): str(r["kind"]) for r in recs}


def git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


class TestParsing:
    def test_hwr_dt_001_paths_frontmatter(self) -> None:
        """HWR-DT-001: paths 解析——清單式 `**` 必須判為必載，不可被下一行吞掉"""
        assert hr.parse_paths_frontmatter('---\npaths:\n  - "**"\n---\nbody') == ["**"]
        assert hr.parse_paths_frontmatter('---\npaths: ["docs/**", "a"]\n---\n') == ["docs/**", "a"]
        assert hr.parse_paths_frontmatter("# no frontmatter") is None
        assert hr.parse_paths_frontmatter("---\nname: x\n---\n") is None
        assert hr.parse_paths_frontmatter(
            '---\npaths:\n  - "mobile/**"\n  - "b"\nother: 1\n---\n'
        ) == ["mobile/**", "b"]

    def test_hwr_dt_002_hook_name_from_command(self) -> None:
        """HWR-DT-002: launcher 形狀取其後的 script；inline 指令給 inline: 前綴"""
        launcher = 'R=$(git rev-parse --show-toplevel) || exit 2; L=$R/.claude/hooks/run-hook.sh; HOOK_ROOT=$R bash "$L" --python protect-bash-cd.py'
        assert hr.hook_name_from_command(launcher) == "protect-bash-cd.py"
        assert (
            hr.hook_name_from_command(
                '"$CLAUDE_PROJECT_DIR"/.claude/hooks/spec-audit-drift-check.sh'
            )
            == "spec-audit-drift-check.sh"
        )
        assert hr.hook_name_from_command("uv run ruff format x").startswith("inline:")


class TestRecommendations:
    def test_hwr_dt_003_insurance_vs_low_signal(self) -> None:
        """HWR-DT-003: 0 攔截時 protect-* 列為保留，一般 hook 列為退役候選"""
        snap = make_snapshot()
        snap["hooks"]["inventory"]["registered"] = {"protect-env.sh": {}, "figma-check.sh": {}}  # type: ignore[index]
        snap["hooks"]["events"]["hooks"] = {  # type: ignore[index]
            "protect-env.sh": make_event_stats(),
            "figma-check.sh": make_event_stats(),
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds["protect-env.sh"] == "hook-insurance-idle"
        assert kinds["figma-check.sh"] == "hook-low-signal"

    def test_hwr_dt_004_coverage_gap_suppresses_conclusions(self) -> None:
        """HWR-DT-004: 紀錄未涵蓋觀察期時，不產出沒資料與低訊號建議"""
        snap = make_snapshot()
        snap["hooks"]["events"]["covers_window"] = False  # type: ignore[index]
        snap["hooks"]["inventory"]["registered"] = {"a.sh": {}, "b.sh": {}}  # type: ignore[index]
        snap["hooks"]["events"]["hooks"] = {"a.sh": make_event_stats()}  # type: ignore[index]
        assert hr.build_recommendations(snap, make_thresholds()) == []

    def test_hwr_dt_005_error_rate(self) -> None:
        """HWR-DT-005: hook 自身錯誤率達門檻才列修正，低於門檻不列"""
        snap = make_snapshot()
        snap["hooks"]["inventory"]["registered"] = {"a.sh": {}, "b.sh": {}}  # type: ignore[index]
        snap["hooks"]["events"]["hooks"] = {  # type: ignore[index]
            "a.sh": make_event_stats(calls=20, error=2, error_rate=0.1, warn=1),
            "b.sh": make_event_stats(calls=100, error=1, error_rate=0.01, warn=1),
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds.get("a.sh") == "hook-error"
        assert "b.sh" not in kinds

    def test_hwr_dt_006_second_resolution_raises_slow_threshold(self) -> None:
        """HWR-DT-006: 秒級計時下 1000ms 讀值不算慢，2000ms 才算"""
        snap = make_snapshot()
        snap["hooks"]["events"]["resolution"] = "second"  # type: ignore[index]
        snap["hooks"]["inventory"]["registered"] = {"a.sh": {}, "b.sh": {}}  # type: ignore[index]
        snap["hooks"]["events"]["hooks"] = {  # type: ignore[index]
            "a.sh": make_event_stats(p95_ms=1000, warn=1),
            "b.sh": make_event_stats(p95_ms=2000, warn=1),
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert "a.sh" not in kinds
        assert kinds["b.sh"] == "hook-slow"

    def test_hwr_dt_007_silent_block(self) -> None:
        """HWR-DT-007: 過半阻擋沒有 stderr 時列為修正"""
        snap = make_snapshot()
        snap["hooks"]["transcript"]["hooks"] = {  # type: ignore[index]
            "x.py": {"block": 10, "no_stderr": 9},
            "y.py": {"block": 10, "no_stderr": 1},
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds["x.py"] == "hook-silent-block"
        assert "y.py" not in kinds

    def test_hwr_dt_008_gate_unwired_and_silent(self) -> None:
        """HWR-DT-008: 沒接 CI 的 gate 列修正；上線夠久且 0 失敗列退役候選；太新不列"""
        snap = make_snapshot()
        snap["ci"]["inventory"]["gates"] = [  # type: ignore[index]
            {"script": "rule-gate-a.py", "wired_in_ci": False, "added": "2026-01-01"},
            {"script": "rule-gate-b.py", "wired_in_ci": True, "added": "2026-01-01"},
            {"script": "rule-gate-c.py", "wired_in_ci": True, "added": "2026-09-01"},
            {"script": "rule-gate-d.py", "wired_in_ci": True, "added": "2026-01-01"},
        ]
        snap["ci"]["failures"]["jobs"] = {
            "CI / Gates": {
                "failures": 3,
                "branches": 2,  # type: ignore[index]
                "steps": {"rule-gate-d self-test": 3},
            }
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds["rule-gate-a.py"] == "gate-unwired"
        assert kinds["rule-gate-b.py"] == "gate-silent"
        assert "rule-gate-c.py" not in kinds
        assert "rule-gate-d.py" not in kinds

    def test_hwr_dt_009_ci_unmeasured_skips_silent_gate(self) -> None:
        """HWR-DT-009: CI 沒量到時不可把 gate 判成 0 失敗"""
        snap = make_snapshot()
        snap["ci"]["measured"] = False  # type: ignore[index]
        snap["ci"]["inventory"]["gates"] = [  # type: ignore[index]
            {"script": "rule-gate-b.py", "wired_in_ci": True, "added": "2026-01-01"}
        ]
        assert hr.build_recommendations(snap, make_thresholds()) == []

    def test_hwr_dt_011_noisy_step_ignores_rollup(self) -> None:
        """HWR-DT-011: 高噪以 step 為單位；rollup job 與未達門檻的 step 不列"""
        snap = make_snapshot()
        snap["ci"]["failures"]["jobs"] = {  # type: ignore[index]
            "CI / Doc Endpoint Paths": {
                "failures": 60,
                "branches": 30,
                "steps": {"Check change numbers": 46, "Check TODO": 2},
            },
            "CI / CI Status": {"failures": 300, "branches": 100, "steps": {"Check results": 300}},
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds == {"CI / Doc Endpoint Paths / Check change numbers": "gate-noisy"}

    def test_hwr_dt_012_bold_paragraph_sections(self) -> None:
        """HWR-DT-012: 行首粗體段落切成子段，避免整節併成一個大候選"""
        text = "## 1. Claims\n\n**V1 — first.**\nbody\n\n**V2 — second.**\nbody\n"
        titles = [t for t, _, _ in hr.split_sections(text)]
        assert titles == ["1. Claims", "V1 — first.", "V2 — second."]

    def test_hwr_dt_013_stale_plugin_version(self) -> None:
        """HWR-DT-013: 舊版快取仍在跑時列 stale-plugin；silent-block 只看最新版，已修好的舊版不誤報"""
        snap = make_snapshot()
        snap["hooks"]["transcript"]["hooks"] = {
            "bash-ap1.sh": {  # type: ignore[index]
                "block": 15,
                "no_stderr": 10,
                "versions": {
                    "1.20.1": {"block": 10, "no_stderr": 10},
                    "1.23.5": {"block": 5, "no_stderr": 0},
                },
            }
        }
        kinds = [r["kind"] for r in hr.build_recommendations(snap, make_thresholds())]
        assert kinds == ["hook-stale-plugin"]
        snap["hooks"]["transcript"]["hooks"]["bash-ap1.sh"]["versions"]["1.23.5"]["no_stderr"] = 5  # type: ignore[index]
        kinds = [r["kind"] for r in hr.build_recommendations(snap, make_thresholds())]
        assert kinds == ["hook-stale-plugin", "hook-silent-block"]

    def test_hwr_dt_010_rules(self) -> None:
        """HWR-DT-010: 必載過重的 rule 與已有 gate 的段落各自產生減量建議"""
        snap = make_snapshot()
        snap["rules"] = {  # type: ignore[index]
            "files": [
                {"file": ".claude/rules/50.md", "chars": 40000, "always_loaded": True},
                {"file": ".claude/rules/20.md", "chars": 40000, "always_loaded": False},
            ],
            "candidates": [
                {
                    "file": ".claude/rules/03.md",
                    "line": 5,
                    "section": "禁止 cd",
                    "chars": 300,
                    "score": 4,
                    "already_gated": ["protect-bash-cd.py"],
                }
            ],
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds[".claude/rules/50.md"] == "rule-heavy"
        assert ".claude/rules/20.md" not in kinds
        assert kinds[".claude/rules/03.md:5"] == "rule-already-gated"


class TestCollectors:
    def test_hwr_st_001_hook_events(self, tmp_path: Path) -> None:
        """HWR-ST-001: 依 outcome 計數、觀察期外的紀錄排除、秒級解析度偵測"""
        lines = [
            {"ts": "2026-09-29T00:00:00Z", "hook": "a.sh", "outcome": "block", "ms": 1000},
            {
                "ts": "2026-09-29T00:00:01Z",
                "hook": "a.sh",
                "outcome": "error",
                "ms": 0,
                "msg": "boom",
            },
            {"ts": "2026-09-29T00:00:02Z", "hook": "a.sh", "outcome": "pass", "ms": 2000},
            {"ts": "2026-08-01T00:00:00Z", "hook": "a.sh", "outcome": "block", "ms": 0},
        ]
        (tmp_path / "demo-2026-09.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\nnot json\n"
        )
        since = hr.parse_ts("2026-09-20T00:00:00Z")
        assert since is not None
        data, warnings = hr.collect_hook_events(tmp_path, "demo", since)
        a = data["hooks"]["a.sh"]
        assert (a["calls"], a["block"], a["error"], a["pass"]) == (3, 1, 1, 1)
        assert a["error_sample"] == "boom"
        assert data["resolution"] == "second"
        assert any("秒級" in w for w in warnings)
        assert any("格式錯誤" in w for w in warnings)

    def test_hwr_st_002_transcript_blocks(self, tmp_path: Path) -> None:
        """HWR-ST-002: 抽出 tool_result 與 attachment 兩種阻擋、uuid 去重、排除同前綴的其他 repo"""
        repo = tmp_path / "work" / "demo"
        repo.mkdir(parents=True)
        projects = tmp_path / "projects"
        slug = hr.project_slug(repo)
        events = [
            {
                "type": "user",
                "uuid": "u1",
                "timestamp": "2026-09-29T00:00:00Z",
                "sessionId": "s1",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": "PreToolUse:Bash hook error: [bash run-hook.sh --python protect-bash-cd.py]: No stderr output",
                        }
                    ]
                },
            },
            {
                "type": "attachment",
                "uuid": "u2",
                "timestamp": "2026-09-29T00:00:01Z",
                "sessionId": "s1",
                "attachment": {
                    "type": "hook_blocking_error",
                    "blockingError": {"command": "bash x/check.sh", "blockingError": "nope"},
                },
            },
            {
                "type": "attachment",
                "uuid": "u3",
                "timestamp": "2026-09-29T00:00:02Z",
                "sessionId": "s2",
                "attachment": {
                    "type": "hook_non_blocking_error",
                    "command": "bash x/check.sh",
                    "exitCode": 127,
                    "stderr": "not found",
                },
            },
        ]
        for name in (slug, slug + "--claude-worktrees-wt"):
            d = projects / name
            d.mkdir(parents=True)
            (d / "s.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
        other = projects / (slug + "-other")
        other.mkdir()
        (other / "s.jsonl").write_text(json.dumps(events[0] | {"uuid": "zzz"}) + "\n")
        since = hr.parse_ts("2026-09-01T00:00:00Z")
        assert since is not None
        data, warnings = hr.collect_transcript_blocks(projects, repo, since)
        assert warnings == []
        assert data["files"] == 2
        cd = data["hooks"]["protect-bash-cd.py"]
        assert (cd["block"], cd["no_stderr"]) == (1, 1)
        chk = data["hooks"]["check.sh"]
        assert (chk["block"], chk["error"], chk["sessions"]) == (1, 1, 2)
        assert cd["versions"] == {}

    def test_hwr_st_005_transcript_plugin_version(self, tmp_path: Path) -> None:
        """HWR-ST-005: 從 plugin 快取路徑記下版本，依版本分開計數"""
        repo = tmp_path / "demo"
        repo.mkdir()
        d = tmp_path / "projects" / hr.project_slug(repo)
        d.mkdir(parents=True)
        rows = []
        for i, (ver, msg) in enumerate([("1.20.1", "No stderr output"), ("1.23.5", "BLOCKED: x")]):
            rows.append(
                {
                    "type": "user",
                    "uuid": f"u{i}",
                    "timestamp": "2026-09-29T00:00:00Z",
                    "sessionId": "s",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "content": f'PreToolUse:Bash hook error: [bash "/h/.claude/plugins/cache/yibi-stack/harness/{ver}/hooks/ap1.sh"]: {msg}',
                            }
                        ]
                    },
                }
            )
        (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        since = hr.parse_ts("2026-09-01T00:00:00Z")
        assert since is not None
        data, _ = hr.collect_transcript_blocks(tmp_path / "projects", repo, since)
        versions = data["hooks"]["ap1.sh"]["versions"]
        assert versions["1.20.1"]["no_stderr"] == 1 and versions["1.23.5"]["no_stderr"] == 0

    def test_hwr_st_003_collect_and_report_end_to_end(self, tmp_path: Path) -> None:
        """HWR-ST-003: collect（--no-ci）→ report 產出快照、報告與 lesson 候選"""
        repo = tmp_path / "demo"
        git_init(repo)
        (repo / ".claude" / "hooks").mkdir(parents=True)
        (repo / ".claude" / "rules").mkdir()
        (repo / ".claude" / "hooks" / "orphan.sh").write_text("#!/bin/bash\n")
        (repo / ".claude" / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "bash run-hook.sh protect-env.sh",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        )
        (repo / ".claude" / "rules" / "big.md").write_text(
            '---\npaths:\n  - "**"\n---\n' + "字" * 9000
        )
        (repo / "CLAUDE.md").write_text("# demo\n")
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "demo-2026-09.jsonl").write_text(
            json.dumps(
                {"ts": "2026-09-20T00:00:00Z", "hook": "protect-env.sh", "outcome": "pass", "ms": 5}
            )
            + "\n"
        )
        snap_path = tmp_path / "out" / "snap.json"
        rc = hr.main(
            [
                "collect",
                "--repo",
                str(repo),
                "--out",
                str(snap_path),
                "--no-ci",
                "--events-dir",
                str(events_dir),
                "--projects-dir",
                str(tmp_path / "none"),
                "--now",
                "2026-09-26T00:00:00Z",
            ]
        )
        assert rc == 3  # transcript 找不到 → 量測不完整，但快照照樣寫出
        snap = json.loads(snap_path.read_text())
        assert snap["metrics"]["always_loaded_chars"] > 9000
        kinds = rec_kinds(snap["recommendations"])
        assert kinds["orphan.sh"] == "hook-unregistered"
        assert kinds[".claude/rules/big.md"] == "rule-heavy"
        report, lessons = tmp_path / "out" / "r.md", tmp_path / "out" / "l.jsonl"
        assert (
            hr.main(
                [
                    "report",
                    "--snapshot",
                    str(snap_path),
                    "--out",
                    str(report),
                    "--lessons-out",
                    str(lessons),
                ]
            )
            == 0
        )
        text = report.read_text()
        assert "量測不完整" in text and "orphan.sh" in text
        keys = [json.loads(line)["key"] for line in lessons.read_text().splitlines()]
        assert all(k.startswith("harness-weekly-") for k in keys) and keys

    def test_hwr_st_004_week_over_week(self) -> None:
        """HWR-ST-004: new／persisting 累計週數／resolved，達門檻升級為 owner 裁決"""
        prev = {
            "metrics": {"m": 10},
            "recommendations": [{"id": "a", "weeks": 2}, {"id": "gone", "weeks": 1}],
        }
        curr = {"metrics": {"m": 7}, "recommendations": [{"id": "a"}, {"id": "b"}]}
        delta = hr.diff_snapshots(prev, curr, escalate_weeks=3)
        by_id = {s["id"]: s for s in delta["statuses"]}
        assert by_id["a"] == {"id": "a", "status": "persisting", "weeks": 3, "escalate": True}
        assert by_id["b"]["status"] == "new" and not by_id["b"]["escalate"]
        assert by_id["gone"]["status"] == "resolved"
        assert delta["metrics"]["m"] == {"prev": 10, "curr": 7, "delta": -3}


class TestValidation:
    def test_hwr_vl_001_not_git_repo(self, tmp_path: Path) -> None:
        """HWR-VL-001: 非 git 目錄 exit 2"""
        assert (
            hr.main(
                ["collect", "--repo", str(tmp_path), "--out", str(tmp_path / "s.json"), "--no-ci"]
            )
            == 2
        )

    def test_hwr_vl_002_missing_snapshot(self, tmp_path: Path) -> None:
        """HWR-VL-002: 快照不存在或版本不符 exit 2"""
        assert (
            hr.main(
                [
                    "report",
                    "--snapshot",
                    str(tmp_path / "nope.json"),
                    "--out",
                    str(tmp_path / "r.md"),
                    "--lessons-out",
                    str(tmp_path / "l.jsonl"),
                ]
            )
            == 2
        )
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"version": 999}))
        assert hr.main(["diff", "--snapshot", str(bad)]) == 2

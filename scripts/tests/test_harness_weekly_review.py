"""HWR: harness-weekly-review 的量測、建議與週對週比對測試。

Test ID 規則見 .claude/rules/09-test-conventions.md。mock 只放在外部邊界
（subprocess.run、以 tmp_path 建的檔案系統），不 mock 本 repo 的函式。

覆蓋對映：
- rule `paths:` 解析（清單式、inline、無 frontmatter、跨行陷阱）：HWR-DT-001
- hook 指令 → hook 名稱（run-hook launcher、直接呼叫、inline）：HWR-DT-002
- 建議分類（保險型 vs 低訊號、涵蓋不足時抑制、錯誤率、秒級計時門檻、silent block、
  gate 未接 CI 與 0 失敗、CI 未量測時不判 gate-silent 及其正向對照、rule 過重、
  段落已有 gate、高噪 step、粗體子段、舊版 plugin 快取）：HWR-DT-003..013
- CI 量測完整性（runs 第 1 頁失敗、逾時、jobs 讀取失敗不寫快取、jobs 筆數不符、
  1000 筆上限、runs 頁不是 JSON；正向對照：全部讀到才 measured）：HWR-DT-014..019
- gate 失敗歸因（workflow step 解析、以 step 名稱歸因、無法歸因不判 gate-silent）：HWR-DT-020..021
- --no-ci 時已接 CI 的 gate 不判 gate-silent 且報告註明：HWR-DT-022
- hook-events 涵蓋判定（最早晚於起點、觀察期內無紀錄、紀錄中斷、正向對照）：HWR-DT-023
- hook-events 檔名只收 `<repo>-YYYY-MM.jsonl`：HWR-DT-024
- 共用模組不算未註冊、settings.local.json 註冊合併：HWR-DT-025
- transcript slug 把 `_` 等非英數字元換成 `-`：HWR-DT-026
- rule 建議 id 不含行號，前文增刪行後仍穩定：HWR-DT-027
- ISO 週相鄰判定（W52／W53 跨年）：HWR-DT-028
- hook-events 彙總與秒級解析度偵測（秒級只是 note）：HWR-ST-001
- transcript 阻擋抽取（兩種形狀、uuid 去重、只收本 repo 與 worktree）：HWR-ST-002
- collect → report 端對端（快照、報告、lesson 候選）：HWR-ST-003
- 週對週比對（new／persisting／resolved／升級）：HWR-ST-004
- transcript 記下 plugin 版本：HWR-ST-005
- 本週量不到的建議標 unmeasured、週數帶到下週：HWR-ST-006
- 連續三週走真的 report --prev auto，第 3 週升級：HWR-ST-007
- 缺週時週數重算並標記、同週重跑不累加：HWR-ST-008
- AC-1：collect／report 只呼叫 git／gh、只寫指定檔案、每個外部呼叫都帶 timeout：HWR-ST-009
- write-lessons：list args、反引號原樣傳入、任一筆失敗 exit 1：HWR-ST-010
- 只有 notes（秒級計時、資料齊全）時 collect exit 0：HWR-ST-011
- 在 worktree 內執行時 transcript slug 與 repo 名稱取主 repo：HWR-ST-012
- 非 git repo、缺快照、缺 lesson 檔 fail loud：HWR-VL-001..003
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

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

REAL_RUN = subprocess.run
GH_OK = "o/r\n"


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


def make_snapshot() -> dict[str, Any]:
    return {
        "window": {"gate_since": "2026-07-01T00:00:00+00:00", "label": "2026-W40"},
        "hooks": {
            "inventory": {"registered": {}, "on_disk": [], "unregistered": [], "complete": True},
            "events": {"files": 1, "hooks": {}, "resolution": "ms", "covers_window": True},
            "transcript": {"files": 1, "hooks": {}},
        },
        "ci": {"inventory": {"gates": []}, "failures": {"jobs": {}}, "measured": True},
        "rules": {"files": [], "candidates": []},
    }


def rec_kinds(recs: list[dict[str, Any]]) -> dict[str, str]:
    """target → kind；同一 target 出現多種建議時直接失敗，避免後者靜默覆蓋前者。"""
    out: dict[str, str] = {}
    for r in recs:
        assert r["target"] not in out, f"同一 target 多條建議：{r['target']}"
        out[str(r["target"])] = str(r["kind"])
    return out


def git_init(path: Path) -> None:
    REAL_RUN(["git", "init", "-q", str(path)], check=True)


def git_commit_all(path: Path, date: str = "2026-01-01T00:00:00") -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    REAL_RUN(["git", "-C", str(path), "add", "-A"], check=True)
    REAL_RUN(
        ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"],
        check=True,
        env=env,
    )


def cp(args: list[str], rc: int = 0, out: str = "", err: str = "") -> Any:
    return subprocess.CompletedProcess(args, rc, out, err)


def make_gh(
    runs: list[dict[str, Any]] | None = None,
    jobs: dict[int, str] | None = None,
    runs_rc: int = 0,
    runs_exc: BaseException | None = None,
    runs_out: str | None = None,
) -> Callable[[list[str]], Any]:
    """偽造 gh 的外部回應：repo view、runs 列表、每個 run 的 jobs（原樣輸出字串）。"""

    def handler(args: list[str]) -> Any:
        if args[1:3] == ["repo", "view"]:
            return cp(args, 0, GH_OK)
        if "--paginate" in args:
            run_id = int(args[3].split("/runs/")[1].split("/")[0])
            return cp(args, 0, (jobs or {}).get(run_id, '{"total_count":0,"jobs":[]}'))
        if runs_exc is not None:
            raise runs_exc
        if runs_rc:
            return cp(args, runs_rc, "", "HTTP 502")
        if runs_out is not None:
            return cp(args, 0, runs_out)
        return cp(args, 0, json.dumps({"workflow_runs": runs or []}))

    return handler


def install_fake_run(
    monkeypatch: pytest.MonkeyPatch,
    gh: Callable[[list[str]], Any],
    calls: list[tuple[list[str], dict[str, Any]]],
) -> None:
    """只替換外部邊界 subprocess.run：git 照常執行，gh 走偽造回應，全部記錄下來。"""

    def fake(args: list[str], **kw: Any) -> Any:
        calls.append((list(args), kw))
        if args[0] == "gh":
            return gh(list(args))
        return REAL_RUN(args, **kw)

    monkeypatch.setattr(hr.subprocess, "run", fake)


def make_gate_repo(tmp_path: Path, workflow: str | None = None) -> Path:
    """建一個有 gate script、接進 workflow、上線日期夠久的 repo。"""
    repo = tmp_path / "demo"
    git_init(repo)
    (repo / "scripts" / "harness").mkdir(parents=True)
    (repo / "scripts" / "harness" / "rule-gate-alpha.py").write_text("print(1)\n")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text(
        workflow
        or (
            "jobs:\n  check:\n    steps:\n"
            "      - name: Check things\n"
            "        run: python scripts/harness/rule-gate-alpha.py\n"
        )
    )
    git_commit_all(repo)
    return repo


def collect_args(repo: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "collect",
        "--repo",
        str(repo),
        "--out",
        str(tmp_path / "out" / "snap.json"),
        "--events-dir",
        str(tmp_path / "events"),
        "--projects-dir",
        str(tmp_path / "projects"),
        "--now",
        "2026-09-30T00:00:00Z",
        *extra,
    ]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


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

    def test_hwr_dt_020_workflow_steps(self) -> None:
        """HWR-DT-020: step 名稱取 name:；沒寫 name 時照 GitHub 規則推成「Run <第一行>」"""
        text = (
            "jobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@v7\n"
            "      - name: Gate A\n        run: python scripts/harness/rule-gate-a.py\n"
            "      - run: bash scripts/harness/ci-check-b.sh --x\n"
            "      - name: Multi\n        run: |\n          echo hi\n"
            "          python scripts/harness/rule-gate-c.py\n"
        )
        steps = {s["name"]: s["run"] for s in hr.workflow_steps(text)}
        assert set(steps) == {"Gate A", "Run bash scripts/harness/ci-check-b.sh --x", "Multi"}
        assert "rule-gate-c.py" in steps["Multi"]

    def test_hwr_dt_028_week_relation(self) -> None:
        """HWR-DT-028: 只有正好前一個 ISO 週才算相鄰；跨年 W52／W53 → W01 依實際週數判定"""
        assert hr.week_relation("2026-W39", "2026-W40") == "next"
        assert hr.week_relation("2026-W40", "2026-W40") == "same"
        assert hr.week_relation("2026-W35", "2026-W40") == "gap"
        assert hr.week_relation("2026-W53", "2027-W01") == "next"  # 2026 有 W53
        assert hr.week_relation("2026-W52", "2027-W01") == "gap"
        assert hr.week_relation("2025-W52", "2026-W01") == "next"  # 2025 沒有 W53
        assert hr.week_relation("2025-W53", "2026-W01") == "gap"  # 不存在的週
        assert hr.week_relation("2026-W41", "2026-W40") == "gap"


class TestRecommendations:
    def test_hwr_dt_003_insurance_vs_low_signal(self) -> None:
        """HWR-DT-003: 0 攔截時 protect-* 列為保留，一般 hook 列為退役候選"""
        snap = make_snapshot()
        snap["hooks"]["inventory"]["registered"] = {"protect-env.sh": {}, "figma-check.sh": {}}
        snap["hooks"]["events"]["hooks"] = {
            "protect-env.sh": make_event_stats(),
            "figma-check.sh": make_event_stats(),
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds["protect-env.sh"] == "hook-insurance-idle"
        assert kinds["figma-check.sh"] == "hook-low-signal"

    def test_hwr_dt_004_coverage_gap_suppresses_conclusions(self) -> None:
        """HWR-DT-004: 紀錄未涵蓋觀察期時，不產出沒資料與低訊號建議，且這兩類不列為可判定"""
        snap = make_snapshot()
        snap["hooks"]["events"]["covers_window"] = False
        snap["hooks"]["inventory"]["registered"] = {"a.sh": {}, "b.sh": {}}
        snap["hooks"]["events"]["hooks"] = {"a.sh": make_event_stats()}
        assert hr.build_recommendations(snap, make_thresholds()) == []
        kinds = hr.evaluation_scope(snap)["kinds"]
        assert "hook-no-data" not in kinds and "hook-low-signal" not in kinds
        snap["hooks"]["events"]["covers_window"] = True  # 正向對照
        got = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert got == {"a.sh": "hook-low-signal", "b.sh": "hook-no-data"}

    def test_hwr_dt_005_error_rate(self) -> None:
        """HWR-DT-005: hook 自身錯誤率達門檻才列修正，低於門檻不列"""
        snap = make_snapshot()
        snap["hooks"]["inventory"]["registered"] = {"a.sh": {}, "b.sh": {}}
        snap["hooks"]["events"]["hooks"] = {
            "a.sh": make_event_stats(calls=20, error=2, error_rate=0.1, warn=1),
            "b.sh": make_event_stats(calls=100, error=1, error_rate=0.01, warn=1),
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds.get("a.sh") == "hook-error"
        assert "b.sh" not in kinds

    def test_hwr_dt_006_second_resolution_raises_slow_threshold(self) -> None:
        """HWR-DT-006: 秒級計時下 1000ms 讀值不算慢，2000ms 才算"""
        snap = make_snapshot()
        snap["hooks"]["events"]["resolution"] = "second"
        snap["hooks"]["inventory"]["registered"] = {"a.sh": {}, "b.sh": {}}
        snap["hooks"]["events"]["hooks"] = {
            "a.sh": make_event_stats(p95_ms=1000, warn=1),
            "b.sh": make_event_stats(p95_ms=2000, warn=1),
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert "a.sh" not in kinds
        assert kinds["b.sh"] == "hook-slow"

    def test_hwr_dt_007_silent_block(self) -> None:
        """HWR-DT-007: 過半阻擋沒有 stderr 時列為修正"""
        snap = make_snapshot()
        snap["hooks"]["transcript"]["hooks"] = {
            "x.py": {"block": 10, "no_stderr": 9},
            "y.py": {"block": 10, "no_stderr": 1},
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds["x.py"] == "hook-silent-block"
        assert "y.py" not in kinds

    def test_hwr_dt_008_gate_unwired_and_silent(self) -> None:
        """HWR-DT-008: 沒接 CI 的 gate 列修正；上線夠久且 0 失敗列退役候選；太新或有失敗不列"""
        snap = make_snapshot()
        snap["ci"]["inventory"]["gates"] = [
            {"script": "rule-gate-a.py", "wired_in_ci": False, "added": "2026-01-01"},
            {
                "script": "rule-gate-b.py",
                "wired_in_ci": True,
                "ci_steps": ["Gate B"],
                "added": "2026-01-01",
            },
            {
                "script": "rule-gate-c.py",
                "wired_in_ci": True,
                "ci_steps": ["Gate C"],
                "added": "2026-09-01",
            },
            {
                "script": "rule-gate-d.py",
                "wired_in_ci": True,
                "ci_steps": ["Gate D"],
                "added": "2026-01-01",
            },
        ]
        snap["ci"]["failures"]["jobs"] = {
            "CI / Gates": {"failures": 3, "branches": 2, "steps": {"rule-gate-d self-test": 3}}
        }
        kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
        assert kinds["rule-gate-a.py"] == "gate-unwired"
        assert kinds["rule-gate-b.py"] == "gate-silent"
        assert "rule-gate-c.py" not in kinds
        assert "rule-gate-d.py" not in kinds

    def test_hwr_dt_009_ci_unmeasured_skips_silent_gate(self) -> None:
        """HWR-DT-009: CI 沒量到時不可把 gate 判成 0 失敗；measured=True 的對照會產生 gate-silent"""
        snap = make_snapshot()
        snap["ci"]["inventory"]["gates"] = [
            {
                "script": "rule-gate-b.py",
                "wired_in_ci": True,
                "ci_steps": ["Gate B"],
                "added": "2026-01-01",
            }
        ]
        snap["ci"]["measured"] = False
        assert hr.build_recommendations(snap, make_thresholds()) == []
        snap["ci"]["measured"] = True
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {
            "rule-gate-b.py": "gate-silent"
        }

    def test_hwr_dt_010_rules(self) -> None:
        """HWR-DT-010: 必載過重的 rule 與已有 gate 的段落各自產生減量建議；id 用段落標題"""
        snap = make_snapshot()
        snap["rules"] = {
            "files": [
                {"file": ".claude/rules/50.md", "chars": 40000, "always_loaded": True},
                {"file": ".claude/rules/20.md", "chars": 40000, "always_loaded": False},
            ],
            "candidates": [
                {
                    "file": ".claude/rules/03.md",
                    "anchor": ".claude/rules/03.md#禁止 cd",
                    "line": 5,
                    "section": "禁止 cd",
                    "chars": 300,
                    "score": 4,
                    "already_gated": ["protect-bash-cd.py"],
                }
            ],
        }
        recs = hr.build_recommendations(snap, make_thresholds())
        kinds = rec_kinds(recs)
        assert kinds[".claude/rules/50.md"] == "rule-heavy"
        assert ".claude/rules/20.md" not in kinds
        assert kinds[".claude/rules/03.md#禁止 cd"] == "rule-already-gated"
        gated = next(r for r in recs if r["kind"] == "rule-already-gated")
        assert gated["location"] == ".claude/rules/03.md:5"

    def test_hwr_dt_011_noisy_step_ignores_rollup(self) -> None:
        """HWR-DT-011: 高噪以 step 為單位；rollup job 與未達門檻的 step 不列"""
        snap = make_snapshot()
        snap["ci"]["failures"]["jobs"] = {
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
            "bash-ap1.sh": {
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
        snap["hooks"]["transcript"]["hooks"]["bash-ap1.sh"]["versions"]["1.23.5"]["no_stderr"] = 5
        kinds = [r["kind"] for r in hr.build_recommendations(snap, make_thresholds())]
        assert kinds == ["hook-stale-plugin", "hook-silent-block"]

    def test_hwr_dt_021_gate_attribution(self) -> None:
        """HWR-DT-021: failed step 名稱對到呼叫 gate 的 step 即歸因；找不到可歸因 step 不判 gate-silent"""
        snap = make_snapshot()
        snap["ci"]["inventory"]["gates"] = [
            {
                "script": "rule-gate-alpha.py",
                "wired_in_ci": True,
                "ci_steps": ["Check things"],
                "added": "2026-01-01",
            },
            {
                "script": "rule-gate-beta.py",
                "wired_in_ci": True,
                "ci_steps": [],
                "added": "2026-01-01",
            },
        ]
        snap["ci"]["failures"]["jobs"] = {
            "CI / check": {"failures": 2, "branches": 1, "steps": {"check THINGS": 2}}
        }
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {}
        assert hr.evaluation_scope(snap)["unevaluated_ids"] == ["gate-silent:rule-gate-beta.py"]
        snap["ci"]["failures"]["jobs"] = {}  # 對照：可歸因的 gate 0 失敗才判 gate-silent
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {
            "rule-gate-alpha.py": "gate-silent"
        }


class TestCiCompleteness:
    def _collect(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        gh: Callable[[list[str]], Any],
        *extra: str,
    ) -> tuple[int, dict[str, Any], list[tuple[list[str], dict[str, Any]]]]:
        repo = make_gate_repo(tmp_path)
        calls: list[tuple[list[str], dict[str, Any]]] = []
        install_fake_run(monkeypatch, gh, calls)
        rc = hr.main(collect_args(repo, tmp_path, *extra))
        return rc, load(tmp_path / "out" / "snap.json"), calls

    def test_hwr_dt_014_runs_page_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-014: runs 第 1 頁讀取失敗 → CI 未量測、不判 gate-silent、ci_gate_failures 為 None"""
        rc, snap, _ = self._collect(tmp_path, monkeypatch, make_gh(runs_rc=1))
        assert rc == 3
        assert snap["ci"]["measured"] is False
        assert snap["metrics"]["ci_gate_failures"] is None
        assert "gate-silent" not in {r["kind"] for r in snap["recommendations"]}
        assert "gate-silent" not in snap["evaluation"]["kinds"]

    def test_hwr_dt_014b_runs_page_not_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-014: runs 頁 exit 0 但內容不是 JSON（如 proxy 錯誤頁）→ CI 未量測"""
        _, snap, _ = self._collect(tmp_path, monkeypatch, make_gh(runs_out="<html>502</html>"))
        assert snap["ci"]["measured"] is False
        assert "gate-silent" not in {r["kind"] for r in snap["recommendations"]}

    def test_hwr_dt_015_all_read_is_measured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-015: 正向對照——CI 全部讀到才 measured，同一個 fixture 會產生 gate-silent"""
        rc, snap, _ = self._collect(tmp_path, monkeypatch, make_gh(runs=[]))
        assert snap["ci"]["measured"] is True
        assert snap["metrics"]["ci_gate_failures"] == 0
        assert rec_kinds(snap["recommendations"])["rule-gate-alpha.py"] == "gate-silent"
        assert rc == 3  # hook-events 與 transcript 在 fixture 中不存在

    def test_hwr_dt_016_runs_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """HWR-DT-016: gh 逾時視為讀取失敗，CI 未量測"""
        exc = subprocess.TimeoutExpired(["gh"], 60)
        _, snap, _ = self._collect(tmp_path, monkeypatch, make_gh(runs_exc=exc))
        assert snap["ci"]["measured"] is False
        assert any("逾時" in w for w in snap["warnings"])

    def test_hwr_dt_017_jobs_failure_not_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-017: jobs 讀取失敗 → CI 未量測，且不寫進快取（下週會重抓）"""
        runs = [{"id": 7, "name": "CI", "head_branch": "x", "created_at": "2026-09-01"}]
        cache = tmp_path / "cache.json"

        def gh(args: list[str]) -> Any:
            if "--paginate" in args:
                return cp(args, 1, "", "HTTP 500")
            return make_gh(runs=runs)(args)

        _, snap, _ = self._collect(tmp_path, monkeypatch, gh, "--ci-cache", str(cache))
        assert snap["ci"]["measured"] is False
        assert "7" not in load(cache)

    def test_hwr_dt_018_jobs_incomplete_not_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-018: jobs 筆數少於 total_count（分頁沒讀完）→ 不完整、不快取；筆數相符才快取"""
        runs = [
            {"id": 7, "name": "CI", "head_branch": "x", "created_at": "2026-09-01"},
            {"id": 8, "name": "CI", "head_branch": "x", "created_at": "2026-09-02"},
        ]
        job = {"name": "check", "conclusion": "failure", "steps": []}
        page1 = json.dumps({"total_count": 2, "jobs": [job]})
        page2 = json.dumps({"total_count": 2, "jobs": [job]})
        jobs = {7: json.dumps({"total_count": 2, "jobs": [job]}), 8: page1 + "\n" + page2 + "\n"}
        cache = tmp_path / "cache.json"
        _, snap, _ = self._collect(
            tmp_path, monkeypatch, make_gh(runs=runs, jobs=jobs), "--ci-cache", str(cache)
        )
        assert snap["ci"]["measured"] is False
        assert set(load(cache)) == {"8"}

    def test_hwr_dt_019_runs_cap(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """HWR-DT-019: runs 翻滿 1000 筆上限 → 可能漏掉較早的失敗，CI 未量測"""
        runs = [
            {"id": i, "name": "CI", "head_branch": "x", "created_at": "2026-09-01"}
            for i in range(100)
        ]
        _, snap, _ = self._collect(tmp_path, monkeypatch, make_gh(runs=runs))
        assert snap["ci"]["measured"] is False
        assert any("上限" in w for w in snap["warnings"])

    def test_hwr_dt_022_no_ci_with_wired_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-022: --no-ci 時已接 CI 的 gate 不判 gate-silent，報告註明 CI 未量測"""
        rc, snap, calls = self._collect(tmp_path, monkeypatch, make_gh(), "--no-ci")
        assert not [c for c, _ in calls if c[0] == "gh"]
        assert snap["ci"]["measured"] is False
        assert snap["metrics"]["ci_gate_failures"] is None
        assert "gate-silent" not in {r["kind"] for r in snap["recommendations"]}
        assert any("--no-ci" in n for n in snap["notes"])
        report = tmp_path / "out" / "r.md"
        snap_path = str(tmp_path / "out" / "snap.json")
        lessons = str(tmp_path / "out" / "l.jsonl")
        hr.main(["report", "--snapshot", snap_path, "--out", str(report), "--lessons-out", lessons])
        text = report.read_text()
        assert "CI 未量測" in text
        assert "| ci_gate_failures | - | 未量測 | - |" in text


class TestCollectors:
    def test_hwr_st_001_hook_events(self, tmp_path: Path) -> None:
        """HWR-ST-001: 依 outcome 計數、觀察期外的紀錄排除、秒級解析度只是 note"""
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
        since, now = hr.parse_ts("2026-09-20T00:00:00Z"), hr.parse_ts("2026-09-30T00:00:00Z")
        assert since is not None and now is not None
        data, warnings, notes = hr.collect_hook_events(tmp_path, "demo", since, now)
        a = data["hooks"]["a.sh"]
        assert (a["calls"], a["block"], a["error"], a["pass"]) == (3, 1, 1, 1)
        assert a["error_sample"] == "boom"
        assert data["resolution"] == "second"
        assert any("秒級" in n for n in notes)
        assert not any("秒級" in w for w in warnings)
        assert any("格式錯誤" in w for w in warnings)

    def test_hwr_dt_023_covers_window(self, tmp_path: Path) -> None:
        """HWR-DT-023: 涵蓋需同時滿足最早 <= 起點、觀察期內有紀錄、最新一筆距今 2 天內"""
        since, now = hr.parse_ts("2026-09-23T00:00:00Z"), hr.parse_ts("2026-09-30T00:00:00Z")
        assert since is not None and now is not None

        def covers(*stamps: str) -> bool:
            d = tmp_path / stamps[0][:10]
            d.mkdir()
            rows = [{"ts": s, "hook": "a.sh", "outcome": "pass", "ms": 5} for s in stamps]
            (d / "demo-2026-09.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            data, warnings, _ = hr.collect_hook_events(d, "demo", since, now)
            assert data["covers_window"] is (not any("未涵蓋" in w for w in warnings))
            return bool(data["covers_window"])

        # 正向對照
        assert covers("2026-09-22T00:00:00Z", "2026-09-29T00:00:00Z") is True
        # 最早一筆晚於起點 1 天（舊版 20% 容許會放行）
        assert covers("2026-09-24T00:00:00Z", "2026-09-29T12:00:00Z") is False
        # 觀察期內沒有任何紀錄
        assert covers("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z") is False
        # 最早與最新都合格，但觀察期內 0 筆（例如時鐘偏移讓紀錄落在 now 之後）
        assert covers("2026-09-10T00:00:00Z", "2026-09-30T12:00:00Z") is False
        # 最新一筆距今超過 2 天（logging 中斷）
        assert covers("2026-09-21T00:00:00Z", "2026-09-25T00:00:00Z") is False

    def test_hwr_dt_024_event_file_selection(self, tmp_path: Path) -> None:
        """HWR-DT-024: 只收 `<repo>-YYYY-MM.jsonl`，`<repo>-other-YYYY-MM.jsonl` 是別的 repo"""
        row = {"ts": "2026-09-29T00:00:00Z", "hook": "a.sh", "outcome": "pass", "ms": 5}
        (tmp_path / "demo-2026-09.jsonl").write_text(json.dumps(row) + "\n")
        (tmp_path / "demo-other-2026-09.jsonl").write_text(json.dumps(row) + "\n")
        since, now = hr.parse_ts("2026-09-20T00:00:00Z"), hr.parse_ts("2026-09-30T00:00:00Z")
        assert since is not None and now is not None
        data, _, _ = hr.collect_hook_events(tmp_path, "demo", since, now)
        assert data["files"] == 1
        assert data["hooks"]["a.sh"]["calls"] == 1

    def test_hwr_dt_025_hook_inventory(self, tmp_path: Path) -> None:
        """HWR-DT-025: 共用模組（_ 開頭、被 source／import／直接呼叫）不算未註冊；local 註冊有合併"""
        hooks = tmp_path / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "_helper.py").write_text("x = 1\n")
        (hooks / "lib.sh").write_text("f() { :; }\n")
        (hooks / "mod.py").write_text("y = 1\n")
        (hooks / "delegate.py").write_text("z = 1\n")
        (hooks / "a.sh").write_text(
            'source "$(dirname "$0")/lib.sh"\n'
            'python3 "$(dirname "$0")/delegate.py"\n'
            "# 註解提到 orphan.sh 不算引用\n"
        )
        (hooks / "b.py").write_text("from mod import y\n")
        (hooks / "orphan.sh").write_text("#!/bin/bash\n")
        (hooks / "local.sh").write_text("#!/bin/bash\n")
        settings = {"hooks": {"PreToolUse": [{"hooks": [{"command": "bash a.sh"}]}]}}
        local = {"hooks": {"PreToolUse": [{"hooks": [{"command": "bash local.sh"}]}]}}
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings))
        (tmp_path / ".claude" / "settings.local.json").write_text(json.dumps(local))
        (hooks / "b.py").write_text("from mod import y\n")
        inv, warnings, notes = hr.collect_hook_inventory(tmp_path)
        assert set(inv["shared_modules"]) == {"_helper.py", "lib.sh", "mod.py", "delegate.py"}
        assert inv["unregistered"] == ["b.py", "orphan.sh"]
        assert inv["registered"]["local.sh"]["sources"] == ["settings.local.json"]
        assert warnings == [] and any("~/.claude/settings.json" in n for n in notes)

    def test_hwr_dt_026_project_slug(self, tmp_path: Path) -> None:
        """HWR-DT-026: slug 把 `_`、`.` 等非英數字元都換成 `-`（對齊 ~/.claude/projects 目錄名）"""
        repo = tmp_path / "my_repo.x"
        repo.mkdir()
        slug = hr.project_slug(repo)
        assert slug.endswith("-my-repo-x")
        assert all(ch.isalnum() or ch == "-" for ch in slug)

    def test_hwr_dt_027_rule_id_stable_across_line_shift(self, tmp_path: Path) -> None:
        """HWR-DT-027: 前文多一行後，rule 建議 id 不變（只有 location 行號變）"""
        rules = tmp_path / ".claude" / "rules"
        rules.mkdir(parents=True)
        body = "## 禁止 cd\n\n" + "必須 `a` `b` `c` `d`。不要 `e` `f` `g` `h`。一律 `i`。\n"
        (rules / "03.md").write_text("# T\n\n" + body)
        snap = make_snapshot()
        snap["rules"] = hr.collect_rules(tmp_path, set())
        before = hr.build_recommendations(snap, make_thresholds())
        (rules / "03.md").write_text("# T\n\n多一行\n\n" + body)
        snap["rules"] = hr.collect_rules(tmp_path, set())
        after = hr.build_recommendations(snap, make_thresholds())
        assert [r["id"] for r in before] == [r["id"] for r in after] != []
        assert [r["location"] for r in before] != [r["location"] for r in after]

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


def make_orphan_repo(tmp_path: Path) -> Path:
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
                                {"type": "command", "command": "bash run-hook.sh protect-env.sh"}
                            ],
                        }
                    ]
                }
            }
        )
    )
    (repo / ".claude" / "rules" / "big.md").write_text('---\npaths:\n  - "**"\n---\n' + "字" * 9000)
    (repo / "CLAUDE.md").write_text("# demo\n")
    return repo


class TestEndToEnd:
    def test_hwr_st_003_collect_and_report_end_to_end(self, tmp_path: Path) -> None:
        """HWR-ST-003: collect（--no-ci）→ report 產出快照、報告與 lesson 候選"""
        repo = make_orphan_repo(tmp_path)
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
        snap = load(snap_path)
        assert snap["metrics"]["always_loaded_chars"] > 9000
        kinds = rec_kinds(snap["recommendations"])
        assert kinds["orphan.sh"] == "hook-unregistered"
        assert kinds[".claude/rules/big.md"] == "rule-heavy"
        report, lessons = tmp_path / "out" / "r.md", tmp_path / "out" / "l.jsonl"
        args = ["report", "--snapshot", str(snap_path), "--out", str(report)]
        assert hr.main([*args, "--lessons-out", str(lessons)]) == 0
        text = report.read_text()
        assert "量測不完整" in text and "orphan.sh" in text
        rows = [json.loads(line) for line in lessons.read_text().splitlines()]
        assert rows and all(r["key"].startswith("harness-weekly-") for r in rows)
        assert all(r["project"] == "demo" and "bucket" in r for r in rows)

    def test_hwr_st_004_week_over_week(self) -> None:
        """HWR-ST-004: new／persisting 累計週數／resolved，達門檻升級為 owner 裁決"""
        prev = {
            "window": {"label": "2026-W39"},
            "metrics": {"m": 10},
            "recommendations": [
                {"id": "a:x", "kind": "a", "weeks": 2},
                {"id": "a:gone", "kind": "a", "weeks": 1},
            ],
        }
        curr = {
            "window": {"label": "2026-W40"},
            "evaluation": {"kinds": ["a"], "unevaluated_ids": []},
            "metrics": {"m": 7},
            "recommendations": [{"id": "a:x", "kind": "a"}, {"id": "a:new", "kind": "a"}],
        }
        delta = hr.diff_snapshots(prev, curr, escalate_weeks=3)
        by_id = {s["id"]: s for s in delta["statuses"]}
        assert by_id["a:x"] == {"id": "a:x", "status": "persisting", "weeks": 3, "escalate": True}
        assert by_id["a:new"]["status"] == "new" and not by_id["a:new"]["escalate"]
        assert by_id["a:gone"]["status"] == "resolved"
        assert delta["metrics"]["m"] == {"prev": 10, "curr": 7, "delta": -3}
        assert delta["week_gap"] is None

    def test_hwr_st_006_unmeasured_kind(self) -> None:
        """HWR-ST-006: 本週量不到的類型標 unmeasured、週數原樣帶到下週，不當成 resolved"""
        prev = {
            "window": {"label": "2026-W39"},
            "metrics": {},
            "recommendations": [
                {"id": "gate-silent:g.py", "kind": "gate-silent", "weeks": 2},
                {"id": "rule-heavy:r.md", "kind": "rule-heavy", "weeks": 1},
            ],
        }
        curr = {
            "window": {"label": "2026-W40"},
            "evaluation": {"kinds": ["rule-heavy"], "unevaluated_ids": []},
            "metrics": {},
            "recommendations": [],
        }
        delta = hr.diff_snapshots(prev, curr, escalate_weeks=3)
        by_id = {s["id"]: s for s in delta["statuses"]}
        assert by_id["gate-silent:g.py"]["status"] == "unmeasured"
        assert by_id["gate-silent:g.py"]["weeks"] == 2
        assert by_id["rule-heavy:r.md"]["status"] == "resolved"  # 對照：可判定且消失 → resolved
        assert [r["id"] for r in curr["carried"]] == ["gate-silent:g.py"]
        # 下一週重新量得到且仍成立：從帶過來的週數接續累加
        nxt = {
            "window": {"label": "2026-W41"},
            "evaluation": {"kinds": ["gate-silent"], "unevaluated_ids": []},
            "metrics": {},
            "recommendations": [{"id": "gate-silent:g.py", "kind": "gate-silent"}],
        }
        by_id = {s["id"]: s for s in hr.diff_snapshots(curr, nxt, 3)["statuses"]}
        assert by_id["gate-silent:g.py"] == {
            "id": "gate-silent:g.py",
            "status": "persisting",
            "weeks": 3,
            "escalate": True,
        }
        report = hr.render_report(
            {
                "repo_name": "demo",
                "window": {
                    "label": "2026-W40",
                    "since": "2026-09-23",
                    "until": "2026-09-30",
                    "gate_since": "2026-07-01",
                },
                "ci": {"measured": False},
                "warnings": [],
                "notes": [],
                "recommendations": [],
                "hooks": {"events": {"hooks": {}}},
            },
            delta,
        )
        assert "本週量不到的上週建議" in report and "gate-silent:g.py" in report

    def test_hwr_st_008_week_gap_and_same_week(self) -> None:
        """HWR-ST-008: 上次快照不相鄰時週數重算為 1 並標記；同週重跑不累加"""
        base = {
            "evaluation": {"kinds": ["a"], "unevaluated_ids": []},
            "metrics": {},
            "recommendations": [{"id": "a:x", "kind": "a"}],
        }
        prev = {"window": {"label": "2026-W35"}, "metrics": {}, "recommendations": []}
        prev["recommendations"] = [{"id": "a:x", "kind": "a", "weeks": 2}]
        gap = hr.diff_snapshots(prev, {**base, "window": {"label": "2026-W40"}}, 3)
        assert gap["statuses"][0]["weeks"] == 1 and gap["statuses"][0]["status"] == "new"
        assert gap["week_gap"] == {"prev": "2026-W35", "curr": "2026-W40"}
        same_prev = {**prev, "window": {"label": "2026-W40"}}
        curr = {**base, "window": {"label": "2026-W40"}, "recommendations": [{"id": "a:x"}]}
        same = hr.diff_snapshots(same_prev, curr, 3)
        assert same["statuses"][0]["weeks"] == 2 and same["week_gap"] is None
        boundary = {**prev, "window": {"label": "2026-W53"}}
        curr = {**base, "window": {"label": "2027-W01"}, "recommendations": [{"id": "a:x"}]}
        assert hr.diff_snapshots(boundary, curr, 3)["statuses"][0]["weeks"] == 3

    def test_hwr_st_007_three_week_escalation(self, tmp_path: Path) -> None:
        """HWR-ST-007: 連續三週走真的 collect → report --prev auto，第 3 週升級為 owner 裁決"""
        repo = make_orphan_repo(tmp_path)
        out = tmp_path / "out"
        results = []
        for label, now in (
            ("2026-W38", "2026-09-16T00:00:00Z"),
            ("2026-W39", "2026-09-23T00:00:00Z"),
            ("2026-W40", "2026-09-30T00:00:00Z"),
        ):
            snap = out / f"snapshot-{label}.json"
            args = ["collect", "--repo", str(repo), "--out", str(snap), "--no-ci", "--now", now]
            args += ["--events-dir", str(tmp_path / "ev"), "--projects-dir", str(tmp_path / "p")]
            assert hr.main(args) in (0, 3)
            report_args = ["report", "--snapshot", str(snap), "--prev", "auto"]
            report_args += ["--out", str(out / f"r-{label}.md")]
            report_args += ["--lessons-out", str(out / f"l-{label}.jsonl")]
            buf: list[str] = []
            rc = _capture_main(report_args, buf)
            assert rc == 0
            results.append(json.loads(buf[0]))
        assert results[0]["prev_status"] == "none"
        assert results[1]["prev"].endswith("snapshot-2026-W38.json")
        assert "hook-unregistered:orphan.sh" not in results[1]["escalated"]
        assert "hook-unregistered:orphan.sh" in results[2]["escalated"]
        assert "已連續 3 週" in (out / "r-2026-W40.md").read_text()

    def test_hwr_st_009_ac1_only_git_gh_and_expected_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-ST-009: AC-1——collect／report 只呼叫 git／gh、每個呼叫都帶 timeout、只寫指定檔案"""
        repo = make_gate_repo(tmp_path)
        before = set(tmp_path.rglob("*"))
        calls: list[tuple[list[str], dict[str, Any]]] = []
        install_fake_run(monkeypatch, make_gh(runs=[]), calls)
        cache = tmp_path / "out" / "cache.json"
        hr.main(collect_args(repo, tmp_path, "--ci-cache", str(cache)))
        snap = tmp_path / "out" / "snap.json"
        report, lessons = tmp_path / "out" / "r.md", tmp_path / "out" / "l.jsonl"
        args = ["report", "--snapshot", str(snap), "--out", str(report)]
        assert hr.main([*args, "--lessons-out", str(lessons)]) == 0
        assert {c[0] for c, _ in calls} == {"git", "gh"}
        assert all("timeout" in kw and "shell" not in kw for _, kw in calls)
        created = {p for p in tmp_path.rglob("*") if p.is_file()} - before
        assert created == {snap, cache, report, lessons}


def _capture_main(argv: list[str], buf: list[str]) -> int:
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = hr.main(argv)
    buf.append(out.getvalue())
    return int(rc)


class TestWriteLessons:
    def test_hwr_st_010_write_lessons(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """HWR-ST-010: list args 呼叫 mycelium、反引號與 $() 原樣傳入、任一筆失敗 exit 1 並印 [FAIL]"""
        insight = "`.claude/hooks/x.sh` 沒註冊 $(touch pwned) `paths:`"
        rows = [
            {"key": "k-ok", "type": "operational", "insight": insight, "project": "demo"},
            {"key": "k-bad", "type": "operational", "insight": "second insight", "project": "demo"},
            {"key": "k-skip", "type": "operational", "insight": "excluded one", "project": "demo"},
        ]
        path = tmp_path / "l.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        calls: list[tuple[Any, dict[str, Any]]] = []

        def fake(args: Any, **kw: Any) -> Any:
            calls.append((args, kw))
            rc = 1 if "k-bad" in args else 0
            return cp(list(args), rc, "", "ValidationError: boom" if rc else "")

        monkeypatch.setattr(hr.subprocess, "run", fake)
        rc = hr.main(["write-lessons", "--lessons", str(path), "--exclude", "k-skip"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "[FAIL] k-bad" in err and "k-ok" not in err
        assert len(calls) == 2
        args, kw = calls[0]
        assert isinstance(args, list) and args[:3] == ["mycelium", "lessons", "add"]
        assert args[args.index("--insight") + 1] == insight
        assert "--skip-if-exists" in args and args[args.index("--project") + 1] == "demo"
        assert kw.get("timeout") and not kw.get("shell")

    def test_hwr_st_010b_write_lessons_all_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-ST-010: 對照——全部成功時 exit 0"""
        path = tmp_path / "l.jsonl"
        path.write_text(
            json.dumps({"key": "k", "type": "operational", "insight": "fine one"}) + "\n"
        )
        monkeypatch.setattr(hr.subprocess, "run", lambda args, **kw: cp(list(args), 0))
        assert hr.main(["write-lessons", "--lessons", str(path)]) == 0

    def test_hwr_st_011_notes_only_exit_zero(self, tmp_path: Path) -> None:
        """HWR-ST-011: 資料源齊全、只有資訊性 notes（秒級計時、--no-ci）時 collect exit 0"""
        repo = make_orphan_repo(tmp_path)
        events = tmp_path / "events"
        events.mkdir()
        rows = [
            {"ts": ts, "hook": "protect-env.sh", "outcome": "pass", "ms": 1000}
            for ts in ("2026-09-22T00:00:00Z", "2026-09-29T00:00:00Z")
        ]
        (events / "demo-2026-09.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        proj = tmp_path / "projects" / hr.project_slug(repo)
        proj.mkdir(parents=True)
        (proj / "s.jsonl").write_text(json.dumps({"timestamp": "2026-09-29T00:00:00Z"}) + "\n")
        assert hr.main(collect_args(repo, tmp_path, "--no-ci")) == 0
        snap = load(tmp_path / "out" / "snap.json")
        assert snap["warnings"] == []
        assert any("秒級" in n for n in snap["notes"])


class TestWorktree:
    def test_hwr_st_012_worktree_uses_main_repo(self, tmp_path: Path) -> None:
        """HWR-ST-012: 在 worktree 內 collect 時，transcript slug 與 repo 名稱取主 repo"""
        repo = make_orphan_repo(tmp_path)
        git_commit_all(repo)
        wt = tmp_path / "wt-copy"
        REAL_RUN(
            ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(wt)], check=True
        )
        proj = tmp_path / "projects" / hr.project_slug(repo)
        proj.mkdir(parents=True)
        (proj / "s.jsonl").write_text(json.dumps({"timestamp": "2026-09-29T00:00:00Z"}) + "\n")
        hr.main(collect_args(wt, tmp_path, "--no-ci"))
        snap = load(tmp_path / "out" / "snap.json")
        assert snap["repo_name"] == "demo"
        assert Path(snap["main_repo"]).resolve() == repo.resolve()
        assert snap["hooks"]["transcript"]["files"] == 1


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

    def test_hwr_vl_003_missing_lessons_file(self, tmp_path: Path) -> None:
        """HWR-VL-003: write-lessons 的 lesson 檔不存在 exit 2"""
        assert hr.main(["write-lessons", "--lessons", str(tmp_path / "none.jsonl")]) == 2

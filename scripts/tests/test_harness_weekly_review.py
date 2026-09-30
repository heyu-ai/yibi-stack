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
- --exclude 的 key 對不到 → 一筆都不寫、exit 1：HWR-VL-004
- --prev auto 無法列出快照目錄 → exit 2：HWR-VL-005
- Round 2（量不到不可變成已解除或錯的週數）：
  - hook-events 未涵蓋觀察期或清單不完整 → hook-error／hook-slow 不判定：HWR-DT-029
  - transcript 窗內 0 筆或有讀取失敗 → transcript 類不判定：HWR-DT-030、HWR-ST-013
  - 缺週時 carried 週數重設為 1、相鄰週不累加：HWR-ST-014
  - YAML 行尾註解與引號、看不懂的形狀：HWR-DT-031、HWR-DT-032
  - gate 上線日期讀不到 → gate-silent 不判定：HWR-DT-033
  - rule 候選被上限截掉 → 不判定，collect 不再截斷：HWR-DT-034
  - 同名 step 跨 job 的歸因歧義：HWR-DT-035；多個 step 呼叫同一 gate：HWR-DT-036
  - workflow 檔讀不到：HWR-DT-037；rule 檔讀不到：HWR-DT-038；同名段落 (2) 後綴：HWR-DT-039
  - diff 的 unevaluated_ids／unevaluated_prefixes 分支：HWR-ST-015
  - 舊版 CI 快取忽略重抓、清掉觀察期外的 run：HWR-DT-040
  - write-lessons：真的 mycelium 分出 written／skipped_existing：HWR-ST-016；
    輸出無法確認：HWR-ST-017；逾時／執行檔不存在／壞行：HWR-ST-018
  - --prev auto 略過版本不符的快照：HWR-ST-019
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
            "transcript": {"files": 1, "in_window": 1, "read_failures": 0, "hooks": {}},
        },
        "ci": {
            "inventory": {"gates": [], "workflows_complete": True},
            "failures": {"jobs": {}},
            "measured": True,
        },
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
        assert set(steps) == {
            "Run actions/checkout@v7",
            "Gate A",
            "Run bash scripts/harness/ci-check-b.sh --x",
            "Multi",
        }
        assert steps["Run actions/checkout@v7"] == ""  # 沒有 run: 的 step 也要列出，供同名比對
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
                "attributable": True,
                "ci_steps": ["Gate B"],
                "added": "2026-01-01",
            },
            {
                "script": "rule-gate-c.py",
                "wired_in_ci": True,
                "attributable": True,
                "ci_steps": ["Gate C"],
                "added": "2026-09-01",
            },
            {
                "script": "rule-gate-d.py",
                "wired_in_ci": True,
                "attributable": True,
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
                "attributable": True,
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
                "attributable": True,
                "ci_steps": ["Check things"],
                "added": "2026-01-01",
            },
            {
                "script": "rule-gate-beta.py",
                "wired_in_ci": True,
                "attributable": True,
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
        assert "7" not in load(cache)["runs"]

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
        assert set(load(cache)["runs"]) == {"8"}

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
        snap["rules"], _ = hr.collect_rules(tmp_path, set())
        before = hr.build_recommendations(snap, make_thresholds())
        (rules / "03.md").write_text("# T\n\n多一行\n\n" + body)
        snap["rules"], _ = hr.collect_rules(tmp_path, set())
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
            return cp(
                list(args),
                rc,
                "" if rc else "id=x trusted=False\n",
                "ValidationError: boom" if rc else "",
            )

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
        monkeypatch.setattr(
            hr.subprocess, "run", lambda args, **kw: cp(list(args), 0, "id=x trusted=False\n")
        )
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


def weekly_args(repo: Path, tmp_path: Path, now: str, *extra: str) -> list[str]:
    return [
        "weekly",
        "--repo",
        str(repo),
        "--no-ci",
        "--now",
        now,
        "--events-dir",
        str(tmp_path / "ev"),
        "--projects-dir",
        str(tmp_path / "p"),
        *extra,
    ]


class TestWeekly:
    def test_hwr_st_015_weekly_writes_week_named_files_under_main_repo(
        self, tmp_path: Path
    ) -> None:
        """HWR-ST-015: 從 worktree 執行 weekly，三個輸出依 ISO 週命名，預設落在主 repo 的 .runtime/harness-review/"""
        repo = make_orphan_repo(tmp_path)
        git_commit_all(repo)
        wt = tmp_path / "wt-copy"
        REAL_RUN(
            ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(wt)], check=True
        )
        buf: list[str] = []
        rc = _capture_main(weekly_args(wt, tmp_path, "2026-09-30T00:00:00Z"), buf)
        assert rc in (0, 3)
        out_dir = repo / ".runtime" / "harness-review"
        for name in ("snapshot-2026-W40.json", "report-2026-W40.md", "lessons-2026-W40.jsonl"):
            assert (out_dir / name).is_file(), name
        assert not (wt / ".runtime").exists()
        summary = json.loads(buf[0].strip().splitlines()[-1])
        assert summary["week"] == "2026-W40"
        assert summary["prev_status"] == "none"
        assert Path(summary["report"]).resolve() == (out_dir / "report-2026-W40.md").resolve()

    def test_hwr_st_016_weekly_finds_previous_week(self, tmp_path: Path) -> None:
        """HWR-ST-016: 連續兩週執行 weekly，第二週自動以上週快照為 prev（排程不需要算日期）"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        for now in ("2026-09-23T00:00:00Z", "2026-09-30T00:00:00Z"):
            buf: list[str] = []
            rc = _capture_main(weekly_args(repo, tmp_path, now, "--out-dir", str(out_dir)), buf)
            assert rc in (0, 3)
        summary = json.loads(buf[0].strip().splitlines()[-1])
        assert summary["week"] == "2026-W40"
        assert summary["prev"].endswith("snapshot-2026-W39.json")
        assert summary["prev_status"] == "found"
        text = (out_dir / "report-2026-W40.md").read_text()
        assert "hook-unregistered" in text

    def test_hwr_st_017_weekly_passes_collect_thresholds(self, tmp_path: Path) -> None:
        """HWR-ST-017: weekly 沿用 collect 的門檻參數（--heavy-rule-chars 調高後不再產出 rule-heavy）"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        args = weekly_args(repo, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir))
        assert hr.main([*args, "--heavy-rule-chars", "1000000"]) in (0, 3)
        kinds = rec_kinds(load(out_dir / "snapshot-2026-W40.json")["recommendations"])
        assert ".claude/rules/big.md" not in kinds
        assert kinds["orphan.sh"] == "hook-unregistered"

    def test_hwr_dt_033_weekly_incomplete_ok(self, tmp_path: Path) -> None:
        """HWR-DT-033: --incomplete-ok 讓量測不完整回 0（scheduler 只把 0 當成功），warnings 仍寫進報告；
        參數錯誤仍回 2"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        base = weekly_args(repo, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir))
        assert hr.main(base) == 3  # transcript 找不到 → 量測不完整
        buf: list[str] = []
        assert _capture_main([*base, "--incomplete-ok"], buf) == 0
        summary = json.loads(buf[0].strip().splitlines()[-1])
        assert summary["collect_rc"] == 3
        assert "量測不完整" in (out_dir / "report-2026-W40.md").read_text()
        bad = weekly_args(tmp_path / "nope", tmp_path, "2026-09-30T00:00:00Z", "--incomplete-ok")
        assert hr.main(bad) == 2

    def test_hwr_dt_034_weekly_collect_error_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-034: collect 回 2 等非 0/3 值時，weekly 原樣回傳且不產報告，--incomplete-ok 也不吞掉"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        monkeypatch.setattr(hr, "cmd_collect", lambda ns: 2)
        base = weekly_args(repo, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir))
        assert hr.main([*base, "--incomplete-ok"]) == 2
        assert not (out_dir / "report-2026-W40.md").exists()


class TestValidation:
    def test_hwr_vl_006_weekly_not_git_repo(self, tmp_path: Path) -> None:
        """HWR-VL-006: weekly 對非 git 目錄 exit 2，且不留下任何輸出檔"""
        out_dir = tmp_path / "hr"
        rc = hr.main(
            weekly_args(tmp_path, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir))
        )
        assert rc == 2
        assert not out_dir.exists() or not any(out_dir.iterdir())

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

    def test_hwr_vl_004_unknown_exclude_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """HWR-VL-004: --exclude 的 key 不在 lesson 檔 → [FAIL]、exit 1、一筆都不寫"""
        path = tmp_path / "l.jsonl"
        path.write_text(json.dumps({"key": "k1", "type": "operational", "insight": "a"}) + "\n")
        calls: list[Any] = []
        monkeypatch.setattr(hr.subprocess, "run", lambda a, **kw: calls.append(a))
        rc = hr.main(["write-lessons", "--lessons", str(path), "--exclude", "k-typo"])
        assert rc == 1 and calls == []
        assert "[FAIL] --exclude 的 key 不在 lesson 檔內：k-typo" in capsys.readouterr().err

    def test_hwr_vl_005_prev_auto_unreadable_dir(self, tmp_path: Path) -> None:
        """HWR-VL-005: --prev auto 無法列出快照目錄 → exit 2，不可當成第一次執行"""
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root 不受目錄權限限制")
        out = tmp_path / "out"
        out.mkdir()
        snap = out / "snapshot-2026-W40.json"
        snap.write_text(json.dumps(v2_snapshot("2026-W40")))
        out.chmod(0o300)  # 可依檔名存取，但不能列目錄
        try:
            rc = hr.main(
                [
                    "report",
                    "--snapshot",
                    str(snap),
                    "--prev",
                    "auto",
                    "--out",
                    str(tmp_path / "r.md"),
                    "--lessons-out",
                    str(tmp_path / "l.jsonl"),
                ]
            )
        finally:
            out.chmod(0o700)
        assert rc == 2


def v2_snapshot(label: str, recs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """report 讀得了的最小 v2 快照。"""
    return {
        "version": hr.SNAPSHOT_VERSION,
        "repo_name": "demo",
        "window": {
            "label": label,
            "since": "2026-09-23",
            "until": "2026-09-30",
            "gate_since": "2026-07-01",
        },
        "warnings": [],
        "notes": [],
        "hooks": {"events": {"hooks": {}}},
        "ci": {"measured": True},
        "metrics": {},
        "evaluation": {"kinds": ["rule-heavy"], "unevaluated_ids": []},
        "recommendations": recs or [],
    }


def scope_diff(scope: dict[str, Any], prev_id: str, kind: str) -> str:
    """上週有 prev_id、本週沒有，回傳 diff 判定的狀態。"""
    prev = {"window": {"label": "2026-W39"}, "metrics": {}, "recommendations": []}
    prev["recommendations"] = [{"id": prev_id, "kind": kind, "weeks": 2}]
    curr = {"window": {"label": "2026-W40"}, "metrics": {}, "recommendations": []}
    curr["evaluation"] = scope
    return str(hr.diff_snapshots(prev, curr, 3)["statuses"][0]["status"])


class TestRound2Coverage:
    """Round 2 review：量不到的情況不可被判成已解除或錯誤的週數。"""

    def test_hwr_dt_029_events_not_covering_blocks_error_kinds(self) -> None:
        """HWR-DT-029: events 檔存在但未涵蓋觀察期 → hook-error／hook-slow 不可判定，上週建議 unmeasured"""
        snap = make_snapshot()
        snap["hooks"]["events"] = {"files": 1, "covers_window": False, "in_window": 0, "hooks": {}}
        scope = hr.evaluation_scope(snap)
        assert "hook-error" not in scope["kinds"] and "hook-slow" not in scope["kinds"]
        assert scope_diff(scope, "hook-error:foo.sh", "hook-error") == "unmeasured"
        assert scope_diff(scope, "hook-slow:foo.sh", "hook-slow") == "unmeasured"
        # hook 清單不完整時也不可判定（hook-error 只對已註冊 hook 產生）
        snap["hooks"]["events"]["covers_window"] = True
        snap["hooks"]["inventory"]["complete"] = False
        assert "hook-error" not in hr.evaluation_scope(snap)["kinds"]
        # 正向對照：涵蓋且清單完整 → 可判定，消失即 resolved
        snap["hooks"]["inventory"]["complete"] = True
        scope = hr.evaluation_scope(snap)
        assert scope_diff(scope, "hook-error:foo.sh", "hook-error") == "resolved"
        assert scope_diff(scope, "hook-slow:foo.sh", "hook-slow") == "resolved"

    def test_hwr_dt_030_transcript_needs_in_window_and_no_read_failure(self) -> None:
        """HWR-DT-030: transcript 窗內 0 筆或有檔案讀取失敗 → transcript 類不判定"""
        snap = make_snapshot()
        tr = snap["hooks"]["transcript"]
        for in_window, failures in ((0, 0), (5, 1)):
            tr.update(in_window=in_window, read_failures=failures)
            scope = hr.evaluation_scope(snap)
            assert "hook-silent-block" not in scope["kinds"]
            assert scope_diff(scope, "hook-silent-block:x.py", "hook-silent-block") == "unmeasured"
            assert scope_diff(scope, "hook-stale-plugin:x.py", "hook-stale-plugin") == "unmeasured"
        tr.update(in_window=5, read_failures=0)  # 正向對照
        scope = hr.evaluation_scope(snap)
        assert scope_diff(scope, "hook-silent-block:x.py", "hook-silent-block") == "resolved"
        # 舊快照沒有這兩個欄位：保守處理成量不到
        del tr["in_window"], tr["read_failures"]
        assert "hook-silent-block" not in hr.evaluation_scope(snap)["kinds"]

    def test_hwr_st_013_transcript_counts(self, tmp_path: Path) -> None:
        """HWR-ST-013: collect_transcript_blocks 回報窗內事件數與讀取失敗數"""
        repo = tmp_path / "demo"
        repo.mkdir()
        d = tmp_path / "projects" / hr.project_slug(repo)
        d.mkdir(parents=True)
        (d / "old.jsonl").write_text(json.dumps({"timestamp": "2026-08-01T00:00:00Z"}) + "\n")
        since = hr.parse_ts("2026-09-23T00:00:00Z")
        assert since is not None
        data, warnings = hr.collect_transcript_blocks(tmp_path / "projects", repo, since)
        assert (data["files"], data["in_window"], data["read_failures"]) == (1, 0, 0)
        assert any("觀察期內" in w for w in warnings)
        (d / "new.jsonl").write_text(json.dumps({"timestamp": "2026-09-29T00:00:00Z"}) + "\n")
        (d / "gone.jsonl").symlink_to(d / "missing-target.jsonl")  # 讀不到的檔案
        data, warnings = hr.collect_transcript_blocks(tmp_path / "projects", repo, since)
        assert (data["files"], data["in_window"], data["read_failures"]) == (3, 1, 1)
        assert any("讀取失敗" in w for w in warnings)

    def test_hwr_st_014_gap_resets_carried_weeks(self) -> None:
        """HWR-ST-014: 缺週時 carried 週數重設為 1 並標記；相鄰週量不到時週數原樣、不累加"""

        def snap(label: str, recs: list[dict[str, Any]], kinds: list[str]) -> dict[str, Any]:
            return {
                "window": {"label": label},
                "metrics": {},
                "recommendations": recs,
                "evaluation": {"kinds": kinds, "unevaluated_ids": []},
            }

        rec = {"id": "gate-silent:g.py", "kind": "gate-silent"}
        w35 = snap("2026-W35", [{**rec, "weeks": 2}], ["gate-silent"])
        w40 = snap("2026-W40", [], [])
        d = hr.diff_snapshots(w35, w40, 3)
        assert d["statuses"][0]["status"] == "unmeasured" and d["statuses"][0]["weeks"] == 1
        assert w40["carried"][0]["weeks"] == 1 and w40["carried"][0]["streak_reset"] is True
        text = hr.render_report(
            {
                **v2_snapshot("2026-W40"),
                "ci": {"measured": True},
            },
            d,
        )
        assert "週數重設為第 1 週" in text
        w41 = snap("2026-W41", [dict(rec)], ["gate-silent"])
        st = hr.diff_snapshots(w40, w41, 3)["statuses"][0]
        assert (st["status"], st["weeks"], st["escalate"]) == ("persisting", 2, False)
        # 對照：相鄰週量不到 → 週數原樣（2），不累加；下一週接續成 3 並升級
        w39 = snap("2026-W39", [{**rec, "weeks": 2}], ["gate-silent"])
        w40b = snap("2026-W40", [], [])
        hr.diff_snapshots(w39, w40b, 3)
        assert w40b["carried"][0]["weeks"] == 2 and w40b["carried"][0]["streak_reset"] is False
        st = hr.diff_snapshots(w40b, snap("2026-W41", [dict(rec)], ["gate-silent"]), 3)
        assert (st["statuses"][0]["weeks"], st["statuses"][0]["escalate"]) == (3, True)

    def test_hwr_dt_031_yaml_trailing_comment_and_quotes(self) -> None:
        """HWR-DT-031: step 名稱與單行 run 去掉 YAML 行尾註解與引號；看不懂的形狀記為 None"""
        text = (
            "jobs:\n  a:\n    steps:\n"
            "      - name: Check things # validation\n"
            "        run: python scripts/harness/rule-gate-a.py  # gate a\n"
            '      - name: "Quoted # not comment"  # real comment\n'
            "        run: 'bash scripts/harness/ci-check-b.sh'\n"
            "      - name: 'It''s fine'\n        run: echo x#y\n"
            '      - name: "unclosed\n        run: echo z\n'
            "      - name: [flow]\n        run: echo w\n"
            '      - run: "echo unclosed\n'
        )
        steps = hr.workflow_steps(text)
        assert [s["name"] for s in steps] == [
            "Check things",
            "Quoted # not comment",
            "It's fine",
            None,
            None,
            None,
        ]
        assert steps[0]["run"] == "python scripts/harness/rule-gate-a.py"
        assert steps[1]["run"] == "bash scripts/harness/ci-check-b.sh"
        assert steps[2]["run"] == "echo x#y"  # 沒有前置空白的 # 不是註解
        assert steps[5]["run"] is None
        assert hr.yaml_scalar("   ") == "" and hr.yaml_scalar("# only comment") == ""

    def test_hwr_dt_032_comment_named_step_attributes_failures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-032: step 名稱帶行尾註解時，同名 failed step 仍歸因到 gate，不誤判 gate-silent"""
        workflow = (
            "jobs:\n  check:\n    steps:\n"
            "      - name: Check things # validation\n"
            "        run: python scripts/harness/rule-gate-alpha.py\n"
        )
        repo = make_gate_repo(tmp_path, workflow)
        inv, _, notes = hr.collect_gate_inventory(repo)
        gate = inv["gates"][0]
        assert gate["ci_steps"] == ["Check things"] and gate["attributable"] is True
        snap = make_snapshot()
        snap["ci"]["inventory"] = inv
        snap["ci"]["failures"]["jobs"] = {
            "CI / check": {"failures": 2, "branches": 1, "steps": {"Check things": 2}}
        }
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {}
        snap["ci"]["failures"]["jobs"] = {}  # 對照：0 失敗才判 gate-silent
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {
            "rule-gate-alpha.py": "gate-silent"
        }
        # 看不懂的名稱形狀：無法歸因 → 不判定
        odd = workflow.replace("Check things # validation", '"Check things')
        repo2 = make_gate_repo(tmp_path / "odd", odd)
        inv2, _, notes2 = hr.collect_gate_inventory(repo2)
        assert inv2["gates"][0]["attributable"] is False and any("YAML" in n for n in notes2)
        snap["ci"]["inventory"] = inv2
        assert "gate-silent:rule-gate-alpha.py" in hr.evaluation_scope(snap)["unevaluated_ids"]

    def test_hwr_dt_033_gate_added_unreadable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-033: gate 上線日期讀不到（git log 失敗）→ gate-silent 列 unevaluated，上週建議 unmeasured"""
        repo = make_gate_repo(tmp_path)

        def fake(args: list[str], **kw: Any) -> Any:
            if args[:2] == ["git", "log"]:
                return cp(args, 128, "", "fatal: bad object")
            return REAL_RUN(args, **kw)

        monkeypatch.setattr(hr.subprocess, "run", fake)
        inv, warnings, _ = hr.collect_gate_inventory(repo)
        assert inv["gates"][0]["added"] is None and any("上線日期" in w for w in warnings)
        snap = make_snapshot()
        snap["ci"]["inventory"] = inv
        scope = hr.evaluation_scope(snap)
        assert "gate-silent:rule-gate-alpha.py" in scope["unevaluated_ids"]
        assert scope_diff(scope, "gate-silent:rule-gate-alpha.py", "gate-silent") == "unmeasured"
        inv["gates"][0]["added"] = "2026-01-01"  # 對照：日期讀得到 → 可判定
        scope = hr.evaluation_scope(snap)
        assert scope_diff(scope, "gate-silent:rule-gate-alpha.py", "gate-silent") == "resolved"

    def test_hwr_dt_034_rule_candidates_cut_are_unevaluated(self, tmp_path: Path) -> None:
        """HWR-DT-034: 排名在 --max-rule-candidates 之外的候選不判定；collect 不再靜默截斷"""
        rules = tmp_path / ".claude" / "rules"
        rules.mkdir(parents=True)
        body = "必須 `a` `b` `c` `d`。不要 `e` `f` `g` `h`。一律 `i`。\n"
        (rules / "03.md").write_text("".join(f"## S{i:02d}\n\n{body}\n" for i in range(45)))
        data, warnings = hr.collect_rules(tmp_path, set())
        assert warnings == [] and len(data["candidates"]) == 45
        snap = make_snapshot()
        snap["rules"] = data
        recs = hr.build_recommendations(snap, make_thresholds(max_rule_candidates=2))
        assert len(recs) == 2
        cut = data["candidates"][44]["anchor"]
        scope = hr.evaluation_scope(snap, 2)
        rid = f"rule-mechanize-candidate:{cut}"
        assert rid in scope["unevaluated_ids"]
        assert scope_diff(scope, rid, "rule-mechanize-candidate") == "unmeasured"
        kept = f"rule-mechanize-candidate:{data['candidates'][0]['anchor']}"
        assert kept not in scope["unevaluated_ids"]
        # 對照：上限夠大時被截掉的候選不存在，消失就是 resolved
        scope = hr.evaluation_scope(snap, 100)
        assert scope_diff(scope, rid, "rule-mechanize-candidate") == "resolved"

    def test_hwr_dt_035_same_step_name_elsewhere_is_ambiguous(self, tmp_path: Path) -> None:
        """HWR-DT-035: gate 的 step 名稱也被別的 job 沒呼叫它的 step 使用 → 無法歸因、不判 gate-silent"""
        workflow = (
            "jobs:\n  a:\n    steps:\n"
            "      - name: Check things\n"
            "        run: python scripts/harness/rule-gate-alpha.py\n"
            "  b:\n    steps:\n"
            "      - name: Check things\n"
            "        run: npm test\n"
        )
        repo = make_gate_repo(tmp_path, workflow)
        inv, _, notes = hr.collect_gate_inventory(repo)
        assert inv["gates"][0]["attributable"] is False
        assert any("也被另一個" in n for n in notes)
        snap = make_snapshot()
        snap["ci"]["inventory"] = inv
        snap["ci"]["failures"]["jobs"] = {
            "CI / b": {"failures": 4, "branches": 1, "steps": {"Check things": 4}}
        }
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {}
        scope = hr.evaluation_scope(snap)
        assert scope_diff(scope, "gate-silent:rule-gate-alpha.py", "gate-silent") == "unmeasured"
        # 同名的 uses: step 也算歧義
        uses = workflow.replace("        run: npm test\n", "        uses: actions/x@v1\n")
        inv2, _, _ = hr.collect_gate_inventory(make_gate_repo(tmp_path / "u", uses))
        assert inv2["gates"][0]["attributable"] is False
        # 對照：名稱不重複 → 可歸因
        unique = workflow.replace(
            "      - name: Check things\n        run: npm test",
            "      - name: Unit\n        run: npm test",
        )
        inv3, _, _ = hr.collect_gate_inventory(make_gate_repo(tmp_path / "ok", unique))
        assert inv3["gates"][0]["attributable"] is True

    def test_hwr_dt_036_multi_step_ci_steps(self) -> None:
        """HWR-DT-036: gate 由兩個不同名 step 呼叫時，第二個 step 的失敗也要算進去"""
        snap = make_snapshot()
        snap["ci"]["inventory"]["gates"] = [
            {
                "script": "rule-gate-z.py",
                "wired_in_ci": True,
                "attributable": True,
                "ci_steps": ["Lint A", "Lint B"],
                "added": "2026-01-01",
            }
        ]
        snap["ci"]["failures"]["jobs"] = {
            "CI / j": {"failures": 1, "branches": 1, "steps": {"Lint B": 1}}
        }
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {}
        snap["ci"]["failures"]["jobs"] = {}
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {
            "rule-gate-z.py": "gate-silent"
        }

    def test_hwr_dt_037_workflow_unreadable(self, tmp_path: Path) -> None:
        """HWR-DT-037: workflow 檔讀不到 → gate-unwired 不判定、所有 gate-silent 列 unevaluated"""
        repo = make_gate_repo(tmp_path)
        (repo / ".github" / "workflows" / "ci.yml").write_bytes(b"\xff\xfe\x00bad")
        inv, warnings, _ = hr.collect_gate_inventory(repo)
        assert inv["workflows_complete"] is False and any("讀取失敗" in w for w in warnings)
        snap = make_snapshot()
        snap["ci"]["inventory"] = inv
        scope = hr.evaluation_scope(snap)
        assert "gate-unwired" not in scope["kinds"]
        assert "gate-silent:rule-gate-alpha.py" in scope["unevaluated_ids"]
        assert hr.build_recommendations(snap, make_thresholds()) == []
        assert scope_diff(scope, "gate-unwired:rule-gate-alpha.py", "gate-unwired") == "unmeasured"

    def test_hwr_dt_038_rule_file_unreadable(self, tmp_path: Path) -> None:
        """HWR-DT-038: rule 檔讀不到 → warning、該檔 rule 類建議不判定；其他檔照常"""
        rules = tmp_path / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "bad.md").write_bytes(b"\xff\xfe bad")
        (rules / "ok.md").write_text("## T\n\n必須 `a` `b` `c` `d`。不要 `e`。一律 `f`。\n")
        data, warnings = hr.collect_rules(tmp_path, set())
        assert data["unreadable"] == [".claude/rules/bad.md"] and warnings
        assert data["always_loaded_chars"] is None
        snap = make_snapshot()
        snap["rules"] = data
        scope = hr.evaluation_scope(snap, 10)
        assert scope_diff(scope, "rule-heavy:.claude/rules/bad.md", "rule-heavy") == "unmeasured"
        rid = "rule-mechanize-candidate:.claude/rules/bad.md#X"
        assert scope_diff(scope, rid, "rule-mechanize-candidate") == "unmeasured"
        other = "rule-mechanize-candidate:.claude/rules/ok.md#Gone"
        assert scope_diff(scope, other, "rule-mechanize-candidate") == "resolved"

    def test_hwr_dt_039_same_title_suffix(self, tmp_path: Path) -> None:
        """HWR-DT-039: 同檔同名段落的 anchor 依出現順序加 (2)"""
        rules = tmp_path / ".claude" / "rules"
        rules.mkdir(parents=True)
        body = "必須 `a` `b` `c` `d`。不要 `e`。一律 `f`。\n"
        (rules / "r.md").write_text(f"## Dup\n\n{body}\n## Dup\n\n{body}\n")
        data, _ = hr.collect_rules(tmp_path, set())
        anchors = sorted(c["anchor"] for c in data["candidates"])
        assert anchors == [".claude/rules/r.md#Dup", ".claude/rules/r.md#Dup (2)"]

    def test_hwr_st_015_diff_unevaluated_branch(self) -> None:
        """HWR-ST-015: 類型可判定但 id 列在 unevaluated_ids／前綴 → unmeasured；不在 → resolved"""
        base = {"kinds": ["gate-silent", "rule-mechanize-candidate"]}
        rid = "gate-silent:g.py"
        assert scope_diff({**base, "unevaluated_ids": [rid]}, rid, "gate-silent") == "unmeasured"
        assert scope_diff({**base, "unevaluated_ids": []}, rid, "gate-silent") == "resolved"
        pref = {
            **base,
            "unevaluated_ids": [],
            "unevaluated_prefixes": ["rule-mechanize-candidate:a.md#"],
        }
        assert (
            scope_diff(pref, "rule-mechanize-candidate:a.md#T", "rule-mechanize-candidate")
            == "unmeasured"
        )
        assert (
            scope_diff(pref, "rule-mechanize-candidate:b.md#T", "rule-mechanize-candidate")
            == "resolved"
        )


class TestCiCacheSchema:
    def test_hwr_dt_040_unversioned_cache_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-040: 舊版（未標版本）jobs 快取整份忽略並重抓；新格式快取才沿用"""
        runs = [{"id": 7, "name": "CI", "head_branch": "x", "created_at": "2026-09-01"}]
        fresh = json.dumps(
            {
                "total_count": 1,
                "jobs": [
                    {
                        "name": "check",
                        "conclusion": "failure",
                        "steps": [{"name": "Check things", "conclusion": "failure"}],
                    }
                ],
            }
        )
        cache = tmp_path / "cache.json"
        # 舊快取說 run 7 沒有任何 job（例如當年分頁沒讀完）；沿用它會把 gate 判成 0 失敗
        cache.write_text(json.dumps({"7": [], "999": []}))
        repo = make_gate_repo(tmp_path)
        calls: list[tuple[list[str], dict[str, Any]]] = []
        install_fake_run(monkeypatch, make_gh(runs=runs, jobs={7: fresh}), calls)
        hr.main(collect_args(repo, tmp_path, "--ci-cache", str(cache)))
        snap = load(tmp_path / "out" / "snap.json")
        assert any("--paginate" in c and "runs/7/jobs" in " ".join(c) for c, _ in calls)
        assert any("舊版或未標版本" in n for n in snap["notes"])
        assert "gate-silent" not in {r["kind"] for r in snap["recommendations"]}
        saved = load(cache)
        assert saved["schema"] == hr.CI_CACHE_SCHEMA and set(saved["runs"]) == {"7"}
        # 對照：新格式快取直接沿用，不再呼叫 jobs API；觀察期外的舊 run（999）會被清掉
        saved["runs"]["999"] = []
        cache.write_text(json.dumps(saved))
        calls.clear()
        hr.main(collect_args(repo, tmp_path, "--ci-cache", str(cache)))
        assert not any("--paginate" in c for c, _ in calls)
        assert not any("舊版或未標版本" in n for n in load(tmp_path / "out" / "snap.json")["notes"])
        assert set(load(cache)["runs"]) == {"7"}


def mycelium_wrapper(tmp_path: Path) -> Path:
    """呼叫本 repo 真正的 mycelium CLI（寫到 MYCELIUM_DB_OVERRIDE 指定的暫存 DB）。"""
    wrapper = tmp_path / "mycelium"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m tasks.mycelium "$@"\n')
    wrapper.chmod(0o755)
    return wrapper


class TestWriteLessonsResults:
    def test_hwr_st_016_written_vs_skipped_existing_real_mycelium(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """HWR-ST-016: 對真的 mycelium 跑兩次：第一次 written，第二次 skipped_existing（不算 written）"""
        monkeypatch.setenv("MYCELIUM_DB_OVERRIDE", str(tmp_path / "t.db"))
        monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
        path = tmp_path / "l.jsonl"
        row = {"key": "hwr-k", "type": "operational", "insight": "probe insight", "project": "demo"}
        path.write_text(json.dumps(row) + "\n")
        args = [
            "write-lessons",
            "--lessons",
            str(path),
            "--mycelium",
            str(mycelium_wrapper(tmp_path)),
        ]
        assert hr.main(args) == 0
        first = json.loads(capsys.readouterr().out)
        assert (first["written"], first["skipped_existing"]) == (1, 0)
        assert hr.main(args) == 0
        second = json.loads(capsys.readouterr().out)
        assert (second["written"], second["skipped_existing"]) == (0, 1)

    def test_hwr_st_017_unconfirmed_result_is_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """HWR-ST-017: exit 0 但輸出既不是寫入也不是略過 → [FAIL]、exit 1"""
        path = tmp_path / "l.jsonl"
        path.write_text(json.dumps({"key": "k", "type": "operational", "insight": "x"}) + "\n")
        monkeypatch.setattr(hr.subprocess, "run", lambda a, **kw: cp(list(a), 0, "", ""))
        assert hr.main(["write-lessons", "--lessons", str(path)]) == 1
        captured = capsys.readouterr()
        assert "無法確認是否寫入" in captured.err
        assert json.loads(captured.out)["failed"] == ["k"]

    def test_hwr_st_018_timeout_oserror_bad_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """HWR-ST-018: 逾時、執行檔不存在、壞行各自記為失敗，其餘照常寫入，exit 1"""
        rows = [
            json.dumps({"key": "k-timeout", "type": "operational", "insight": "a"}),
            "{not json",
            json.dumps({"key": "k-missing-type", "insight": "b"}),
            json.dumps({"key": "k-oserror", "type": "operational", "insight": "c"}),
            json.dumps({"key": "k-ok", "type": "operational", "insight": "d"}),
        ]
        path = tmp_path / "l.jsonl"
        path.write_text("\n".join(rows) + "\n")

        def fake(args: list[str], **kw: Any) -> Any:
            if "k-timeout" in args:
                raise subprocess.TimeoutExpired(args, 60)
            if "k-oserror" in args:
                raise FileNotFoundError(2, "No such file", "mycelium")
            return cp(args, 0, "id=1 trusted=False\n")

        monkeypatch.setattr(hr.subprocess, "run", fake)
        assert hr.main(["write-lessons", "--lessons", str(path)]) == 1
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["written"] == 1
        assert result["failed"] == ["k-timeout", "line 2", "line 3", "k-oserror"]
        assert "逾時" in captured.err and "無法執行" in captured.err and "格式錯誤" in captured.err


class TestPrevAutoCompat:
    def _report(self, out: Path, prev: str = "auto") -> tuple[int, dict[str, Any]]:
        buf: list[str] = []
        rc = _capture_main(
            [
                "report",
                "--snapshot",
                str(out / "snapshot-2026-W40.json"),
                "--prev",
                prev,
                "--out",
                str(out / "r.md"),
                "--lessons-out",
                str(out / "l.jsonl"),
            ],
            buf,
        )
        return rc, (json.loads(buf[0]) if buf[0] else {})

    def test_hwr_st_019_prev_auto_skips_incompatible(self, tmp_path: Path) -> None:
        """HWR-ST-019: --prev auto 略過版本不符的舊快照往前找，prev_status 註明；明確指定仍 exit 2"""
        out = tmp_path / "out"
        out.mkdir()
        rec = {"id": "rule-heavy:r.md", "kind": "rule-heavy", "bucket": "減量", "target": "r.md"}
        rec |= {"suggestion": "s", "evidence": {}}
        (out / "snapshot-2026-W40.json").write_text(json.dumps(v2_snapshot("2026-W40", [rec])))
        old = {**v2_snapshot("2026-W39"), "version": 1}
        (out / "snapshot-2026-W39.json").write_text(json.dumps(old))
        rc, res = self._report(out)
        assert rc == 0 and res["prev_status"] == "none_after_skip"
        assert res["skipped_incompatible"] == [str(out / "snapshot-2026-W39.json")]
        (out / "snapshot-2026-W38.json").write_text(json.dumps(v2_snapshot("2026-W38", [rec])))
        rc, res = self._report(out)
        assert rc == 0 and res["prev_status"] == "found_after_skip"
        assert res["prev"].endswith("snapshot-2026-W38.json")
        rc, _ = self._report(out, str(out / "snapshot-2026-W39.json"))
        assert rc == 2
        (out / "snapshot-2026-W39.json").unlink()  # 對照：沒有舊版快照時是 found
        rc, res = self._report(out)
        assert res["prev_status"] == "found" and res["skipped_incompatible"] == []

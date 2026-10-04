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
- weekly 子命令（排程用）：
  - 從 worktree 執行時依 ISO 週命名、寫到主 repo：HWR-ST-020；自動找上週快照：HWR-ST-021；
    沿用 collect 門檻：HWR-ST-022；summary 帶出 warning 數與 CI 是否量到：HWR-ST-023
  - --incomplete-ok 只把 3 改成 0：HWR-DT-041；collect 的其他錯誤原樣回傳：HWR-DT-042
  - ISO 年界（2027-01-01 → 2026-W53）：HWR-DT-043；只讀一次時鐘：HWR-DT-044
  - 非 git 目錄 exit 2：HWR-VL-006；輸出目錄未被 .gitignore 排除時警告：HWR-VL-007
- issue #509（change harden-weekly-review-measurement）：
  - 家族層級讀取失敗注入矩陣（每個來源 × 檔案／目錄／單行／API 形狀；對照：全部健康時
    14 種建議都 resolved）：HWR-DT-050、HWR-DT-051
  - 來源記錄預設不完整（unreadable-hook-events-file、unreadable-rules-directory、
    truncated-transcript-line、unreadable-hook-script）：HWR-DT-052..056
  - 來源記錄或 ci.measured 缺漏／型別錯誤一律當量不到：HWR-DT-057、HWR-DT-058
  - resolved 需要正向證據（hook-below-sample-threshold、hook-not-observed、
    hook-observed-and-clean、gate-job-never-ran、物件已不存在、表外類型維持舊行為、
    transcript 最少事件數）：HWR-DT-059..066
  - 精確歸因（unrelated-job-sharing-substring、dynamic-step-name、multiline-plain-name、
    無法解碼的跳脫序列）：HWR-DT-067..070
  - gate 上線日期（改名 --follow、shallow／無法判斷、對照）：HWR-DT-071..073
  - 上週快照只跑過 collect → streak 重設並寫出原因：HWR-DT-074..076
  - CI runs 回應形狀與 total_count、對照、workflow 活動量：HWR-DT-077、HWR-DT-078
  - cmd_collect 的 --max-rule-candidates 接線與截斷邊界（C5）：HWR-DT-079
  - SNAPSHOT_VERSION 升為 3、v2 快照被略過：HWR-ST-024；--prev auto 遇壞 JSON exit 2：HWR-ST-025
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import types
from collections.abc import Callable, Iterator
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


def complete_source() -> dict[str, Any]:
    """collector 回報的完整來源記錄。"""
    return {"complete": True, "errors": []}


def make_snapshot() -> dict[str, Any]:
    """所有來源都完整的最小快照；測試要讓某個來源不完整時，改它的 source。"""
    return {
        "window": {"gate_since": "2026-07-01T00:00:00+00:00", "label": "2026-W40"},
        "hooks": {
            "inventory": {
                "registered": {},
                "on_disk": [],
                "unregistered": [],
                "source": complete_source(),
            },
            "events": {
                "files": 1,
                "hooks": {},
                "resolution": "ms",
                "covers_window": True,
                "source": complete_source(),
            },
            "transcript": {
                "files": 1,
                "in_window": 5,
                "read_failures": 0,
                "hooks": {},
                "source": complete_source(),
            },
        },
        "ci": {
            "inventory": {"gates": [], "source": complete_source()},
            "failures": {"jobs": {}, "source": complete_source()},
            "measured": True,
        },
        "rules": {"files": [], "candidates": [], "source": complete_source()},
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
    activity_total: int = 5,
) -> Callable[[list[str]], Any]:
    """偽造 gh 的外部回應：repo view、runs 列表、每個 run 的 jobs（原樣輸出字串）、
    每個 workflow 檔在觀察期內的 run 數（gate-silent 的觀察證據）。"""

    def handler(args: list[str]) -> Any:
        if args[1:3] == ["repo", "view"]:
            return cp(args, 0, GH_OK)
        if "--paginate" in args:
            run_id = int(args[3].split("/runs/")[1].split("/")[0])
            return cp(args, 0, (jobs or {}).get(run_id, '{"total_count":0,"jobs":[]}'))
        if any("/workflows/" in a for a in args):
            return cp(args, 0, json.dumps({"total_count": activity_total, "workflow_runs": []}))
        if runs_exc is not None:
            raise runs_exc
        if runs_rc:
            return cp(args, runs_rc, "", "HTTP 502")
        if runs_out is not None:
            return cp(args, 0, runs_out)
        listed = runs or []
        return cp(args, 0, json.dumps({"total_count": len(listed), "workflow_runs": listed}))

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
        # 歸因只接受精確身分：失敗 step 的名稱必須與呼叫 gate 的 step 完全相同。
        # （舊版會把含 gate 字根的 "rule-gate-d self-test" 也算進 gate D，見 HWR-DT-067）
        snap["ci"]["failures"]["jobs"] = {
            "CI / Gates": {"failures": 3, "branches": 2, "steps": {"Gate D": 3}}
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
            "source": complete_source(),
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
            "carried": [],  # report 寫回的快照一定有 carried；沒有代表只跑過 collect（HWR-DT-074）
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
            "carried": [],
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
        prev = {
            "window": {"label": "2026-W35"},
            "metrics": {},
            "carried": [],
            "recommendations": [],
        }
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
    def test_hwr_st_020_weekly_writes_week_named_files_under_main_repo(
        self, tmp_path: Path
    ) -> None:
        """HWR-ST-020: 從 worktree 執行 weekly，三個輸出依 ISO 週命名，預設落在主 repo 的 .runtime/harness-review/"""
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

    def test_hwr_st_021_weekly_finds_previous_week(self, tmp_path: Path) -> None:
        """HWR-ST-021: 連續兩週執行 weekly，第二週自動以上週快照為 prev（排程不需要算日期）"""
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

    def test_hwr_st_022_weekly_passes_collect_thresholds(self, tmp_path: Path) -> None:
        """HWR-ST-022: weekly 沿用 collect 的門檻參數（--heavy-rule-chars 調高後不再產出 rule-heavy）"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        args = weekly_args(repo, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir))
        assert hr.main([*args, "--heavy-rule-chars", "1000000"]) in (0, 3)
        kinds = rec_kinds(load(out_dir / "snapshot-2026-W40.json")["recommendations"])
        assert ".claude/rules/big.md" not in kinds
        assert kinds["orphan.sh"] == "hook-unregistered"

    def test_hwr_dt_041_weekly_incomplete_ok(self, tmp_path: Path) -> None:
        """HWR-DT-041: --incomplete-ok 讓量測不完整回 0（scheduler 只把 0 當成功），warnings 仍寫進報告；
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

    def test_hwr_dt_042_weekly_collect_error_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-042: collect 回 2 等非 0/3 值時，weekly 原樣回傳且不產報告，--incomplete-ok 也不吞掉"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        monkeypatch.setattr(hr, "cmd_collect", lambda ns: 2)
        base = weekly_args(repo, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir))
        assert hr.main([*base, "--incomplete-ok"]) == 2
        assert not (out_dir / "report-2026-W40.md").exists()

    def test_hwr_dt_043_weekly_iso_year_boundary(self, tmp_path: Path) -> None:
        """HWR-DT-043: 2027-01-01 屬於 ISO 2026-W53，檔名用 ISO 年而非曆年，且與快照內的週一致"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        buf: list[str] = []
        args = weekly_args(repo, tmp_path, "2027-01-01T00:00:00Z", "--out-dir", str(out_dir))
        assert _capture_main(args, buf) in (0, 3)
        assert json.loads(buf[0].strip().splitlines()[-1])["week"] == "2026-W53"
        assert load(out_dir / "snapshot-2026-W53.json")["window"]["label"] == "2026-W53"

    def test_hwr_dt_044_weekly_reads_clock_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-044: 不帶 --now 時只讀一次時鐘；第二次讀取若跨過週界，檔名與快照內的週仍一致"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        first = dt.datetime(2026, 10, 4, 23, 59, 59, tzinfo=dt.UTC)  # 週日，2026-W40
        later = dt.datetime(2026, 10, 5, 0, 0, 1, tzinfo=dt.UTC)  # 週一，2026-W41
        reads = iter([first])

        class FakeDateTime(dt.datetime):
            @classmethod
            def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:  # type: ignore[override]
                return next(reads, later)

        fake_dt = types.SimpleNamespace(**vars(dt))
        fake_dt.datetime = FakeDateTime
        monkeypatch.setattr(hr, "dt", fake_dt)
        args = [
            "weekly",
            "--repo",
            str(repo),
            "--no-ci",
            "--events-dir",
            str(tmp_path / "ev"),
            "--projects-dir",
            str(tmp_path / "p"),
            "--out-dir",
            str(out_dir),
        ]
        buf: list[str] = []
        assert _capture_main(args, buf) in (0, 3)
        assert json.loads(buf[0].strip().splitlines()[-1])["week"] == "2026-W40"
        assert load(out_dir / "snapshot-2026-W40.json")["window"]["label"] == "2026-W40"

    def test_hwr_st_023_weekly_summary_reports_measurement(self, tmp_path: Path) -> None:
        """HWR-ST-023: --incomplete-ok 回 0 時，summary 仍帶出 warning 數與 CI 是否量到"""
        repo = make_orphan_repo(tmp_path)
        out_dir = tmp_path / "hr"
        buf: list[str] = []
        args = weekly_args(
            repo, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir), "--incomplete-ok"
        )
        assert _capture_main(args, buf) == 0
        summary = json.loads(buf[0].strip().splitlines()[-1])
        warnings = load(out_dir / "snapshot-2026-W40.json")["warnings"]
        assert warnings
        assert summary["warning_count"] == len(warnings)
        assert summary["ci_measured"] is False


class TestValidation:
    def test_hwr_vl_006_weekly_not_git_repo(self, tmp_path: Path) -> None:
        """HWR-VL-006: weekly 對非 git 目錄 exit 2，且不留下任何輸出檔"""
        out_dir = tmp_path / "hr"
        rc = hr.main(
            weekly_args(tmp_path, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(out_dir))
        )
        assert rc == 2
        assert not out_dir.exists() or not any(out_dir.iterdir())

    def test_hwr_vl_007_weekly_warns_when_output_not_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """HWR-VL-007: 預設輸出目錄未被 .gitignore 排除 → stderr [WARN]、summary 標 false；
        加上排除後標 true 且不警告；--out-dir 在 repo 外 → null"""
        repo = make_orphan_repo(tmp_path)
        args = weekly_args(repo, tmp_path, "2026-09-30T00:00:00Z")

        def run() -> tuple[object, str]:
            buf: list[str] = []
            assert _capture_main(args, buf) in (0, 3)
            summary = json.loads(buf[0].strip().splitlines()[-1])
            return summary["output_gitignored"], capsys.readouterr().err

        flag, err = run()
        assert flag is False and ".gitignore" in err
        (repo / ".gitignore").write_text(".runtime/\n")
        flag, err = run()
        assert flag is True and ".gitignore" not in err
        args = weekly_args(repo, tmp_path, "2026-09-30T00:00:00Z", "--out-dir", str(tmp_path / "x"))
        flag, _ = run()
        assert flag is None

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


def scope_diff(
    scope: dict[str, Any], prev_id: str, kind: str, observed: dict[str, Any] | None = None
) -> str:
    """上週有 prev_id、本週沒有，回傳 diff 判定的狀態。

    observed 是本週快照裡「觀察到什麼」的部分（hooks／ci／rules）；需要逐對象正向證據的類型
    （hook-error、hook-slow、hook-silent-block、gate-silent）沒有帶 observed 時一律是 unmeasured。
    """
    prev = {"window": {"label": "2026-W39"}, "metrics": {}, "carried": [], "recommendations": []}
    prev["recommendations"] = [{"id": prev_id, "kind": kind, "weeks": 2}]
    curr = {"window": {"label": "2026-W40"}, "metrics": {}, "recommendations": []}
    curr.update({k: v for k, v in (observed or {}).items() if k in ("hooks", "ci", "rules")})
    curr["evaluation"] = scope
    return str(hr.diff_snapshots(prev, curr, 3)["statuses"][0]["status"])


class TestRound2Coverage:
    """Round 2 review：量不到的情況不可被判成已解除或錯誤的週數。"""

    def test_hwr_dt_029_events_not_covering_blocks_error_kinds(self) -> None:
        """HWR-DT-029: events 檔存在但未涵蓋觀察期 → hook-error／hook-slow 不可判定，上週建議 unmeasured；
        涵蓋且清單完整時，這支 hook 本週要有呼叫紀錄才算 resolved（HWR-DT-059..061）"""
        snap = make_snapshot()
        snap["hooks"]["events"] = {
            "files": 1,
            "covers_window": False,
            "in_window": 0,
            "hooks": {},
            "source": complete_source(),
        }
        scope = hr.evaluation_scope(snap)
        assert "hook-error" not in scope["kinds"] and "hook-slow" not in scope["kinds"]
        assert scope_diff(scope, "hook-error:foo.sh", "hook-error", snap) == "unmeasured"
        assert scope_diff(scope, "hook-slow:foo.sh", "hook-slow", snap) == "unmeasured"
        # hook 清單不完整時也不可判定（hook-error 只對已註冊 hook 產生）
        snap["hooks"]["events"]["covers_window"] = True
        snap["hooks"]["inventory"]["source"] = {"complete": False, "errors": ["x"]}
        assert "hook-error" not in hr.evaluation_scope(snap)["kinds"]
        # 涵蓋、清單完整，但這支 hook 本週沒有任何呼叫紀錄（hooks 是空的）：
        # 舊版在這裡判 resolved——「沒有紀錄」被當成「沒有問題」；現在是沒有正向證據
        snap["hooks"]["inventory"]["source"] = complete_source()
        snap["hooks"]["inventory"]["registered"] = {"foo.sh": {}}
        scope = hr.evaluation_scope(snap)
        assert scope_diff(scope, "hook-error:foo.sh", "hook-error", snap) == "unmeasured"
        assert scope_diff(scope, "hook-slow:foo.sh", "hook-slow", snap) == "unmeasured"
        # 正向對照：本週呼叫數達門檻且沒有錯誤 → 可判定，消失即 resolved
        snap["hooks"]["events"]["hooks"] = {"foo.sh": make_event_stats(calls=5)}
        assert scope_diff(scope, "hook-error:foo.sh", "hook-error", snap) == "resolved"
        assert scope_diff(scope, "hook-slow:foo.sh", "hook-slow", snap) == "resolved"

    def test_hwr_dt_030_transcript_needs_in_window_and_no_read_failure(self) -> None:
        """HWR-DT-030: transcript 窗內事件太少或來源不完整（有檔案讀取失敗）→ transcript 類不判定"""
        snap = make_snapshot()
        snap["hooks"]["events"]["hooks"] = {"x.py": make_event_stats(calls=9)}
        tr = snap["hooks"]["transcript"]
        incomplete = {"complete": False, "errors": ["transcript：x 讀取失敗"]}
        for in_window, source in ((0, complete_source()), (2, complete_source()), (5, incomplete)):
            tr.update(in_window=in_window, read_failures=1, source=source)
            scope = hr.evaluation_scope(snap)
            assert "hook-silent-block" not in scope["kinds"]
            args = ("hook-silent-block:x.py", "hook-silent-block", snap)
            assert scope_diff(scope, *args) == "unmeasured"
            assert scope_diff(scope, "hook-stale-plugin:x.py", "hook-stale-plugin", snap) == (
                "unmeasured"
            )
        tr.update(in_window=5, read_failures=0, source=complete_source())  # 正向對照
        scope = hr.evaluation_scope(snap)
        assert scope_diff(scope, "hook-silent-block:x.py", "hook-silent-block", snap) == "resolved"
        # 舊快照沒有 in_window 與 source：保守處理成量不到
        del tr["in_window"], tr["source"]
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
                "carried": [],
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
        snap["ci"]["failures"]["activity"] = {
            "workflows": {"ci.yml": 3},
            "source": complete_source(),
        }
        scope = hr.evaluation_scope(snap)
        assert "gate-silent:rule-gate-alpha.py" in scope["unevaluated_ids"]
        rid = "gate-silent:rule-gate-alpha.py"
        assert scope_diff(scope, rid, "gate-silent", snap) == "unmeasured"
        inv["gates"][0]["added"] = "2026-01-01"  # 對照：日期讀得到 → 可判定
        scope = hr.evaluation_scope(snap)
        assert scope_diff(scope, rid, "gate-silent", snap) == "resolved"

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
        """HWR-DT-037: workflow 檔讀不到 → gate 清單不完整，gate-unwired 與 gate-silent 整類不判定"""
        repo = make_gate_repo(tmp_path)
        (repo / ".github" / "workflows" / "ci.yml").write_bytes(b"\xff\xfe\x00bad")
        inv, warnings, _ = hr.collect_gate_inventory(repo)
        assert inv["source"]["complete"] is False and any("讀取失敗" in w for w in warnings)
        snap = make_snapshot()
        snap["ci"]["inventory"] = inv
        scope = hr.evaluation_scope(snap)
        assert "gate-unwired" not in scope["kinds"] and "gate-silent" not in scope["kinds"]
        assert hr.build_recommendations(snap, make_thresholds()) == []
        assert scope_diff(scope, "gate-unwired:rule-gate-alpha.py", "gate-unwired") == "unmeasured"
        assert scope_diff(scope, "gate-silent:rule-gate-alpha.py", "gate-silent") == "unmeasured"

    def test_hwr_dt_038_rule_file_unreadable(self, tmp_path: Path) -> None:
        """HWR-DT-038: 任一 rule 檔讀不到 → warning、rule 類建議整類不判定（寧可多報 unmeasured）

        舊版只讓讀不到的那一檔不判定、其他檔照常 resolved；改成整類不判定，因為來源不完整時
        連「有哪些 rule 檔」都不能確定（HWR-DT-051 rule-file-unreadable）。
        """
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
        assert scope_diff(scope, other, "rule-mechanize-candidate") == "unmeasured"
        assert data["source"]["complete"] is False  # 對照：source 才是判斷依據

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
        # gate-unwired 不需要逐對象的觀察證據，只測 unevaluated 機制本身
        base = {"kinds": ["gate-unwired", "rule-mechanize-candidate"]}
        rid = "gate-unwired:g.py"
        assert scope_diff({**base, "unevaluated_ids": [rid]}, rid, "gate-unwired") == "unmeasured"
        assert scope_diff({**base, "unevaluated_ids": []}, rid, "gate-unwired") == "resolved"
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

    def test_hwr_st_024_v2_snapshot_is_skipped(self, tmp_path: Path) -> None:
        """HWR-ST-024: v2 快照的 resolved 判定不可信（SNAPSHOT_VERSION 升為 3）：auto 略過、明確指定 exit 2"""
        assert hr.SNAPSHOT_VERSION == 3
        out = tmp_path / "out"
        out.mkdir()
        rec = {"id": "rule-heavy:r.md", "kind": "rule-heavy", "bucket": "減量", "target": "r.md"}
        rec |= {"suggestion": "s", "evidence": {}, "weeks": 2}
        (out / "snapshot-2026-W40.json").write_text(json.dumps(v2_snapshot("2026-W40", [rec])))
        v2 = {**v2_snapshot("2026-W39", [rec]), "version": 2, "carried": []}
        (out / "snapshot-2026-W39.json").write_text(json.dumps(v2))
        rc, res = self._report(out)
        assert rc == 0 and res["prev_status"] == "none_after_skip"
        assert res["skipped_incompatible"] == [str(out / "snapshot-2026-W39.json")]
        # 升級後第一週沒有可比較的上週：建議從第 1 週算起，不沿用 v2 的週數
        report = (out / "r.md").read_text()
        assert "第 3 週" not in report
        rc, _ = self._report(out, str(out / "snapshot-2026-W39.json"))
        assert rc == 2

    def test_hwr_st_025_prev_auto_bad_json_is_exit_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """HWR-ST-025: --prev auto 走訪到壞 JSON 的快照 → exit 2，不跳過它去比對更早的一份（SKILL.md 有記載）"""
        out = tmp_path / "out"
        out.mkdir()
        rec = {"id": "rule-heavy:r.md", "kind": "rule-heavy", "bucket": "減量", "target": "r.md"}
        rec |= {"suggestion": "s", "evidence": {}}
        (out / "snapshot-2026-W40.json").write_text(json.dumps(v2_snapshot("2026-W40", [rec])))
        (out / "snapshot-2026-W38.json").write_text(json.dumps(v2_snapshot("2026-W38", [rec])))
        (out / "snapshot-2026-W39.json").write_text('{"version": 3, "recommendations": [')  # 截斷
        rc, _ = self._report(out)
        assert rc == 2 and "[FAIL]" in capsys.readouterr().err
        (out / "snapshot-2026-W39.json").write_text(json.dumps(v2_snapshot("2026-W39", [rec])))
        rc, res = self._report(out)  # 對照：修好後正常找到 W39
        assert rc == 0 and res["prev"].endswith("snapshot-2026-W39.json")


# ---------------------------------------------------------------------------
# issue #509（change harden-weekly-review-measurement）：
# 來源完整性白名單、resolved 需要正向證據、精確歸因
# ---------------------------------------------------------------------------

needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root 不受檔案權限限制"
)


@contextlib.contextmanager
def unreadable(path: Path) -> Iterator[None]:
    """拿掉 path（檔案或目錄）的所有權限，離開時還原，tmp_path 才清得掉。"""
    mode = path.stat().st_mode & 0o777
    path.chmod(0)
    try:
        yield
    finally:
        path.chmod(mode)


def append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


# prev 快照裡每種建議類型各放一筆；環境健康時本週這些建議都不成立
MATRIX_RECS: dict[str, str] = {
    "unregistered": "hook-unregistered:orphan.sh",
    "no-data": "hook-no-data:a.sh",
    "low-signal": "hook-low-signal:a.sh",
    "insurance-idle": "hook-insurance-idle:protect-x.sh",
    "error": "hook-error:a.sh",
    "slow": "hook-slow:a.sh",
    "stale-plugin": "hook-stale-plugin:a.sh",
    "silent-block": "hook-silent-block:a.sh",
    "rule-heavy": "rule-heavy:.claude/rules/r.md",
    "rule-gated": "rule-already-gated:.claude/rules/r.md#Gone",
    "rule-candidate": "rule-mechanize-candidate:.claude/rules/r.md#Gone",
    "gate-unwired": "gate-unwired:rule-gate-alpha.py",
    "gate-silent": "gate-silent:rule-gate-alpha.py",
    "gate-noisy": "gate-noisy:CI / check / Check things",
}
EVENTS_KEYS = {"no-data", "low-signal", "insurance-idle", "error", "slow"}
INVENTORY_KEYS = EVENTS_KEYS | {"unregistered"}
TRANSCRIPT_KEYS = {"stale-plugin", "silent-block"}
RULE_KEYS = {"rule-heavy", "rule-gated", "rule-candidate"}
GATE_INVENTORY_KEYS = {"gate-unwired", "gate-silent"}
CI_KEYS = {"gate-silent", "gate-noisy"}


def build_matrix_env(tmp_path: Path) -> types.SimpleNamespace:
    """一個所有資料來源都健康的 repo：hook、events、transcript、rule、gate、CI 各一。"""
    repo = make_gate_repo(tmp_path)
    hooks = repo / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "a.sh").write_text("echo a\n")
    (hooks / "protect-x.sh").write_text("echo p\n")
    group = {
        "matcher": "Bash",
        "hooks": [
            {"command": ".claude/hooks/a.sh"},
            {"command": "bash .claude/hooks/protect-x.sh"},
        ],
    }
    (repo / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [group]}}))
    (repo / ".claude" / "rules").mkdir()
    (repo / ".claude" / "rules" / "r.md").write_text("# R\n\nplain text\n")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    stamps = ["2026-09-01", "2026-09-25", "2026-09-26", "2026-09-27", "2026-09-29"]
    events_file = events_dir / "demo-2026-09.jsonl"
    events_file.write_text(
        "".join(
            json.dumps({"ts": f"{d}T00:00:00Z", "hook": "a.sh", "outcome": "pass", "ms": 10}) + "\n"
            for d in stamps
        )
    )
    projects_dir = tmp_path / "projects"
    transcript_dir = projects_dir / hr.project_slug(repo)
    transcript_dir.mkdir(parents=True)
    transcript_file = transcript_dir / "s.jsonl"
    transcript_file.write_text(
        "".join(
            json.dumps({"timestamp": f"2026-09-{d}T00:00:00Z", "type": "system", "uuid": f"u{d}"})
            + "\n"
            for d in (25, 26, 27)
        )
    )
    # 巢狀的 session 目錄（worktree 的 subagent transcript 就是這個形狀）：讓「只有子目錄讀不到、
    # 頂層仍有可讀的 transcript」成為可注入的情境，os.walk 的 onerror 才會是唯一的訊號
    transcript_subdir = transcript_dir / "sub"
    transcript_subdir.mkdir()
    (transcript_subdir / "t.jsonl").write_text(
        json.dumps({"timestamp": "2026-09-28T00:00:00Z", "type": "system", "uuid": "u28"}) + "\n"
    )
    return types.SimpleNamespace(
        repo=repo,
        events_dir=events_dir,
        events_file=events_file,
        projects_dir=projects_dir,
        transcript_dir=transcript_dir,
        transcript_file=transcript_file,
        transcript_subdir=transcript_subdir,
    )


MATRIX_RUN = {"id": 7, "name": "CI", "head_branch": "x", "created_at": "2026-09-20T00:00:00Z"}


def matrix_gh(
    *,
    view_rc: int = 0,
    runs_body: str | None = None,
    activity_rc: int = 0,
    activity_body: str | None = None,
) -> Callable[[list[str]], Any]:
    """偽造 gh：repo view、一筆 failed run（gate 的 step 失敗一次）、每個 workflow 檔的 run 數。"""
    run = MATRIX_RUN
    job = {
        "name": "check",
        "conclusion": "failure",
        "steps": [{"name": "Check things", "conclusion": "failure"}],
    }
    jobs_body = json.dumps({"total_count": 1, "jobs": [job]})

    def handler(args: list[str]) -> Any:
        if args[1:3] == ["repo", "view"]:
            return cp(args, view_rc, GH_OK if view_rc == 0 else "", "" if view_rc == 0 else "boom")
        if "--paginate" in args:
            return cp(args, 0, jobs_body)
        endpoint = next(a for a in args if a.startswith("repos/"))
        if "/workflows/" in endpoint:
            if activity_rc:
                return cp(args, activity_rc, "", "HTTP 502")
            body = activity_body or json.dumps({"total_count": 5, "workflow_runs": []})
            return cp(args, 0, body)
        body = runs_body or json.dumps({"total_count": 1, "workflow_runs": [run]})
        return cp(args, 0, body)

    return handler


def run_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh: Callable[[list[str]], Any] | None = None
) -> dict[str, str]:
    """collect → diff：回傳 {MATRIX_RECS 的 key: 狀態}（prev 每種建議各一筆、本週都不成立）。"""
    install_fake_run(monkeypatch, gh or matrix_gh(), [])
    try:
        hr.main(collect_args(tmp_path / "demo", tmp_path))
    except OSError as e:
        pytest.fail(f"collect 不該因來源讀取失敗而拋出例外：{e!r}")
    curr = load(tmp_path / "out" / "snap.json")
    prev = {
        "version": hr.SNAPSHOT_VERSION,
        "window": {"label": "2026-W39"},
        "metrics": {},
        "carried": [],
        "recommendations": [
            {"id": rid, "kind": rid.split(":", 1)[0], "weeks": 1} for rid in MATRIX_RECS.values()
        ],
    }
    by_id = {s["id"]: s["status"] for s in hr.diff_snapshots(prev, curr, 3)["statuses"]}
    return {key: by_id[rid] for key, rid in MATRIX_RECS.items()}


def chmod_repo(*parts: str) -> Callable[[types.SimpleNamespace, contextlib.ExitStack], None]:
    def inject(env: types.SimpleNamespace, stack: contextlib.ExitStack) -> None:
        stack.enter_context(unreadable(env.repo.joinpath(*parts)))

    return inject


def chmod_attr(name: str) -> Callable[[types.SimpleNamespace, contextlib.ExitStack], None]:
    def inject(env: types.SimpleNamespace, stack: contextlib.ExitStack) -> None:
        stack.enter_context(unreadable(getattr(env, name)))

    return inject


def append_attr(
    name: str, text: str
) -> Callable[[types.SimpleNamespace, contextlib.ExitStack], None]:
    def inject(env: types.SimpleNamespace, stack: contextlib.ExitStack) -> None:
        append_text(getattr(env, name), text)

    return inject


def no_injection(env: types.SimpleNamespace, stack: contextlib.ExitStack) -> None:
    """gh 端的注入（回應形狀、失敗碼）只改偽造的 gh，檔案系統維持健康。"""


# 注入點名稱 → (注入動作, 依賴該來源而必須判 unmeasured 的建議, 偽造 gh 的參數)
INJECTIONS: dict[str, tuple[Any, set[str], dict[str, Any]]] = {
    "settings-unreadable": (chmod_repo(".claude", "settings.json"), INVENTORY_KEYS, {}),
    "hooks-dir-unlistable": (chmod_repo(".claude", "hooks"), INVENTORY_KEYS, {}),
    "hook-script-unreadable": (chmod_repo(".claude", "hooks", "a.sh"), INVENTORY_KEYS, {}),
    # hook-silent-block 的證據是 events 的呼叫次數：events 讀不到時呼叫數是 0
    "events-file-unreadable": (chmod_attr("events_file"), EVENTS_KEYS | {"silent-block"}, {}),
    "events-malformed-line": (append_attr("events_file", "{not json\n"), EVENTS_KEYS, {}),
    "events-dir-unlistable": (chmod_attr("events_dir"), EVENTS_KEYS | {"silent-block"}, {}),
    "transcript-truncated-line": (
        append_attr("transcript_file", '{"timestamp": "2026-09-29T00:00:00Z", "uu\n'),
        TRANSCRIPT_KEYS,
        {},
    ),
    "transcript-file-unreadable": (chmod_attr("transcript_file"), TRANSCRIPT_KEYS, {}),
    "transcript-dir-unlistable": (chmod_attr("transcript_dir"), TRANSCRIPT_KEYS, {}),
    # 頂層仍有 3 筆可讀的事件（達 TRANSCRIPT_MIN_EVENTS）：只有 os.walk 的 onerror 能發現子目錄讀不到
    "transcript-subdir-unlistable": (chmod_attr("transcript_subdir"), TRANSCRIPT_KEYS, {}),
    "projects-dir-unlistable": (chmod_attr("projects_dir"), TRANSCRIPT_KEYS, {}),
    "rules-dir-unlistable": (chmod_repo(".claude", "rules"), RULE_KEYS, {}),
    "rule-file-unreadable": (chmod_repo(".claude", "rules", "r.md"), RULE_KEYS, {}),
    "workflows-dir-unlistable": (chmod_repo(".github", "workflows"), GATE_INVENTORY_KEYS, {}),
    "workflow-file-unreadable": (
        chmod_repo(".github", "workflows", "ci.yml"),
        GATE_INVENTORY_KEYS,
        {},
    ),
    "harness-dir-unlistable": (chmod_repo("scripts", "harness"), GATE_INVENTORY_KEYS, {}),
    "ci-runs-wrong-shape": (no_injection, CI_KEYS, {"runs_body": '{"total_count": 1}'}),
    "ci-runs-total-mismatch": (
        no_injection,
        CI_KEYS,
        {"runs_body": json.dumps({"total_count": 2, "workflow_runs": [MATRIX_RUN]})},
    ),
    "ci-runs-total-missing": (
        no_injection,
        CI_KEYS,
        {"runs_body": json.dumps({"workflow_runs": [MATRIX_RUN]})},
    ),
    "ci-repo-view-fails": (no_injection, CI_KEYS, {"view_rc": 1}),
    "activity-request-fails": (no_injection, {"gate-silent"}, {"activity_rc": 1}),
}


@needs_non_root
class TestInjectionMatrix:
    """HWR-DT-050/051：每個資料來源的每個讀取失敗注入點，都不能讓依賴它的上週建議變成 resolved。"""

    def test_hwr_dt_050_control_healthy_sources_resolve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-050: 對照——所有來源健康時，prev 每種建議（本週都不成立）都判 resolved"""
        build_matrix_env(tmp_path)
        assert run_matrix(tmp_path, monkeypatch) == dict.fromkeys(MATRIX_RECS, "resolved")

    @pytest.mark.parametrize("name", sorted(INJECTIONS))
    def test_hwr_dt_051_injection_point(
        self, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-051: 注入讀取失敗 → 依賴該來源的建議 unmeasured，不相干的來源照常 resolved"""
        env = build_matrix_env(tmp_path)
        inject, expected, gh_kwargs = INJECTIONS[name]
        with contextlib.ExitStack() as stack:
            inject(env, stack)
            got = run_matrix(tmp_path, monkeypatch, matrix_gh(**gh_kwargs))
        unmeasured = {k for k, v in got.items() if v == "unmeasured"}
        resolved = {k for k, v in got.items() if v == "resolved"}
        assert unmeasured == expected, f"{name}: {got}"
        assert resolved == set(MATRIX_RECS) - expected, f"{name}: {got}"


SINCE = hr.parse_ts("2026-09-23T00:00:00Z")
NOW = hr.parse_ts("2026-09-30T00:00:00Z")
assert SINCE is not None and NOW is not None


class TestSourceRecords:
    """Requirement: Every data source reports completeness that defaults to incomplete"""

    def test_hwr_dt_052_healthy_sources_report_complete(self, tmp_path: Path) -> None:
        """HWR-DT-052: 對照——來源健康時每個 collector 都回 complete true、errors 為空"""
        env = build_matrix_env(tmp_path)
        assert SINCE is not None and NOW is not None
        inv, _, _ = hr.collect_hook_inventory(env.repo)
        events, _, _ = hr.collect_hook_events(env.events_dir, "demo", SINCE, NOW)
        transcript, _ = hr.collect_transcript_blocks(env.projects_dir, env.repo, SINCE)
        rules, _ = hr.collect_rules(env.repo, set())
        gates, _, _ = hr.collect_gate_inventory(env.repo)
        for name, data in (
            ("inventory", inv),
            ("events", events),
            ("transcript", transcript),
            ("rules", rules),
            ("gates", gates),
        ):
            assert data.get("source") == {"complete": True, "errors": []}, name

    @needs_non_root
    def test_hwr_dt_053_unreadable_hook_events_file(self, tmp_path: Path) -> None:
        """HWR-DT-053: unreadable-hook-events-file——source.complete 為 false，errors 點名該檔"""
        env = build_matrix_env(tmp_path)
        assert SINCE is not None and NOW is not None
        with unreadable(env.events_file):
            data, _, _ = hr.collect_hook_events(env.events_dir, "demo", SINCE, NOW)
        source = data.get("source") or {}
        assert source.get("complete") is False
        assert any(str(env.events_file) in e for e in source.get("errors", []))

    @needs_non_root
    def test_hwr_dt_054_unreadable_rules_directory(self, tmp_path: Path) -> None:
        """HWR-DT-054: unreadable-rules-directory——complete false，不可當成「0 條 rule」"""
        env = build_matrix_env(tmp_path)
        with unreadable(env.repo / ".claude" / "rules"):
            data, warnings = hr.collect_rules(env.repo, set())
        assert (data.get("source") or {}).get("complete") is False
        assert any(".claude/rules" in w for w in warnings), "列不出目錄要出現在 warnings"

    def test_hwr_dt_055_truncated_transcript_line(self, tmp_path: Path) -> None:
        """HWR-DT-055: truncated-transcript-line——transcript 裡不是合法 JSON 的行使 complete 為 false"""
        env = build_matrix_env(tmp_path)
        append_text(env.transcript_file, '{"timestamp": "2026-09-29T00:00:00Z", "uu\n')
        assert SINCE is not None
        data, _ = hr.collect_transcript_blocks(env.projects_dir, env.repo, SINCE)
        assert (data.get("source") or {}).get("complete") is False

    @needs_non_root
    def test_hwr_dt_056_unreadable_hook_script(self, tmp_path: Path) -> None:
        """HWR-DT-056: unreadable-hook-script——inventory 不完整，不產生 hook-unregistered"""
        env = build_matrix_env(tmp_path)
        orphan = env.repo / ".claude" / "hooks" / "orphan.sh"
        orphan.write_text("echo orphan\n")
        inv, _, _ = hr.collect_hook_inventory(env.repo)
        assert inv["unregistered"] == ["orphan.sh"] and inv["source"]["complete"] is True
        snap = make_snapshot()
        snap["hooks"]["inventory"] = inv
        control = {r["kind"] for r in hr.build_recommendations(snap, make_thresholds())}
        assert "hook-unregistered" in control  # 對照：讀得到才會產生
        with unreadable(orphan):
            inv, _, _ = hr.collect_hook_inventory(env.repo)
        assert (inv.get("source") or {}).get("complete") is False
        snap["hooks"]["inventory"] = inv
        kinds = {r["kind"] for r in hr.build_recommendations(snap, make_thresholds())}
        assert "hook-unregistered" not in kinds


class TestMissingSourceIsUnmeasured:
    """Requirement: Missing or malformed completeness fields are treated as unmeasured"""

    SOURCE_KINDS: dict[tuple[str, ...], set[str]] = {
        ("hooks", "inventory"): {
            "hook-unregistered",
            "hook-no-data",
            "hook-low-signal",
            "hook-insurance-idle",
            "hook-error",
            "hook-slow",
        },
        ("hooks", "events"): {
            "hook-no-data",
            "hook-low-signal",
            "hook-insurance-idle",
            "hook-error",
            "hook-slow",
        },
        ("hooks", "transcript"): {"hook-stale-plugin", "hook-silent-block"},
        ("rules",): {"rule-heavy", "rule-already-gated", "rule-mechanize-candidate"},
        ("ci", "inventory"): {"gate-unwired", "gate-silent"},
    }
    BAD_RECORDS: list[Any] = [
        "missing",  # 以 sentinel 代表整個欄位刪除
        "yes",
        None,
        {},
        {"complete": "true"},
        {"complete": 1},
        {"complete": False},
        {"complete": True, "errors": ["x"]},
    ]

    @staticmethod
    def _holder(snap: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
        node = snap
        for key in path:
            node = node[key]
        return node

    def test_hwr_dt_057_snapshot_without_source_record(self) -> None:
        """HWR-DT-057: snapshot-without-source-record——來源記錄缺漏、型別錯或 complete 不是 true → 不在 scope"""
        control = set(hr.evaluation_scope(make_snapshot())["kinds"])
        for path, dependent in self.SOURCE_KINDS.items():
            assert dependent <= control, f"對照：來源完整時 {path} 的類型都該在 scope 內"
            for bad in self.BAD_RECORDS:
                snap = make_snapshot()
                holder = self._holder(snap, path)
                if bad == "missing":
                    del holder["source"]
                else:
                    holder["source"] = bad
                kinds = set(hr.evaluation_scope(snap)["kinds"])
                assert not (dependent & kinds), f"{path} source={bad!r} 仍判定：{dependent & kinds}"

    def test_hwr_dt_058_snapshot_without_ci_measured(self) -> None:
        """HWR-DT-058: snapshot-without-ci-measured——ci.measured 缺漏不拋 KeyError，CI 類型不在 scope"""
        for mutate in (
            lambda s: s["ci"].pop("measured"),
            lambda s: s.pop("ci"),
            lambda s: s["ci"].update(measured="yes"),
        ):
            snap = make_snapshot()
            mutate(snap)
            kinds = set(hr.evaluation_scope(snap)["kinds"])
            assert not ({"gate-silent", "gate-noisy"} & kinds)


def gate_entry(**kw: Any) -> dict[str, Any]:
    base = {
        "script": "rule-gate-alpha.py",
        "wired_in_ci": True,
        "attributable": True,
        "ci_steps": ["Check things"],
        "added": "2026-01-01",
        "workflows": ["ci.yml"],
    }
    return {**base, **kw}


def evidence_snapshot(
    calls: dict[str, int] | None = None,
    registered: tuple[str, ...] = (),
    gates: list[dict[str, Any]] | None = None,
    runs: dict[str, int] | None = None,
) -> dict[str, Any]:
    """本週快照：所有來源完整、各類型都在 scope 內，只調整「本週觀察到什麼」。"""
    snap = make_snapshot()
    snap["window"]["label"] = "2026-W40"
    snap["hooks"]["events"]["hooks"] = {
        name: make_event_stats(calls=n) for name, n in (calls or {}).items()
    }
    snap["hooks"]["inventory"]["registered"] = {name: {} for name in registered}
    snap["ci"]["inventory"]["gates"] = gates or []
    snap["ci"]["failures"]["activity"] = {
        "workflows": runs if runs is not None else {},
        "source": complete_source(),
    }
    snap["metrics"] = {}
    snap["recommendations"] = []
    snap["evaluation"] = hr.evaluation_scope(snap)
    return snap


def status_of(kind: str, target: str, curr: dict[str, Any]) -> str:
    """上週有 kind:target、本週沒有，回傳 diff 判定的狀態。"""
    prev = {"window": {"label": "2026-W39"}, "metrics": {}, "carried": []}
    prev["recommendations"] = [{"id": f"{kind}:{target}", "kind": kind, "weeks": 2}]
    return str(hr.diff_snapshots(prev, curr, 3)["statuses"][0]["status"])


class TestPositiveEvidence:
    """Requirement: A previous recommendation is resolved only with positive evidence"""

    HOOK_KINDS = ("hook-error", "hook-slow", "hook-silent-block")

    def test_hwr_dt_059_hook_below_sample_threshold(self) -> None:
        """HWR-DT-059: hook-below-sample-threshold——本週呼叫數 < 3 → unmeasured；剛好 3 → resolved"""
        for kind in self.HOOK_KINDS:
            below = evidence_snapshot(calls={"h.sh": 2}, registered=("h.sh",))
            assert status_of(kind, "h.sh", below) == "unmeasured", kind
            at = evidence_snapshot(calls={"h.sh": 3}, registered=("h.sh",))
            assert status_of(kind, "h.sh", at) == "resolved", kind

    def test_hwr_dt_060_hook_not_observed(self) -> None:
        """HWR-DT-060: hook-not-observed——本週統計沒有這支 hook 的項目 → unmeasured"""
        curr = evidence_snapshot(calls={"other.sh": 9}, registered=("h.sh", "other.sh"))
        for kind in self.HOOK_KINDS:
            assert status_of(kind, "h.sh", curr) == "unmeasured", kind

    def test_hwr_dt_061_hook_observed_and_clean(self) -> None:
        """HWR-DT-061: hook-observed-and-clean——來源完整、呼叫數達門檻且沒有錯誤 → resolved"""
        curr = evidence_snapshot(calls={"h.sh": 5}, registered=("h.sh",))
        for kind in self.HOOK_KINDS:
            assert status_of(kind, "h.sh", curr) == "resolved", kind

    def test_hwr_dt_062_removed_hook_is_resolved_but_unseen_plugin_hook_is_not(self) -> None:
        """HWR-DT-062: hook 已從完整的 inventory 消失 → hook-error／hook-slow resolved（物件不存在）；
        hook-silent-block 的對象是 plugin hook，inventory 看不到它，不能用「不在清單」當證據"""
        curr = evidence_snapshot(calls={}, registered=())
        assert status_of("hook-error", "gone.sh", curr) == "resolved"
        assert status_of("hook-slow", "gone.sh", curr) == "resolved"
        assert status_of("hook-silent-block", "gone.sh", curr) == "unmeasured"

    def test_hwr_dt_063_gate_job_never_ran(self) -> None:
        """HWR-DT-063: gate-job-never-ran——觀察期內該 gate 所在 workflow 一次都沒跑 → unmeasured"""
        target = "rule-gate-alpha.py"
        never = evidence_snapshot(gates=[gate_entry()], runs={"ci.yml": 0})
        assert status_of("gate-silent", target, never) == "unmeasured"
        ran = evidence_snapshot(gates=[gate_entry()], runs={"ci.yml": 3})
        assert status_of("gate-silent", target, ran) == "resolved"  # 對照
        unknown = evidence_snapshot(gates=[gate_entry()], runs={})
        assert status_of("gate-silent", target, unknown) == "unmeasured"
        bad = evidence_snapshot(gates=[gate_entry()], runs={"ci.yml": 3})
        bad["ci"]["failures"]["activity"]["source"] = {"complete": False, "errors": ["x"]}
        assert status_of("gate-silent", target, bad) == "unmeasured"
        no_activity = evidence_snapshot(gates=[gate_entry()], runs={"ci.yml": 3})
        del no_activity["ci"]["failures"]["activity"]
        assert status_of("gate-silent", target, no_activity) == "unmeasured"

    def test_hwr_dt_064_gate_gone_or_unwired_is_resolved(self) -> None:
        """HWR-DT-064: gate 已從完整 inventory 消失或已不在 CI → gate-silent 的對象不存在，resolved"""
        target = "rule-gate-alpha.py"
        assert status_of("gate-silent", target, evidence_snapshot(gates=[])) == "resolved"
        unwired = evidence_snapshot(gates=[gate_entry(wired_in_ci=False, ci_steps=[])])
        assert status_of("gate-silent", target, unwired) == "resolved"

    def test_hwr_dt_065_other_kinds_need_only_complete_sources(self) -> None:
        """HWR-DT-065: 表外的類型（rule 類、gate-unwired、gate-noisy…）只看來源完整，維持舊行為"""
        curr = evidence_snapshot()
        for kind, target in (
            ("rule-heavy", "r.md"),
            ("gate-unwired", "g.py"),
            ("gate-noisy", "CI / j / s"),
            ("hook-unregistered", "o.sh"),
            ("hook-stale-plugin", "p.py"),
        ):
            assert status_of(kind, target, curr) == "resolved", kind

    def test_hwr_dt_066_transcript_kinds_need_min_events(self) -> None:
        """HWR-DT-066: transcript 類——觀察期內事件數 < 3 不判定；剛好 3 才判定"""
        for in_window, expected in ((2, "unmeasured"), (3, "resolved")):
            snap = make_snapshot()
            snap["hooks"]["transcript"]["in_window"] = in_window
            scope = hr.evaluation_scope(snap)
            snap.update(evaluation=scope, recommendations=[], metrics={})
            assert status_of("hook-stale-plugin", "p.py", snap) == expected, in_window


def attribution_repo(tmp_path: Path, step_name: str = "Check things", extra: str = "") -> Path:
    workflow = (
        "jobs:\n  check:\n    steps:\n"
        f"      - name: {step_name}\n"
        "        run: python scripts/harness/rule-gate-alpha.py\n" + extra
    )
    return make_gate_repo(tmp_path, workflow)


class TestExactAttribution:
    """Requirement: Gate attribution uses exact identity only"""

    def test_hwr_dt_067_unrelated_job_sharing_substring(self) -> None:
        """HWR-DT-067: unrelated-job-sharing-substring——名稱含 gate 字根的別的 job／step 不算 gate 的失敗"""
        snap = make_snapshot()
        snap["ci"]["inventory"]["gates"] = [
            gate_entry(script="rule-gate-docs.py", ci_steps=["Check docs"])
        ]
        for jobs in (
            {"CI / build-docs": {"failures": 3, "branches": 1, "steps": {"Build site": 3}}},
            {"CI / site": {"failures": 3, "branches": 1, "steps": {"Check docs thoroughly": 3}}},
        ):
            snap["ci"]["failures"]["jobs"] = jobs
            kinds = rec_kinds(hr.build_recommendations(snap, make_thresholds()))
            assert kinds == {"rule-gate-docs.py": "gate-silent"}, jobs
        exact = {"CI / site": {"failures": 3, "branches": 1, "steps": {"Check docs": 3}}}
        snap["ci"]["failures"]["jobs"] = exact  # 對照：step 名稱精確相同才算
        assert rec_kinds(hr.build_recommendations(snap, make_thresholds())) == {}

    def test_hwr_dt_068_dynamic_step_name_in_same_workflow(self, tmp_path: Path) -> None:
        """HWR-DT-068: dynamic-step-name——同一個 workflow 有名稱含 `${{ }}` 的 step → gate 無法歸因"""
        dynamic = "      - name: Deploy ${{ matrix.env }}\n        run: echo deploy\n"
        inv, _, notes = hr.collect_gate_inventory(attribution_repo(tmp_path / "d", extra=dynamic))
        assert inv["gates"][0]["attributable"] is False
        assert any("${{" in n for n in notes)
        snap = make_snapshot()
        snap["ci"]["inventory"] = inv
        scope = hr.evaluation_scope(snap)
        assert "gate-silent:rule-gate-alpha.py" in scope["unevaluated_ids"]
        plain = "      - name: Deploy\n        run: echo deploy\n"
        ok, _, _ = hr.collect_gate_inventory(attribution_repo(tmp_path / "p", extra=plain))
        assert ok["gates"][0]["attributable"] is True  # 對照
        other = make_gate_repo(tmp_path / "o")
        (other / ".github" / "workflows" / "other.yml").write_text(
            "jobs:\n  j:\n    steps:\n" + dynamic
        )
        elsewhere, _, _ = hr.collect_gate_inventory(other)
        assert elsewhere["gates"][0]["attributable"] is True  # 動態名稱在別的 workflow 檔不影響

    def test_hwr_dt_069_multiline_plain_name(self) -> None:
        """HWR-DT-069: multiline-plain-name——plain scalar 換行續寫的 step 名稱 → 名稱為 None"""
        text = (
            "jobs:\n  a:\n    steps:\n"
            "      - name: Check\n          things\n"
            "        run: python scripts/harness/rule-gate-alpha.py\n"
        )
        assert hr.workflow_steps(text)[0]["name"] is None
        single = text.replace("Check\n          things", "Check things")
        assert hr.workflow_steps(single)[0]["name"] == "Check things"  # 對照

    def test_hwr_dt_070_undecodable_escape_is_none(self, tmp_path: Path) -> None:
        """HWR-DT-070: 雙引號字串含無法完整解碼的跳脫序列 → yaml_scalar 回 None，不回部分字串"""
        assert hr.yaml_scalar('"Check\\tthings"') is None
        assert hr.yaml_scalar('"Check\\x41"') is None
        assert hr.yaml_scalar('"say \\"hi\\""') == 'say "hi"'  # 對照：能完整解碼的照常
        assert hr.yaml_scalar('"back\\\\slash"') == "back\\slash"
        inv, _, _ = hr.collect_gate_inventory(attribution_repo(tmp_path, '"Check\\tthings"'))
        assert inv["gates"][0]["attributable"] is False


class TestGateAddedDate:
    """Requirement: Gate added date is unknown when history cannot establish it"""

    def test_hwr_dt_071_rename_is_followed(self, tmp_path: Path) -> None:
        """HWR-DT-071: gate 改名後上線日期仍取最初加入的日期（git log --follow）"""
        repo = tmp_path / "demo"
        git_init(repo)
        harness = repo / "scripts" / "harness"
        harness.mkdir(parents=True)
        (harness / "rule-gate-old.py").write_text("print(1)\n")
        git_commit_all(repo, "2026-01-01T00:00:00")
        old, new = "scripts/harness/rule-gate-old.py", "scripts/harness/rule-gate-alpha.py"
        REAL_RUN(["git", "-C", str(repo), "mv", old, new], check=True)
        git_commit_all(repo, "2026-09-01T00:00:00")
        inv, _, _ = hr.collect_gate_inventory(repo)
        assert inv["gates"][0]["added"] == "2026-01-01"

    @pytest.mark.parametrize("probe", [(0, "true\n"), (128, ""), (0, "maybe\n")])
    def test_hwr_dt_072_shallow_or_unknown_is_unknown(
        self, probe: tuple[int, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-072: shallow-clone——shallow 或無法判斷時日期為未知，gate-silent 不判定"""
        repo = make_gate_repo(tmp_path)
        rc, out = probe

        def fake(args: list[str], **kw: Any) -> Any:
            if args[:3] == ["git", "rev-parse", "--is-shallow-repository"]:
                return cp(args, rc, out, "")
            return REAL_RUN(args, **kw)

        monkeypatch.setattr(hr.subprocess, "run", fake)
        inv, _, _ = hr.collect_gate_inventory(repo)
        assert inv["gates"][0]["added"] is None
        snap = make_snapshot()
        snap["ci"]["inventory"] = inv
        scope = hr.evaluation_scope(snap)
        assert "gate-silent:rule-gate-alpha.py" in scope["unevaluated_ids"]
        assert status_of("gate-silent", "rule-gate-alpha.py", {**snap, **_blank_week(scope)}) == (
            "unmeasured"
        )

    def test_hwr_dt_073_full_clone_keeps_date(self, tmp_path: Path) -> None:
        """HWR-DT-073: 對照——不是 shallow 時日期照常取得"""
        inv, _, _ = hr.collect_gate_inventory(make_gate_repo(tmp_path))
        assert inv["gates"][0]["added"] == "2026-01-01"


def _blank_week(scope: dict[str, Any]) -> dict[str, Any]:
    return {"evaluation": scope, "recommendations": [], "metrics": {}}


class TestCollectOnlyPrevious:
    """Requirement: Streaks reset visibly when the previous snapshot lacks carry data"""

    @staticmethod
    def _snap(label: str, recs: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        return {
            "window": {"label": label},
            "metrics": {},
            "recommendations": recs,
            "evaluation": {"kinds": ["a"], "unevaluated_ids": []},
            **extra,
        }

    def test_hwr_dt_074_previous_snapshot_collect_only(self) -> None:
        """HWR-DT-074: previous-snapshot-collect-only——沒有 carried／weeks 的上週快照 → streak 重設並說明原因"""
        prev = self._snap(
            "2026-W39", [{"id": "a:x", "kind": "a"}, {"id": "a:gone", "kind": "a"}]
        )  # 只跑過 collect：沒有 carried，建議也沒有 weeks
        curr = self._snap("2026-W40", [{"id": "a:x", "kind": "a"}])
        curr["evaluation"] = {"kinds": [], "unevaluated_ids": []}  # a:gone 本週量不到
        delta = hr.diff_snapshots(prev, curr, 3)
        by_id = {s["id"]: s for s in delta["statuses"]}
        assert by_id["a:x"]["status"] == "persisting" and by_id["a:x"]["weeks"] == 1
        assert by_id["a:x"].get("streak_reset") is True
        assert by_id["a:gone"]["status"] == "unmeasured"
        assert by_id["a:gone"].get("streak_reset") is True
        assert delta.get("prev_collect_only") is True
        report = hr.render_report(v2_snapshot("2026-W40"), delta)
        assert "只跑過 collect" in report

    def test_hwr_dt_075_report_written_previous_keeps_streak(self) -> None:
        """HWR-DT-075: 對照——上週快照有 carried 與 weeks 時週數照常累加、不標 streak_reset"""
        prev = self._snap("2026-W39", [{"id": "a:x", "kind": "a", "weeks": 2}], carried=[])
        curr = self._snap("2026-W40", [{"id": "a:x", "kind": "a"}])
        delta = hr.diff_snapshots(prev, curr, 3)
        st = delta["statuses"][0]
        assert (st["status"], st["weeks"], st.get("streak_reset")) == ("persisting", 3, None)
        assert delta.get("prev_collect_only") is False
        assert "只跑過 collect" not in hr.render_report(v2_snapshot("2026-W40"), delta)

    def test_hwr_dt_076_no_previous_is_not_collect_only(self) -> None:
        """HWR-DT-076: 第一次執行（沒有上週快照）不是 collect-only"""
        delta = hr.diff_snapshots(None, self._snap("2026-W40", [{"id": "a:x", "kind": "a"}]), 3)
        assert delta.get("prev_collect_only") is False


class TestCiRunsShape:
    """Requirement: CI run listing is verified against its declared total"""

    @pytest.mark.parametrize(
        "body",
        [
            '{"total_count": 0}',  # runs-response-wrong-shape：沒有 workflow_runs
            '{"workflow_runs": []}',  # 沒有 total_count
            '{"total_count": 3, "workflow_runs": []}',  # 宣告 3 筆、只列到 0 筆
            '{"total_count": 0, "workflow_runs": "x"}',  # workflow_runs 不是清單
        ],
    )
    def test_hwr_dt_077_runs_response_shape(
        self, body: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-077: runs-response-wrong-shape——回應形狀不符或筆數對不上 total_count → CI 不完整"""
        repo = make_gate_repo(tmp_path)
        install_fake_run(monkeypatch, make_gh(runs_out=body), [])
        hr.main(collect_args(repo, tmp_path))
        snap = load(tmp_path / "out" / "snap.json")
        assert snap["ci"]["measured"] is False
        assert (snap["ci"]["failures"].get("source") or {}).get("complete") is False

    def test_hwr_dt_078_matching_total_is_measured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HWR-DT-078: 對照——筆數與 total_count 相符才 measured"""
        repo = make_gate_repo(tmp_path)
        install_fake_run(monkeypatch, make_gh(runs=[]), [])
        hr.main(collect_args(repo, tmp_path))
        snap = load(tmp_path / "out" / "snap.json")
        assert snap["ci"]["measured"] is True
        assert snap["ci"]["failures"]["source"] == {"complete": True, "errors": []}
        activity = snap["ci"]["failures"].get("activity") or {}
        assert activity.get("workflows") == {"ci.yml": 5}
        assert activity.get("source") == {"complete": True, "errors": []}


class TestCollectWiring:
    def test_hwr_dt_079_max_rule_candidates_wiring(self, tmp_path: Path) -> None:
        """HWR-DT-079: cmd_collect 把 --max-rule-candidates 同時接到建議產生與 evaluation scope
        （issue #509 的 C5：HWR-DT-034 直接呼叫函式，接線與截斷邊界沒有端到端的測試）"""
        repo = tmp_path / "demo"
        git_init(repo)
        rules = repo / ".claude" / "rules"
        rules.mkdir(parents=True)
        body = "必須 `a` `b` `c` `d`。不要 `e` `f` `g` `h`。一律 `i`。\n"
        (rules / "03.md").write_text("".join(f"## S{i:02d}\n\n{body}\n" for i in range(5)))
        out = tmp_path / "out" / "snap.json"
        args = ["collect", "--repo", str(repo), "--out", str(out), "--no-ci"]
        args += ["--now", "2026-09-30T00:00:00Z", "--max-rule-candidates", "2"]
        args += ["--events-dir", str(tmp_path / "ev"), "--projects-dir", str(tmp_path / "p")]
        assert hr.main(args) in (0, 3)
        snap = load(out)
        anchors = [c["anchor"] for c in snap["rules"]["candidates"]]
        assert len(anchors) == 5  # collect 不截斷：全部候選都存進快照
        kept = {
            r["target"] for r in snap["recommendations"] if r["kind"] == "rule-mechanize-candidate"
        }
        assert kept == set(anchors[:2])
        unevaluated = set(snap["evaluation"]["unevaluated_ids"])
        for rank, anchor in enumerate(anchors):
            for kind in hr.RULE_CANDIDATE_KINDS:
                # 邊界：排名第 2（含）以內判定，第 3 名起不判定；差一名都會被抓到
                assert (f"{kind}:{anchor}" in unevaluated) is (rank >= 2), (rank, kind)

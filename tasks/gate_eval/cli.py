"""CLI 入口：Evidence gate conformance eval。

三個子命令：eval（跑判定與報告）、mutation-verify（驗 fixture 的 mutation anchor）、
sunset-report（產 prune 與 sunset 建議）。刻意不註冊任何 pre-commit hook 或 merge 阻擋——
移除成本因此維持在刪一個目錄加一個排程項目。
"""

import json
from pathlib import Path

import click

SKILL_REL = "plugins/pr-flow/skills/pr-cycle-deep/SKILL.md"


@click.group()
def cli() -> None:
    """Evidence gate conformance eval（disposition 符合度量測 + sunset 協議）。"""


def _skill_path() -> Path:
    from tasks._paths import PROJECT_ROOT

    return PROJECT_ROOT / SKILL_REL


@cli.command()
@click.option(
    "--dispositions", "disp_file", type=click.Path(path_type=Path), help="已記錄的 disposition JSON"
)
@click.option("--emit-manifest", is_flag=True, help="只印判定任務 manifest（供 agent 逐一判定）")
@click.option("--runs", "-n", default=None, type=int, help="每個 fixture 判定次數（預設 5）")
@click.option("--findings-dir", type=click.Path(path_type=Path), help="fixture 目錄（測試用）")
@click.option(
    "--oracle", "oracle_file", type=click.Path(path_type=Path), help="oracle 路徑（測試用）"
)
def eval(  # noqa: A001 — spec 要求的子命令名，與內建 eval() 無關
    disp_file: Path | None,
    emit_manifest: bool,
    runs: int | None,
    findings_dir: Path | None,
    oracle_file: Path | None,
) -> None:
    """載入 fixtures、核對 oracle 一致性，依已記錄 disposition 產出三值判定與報告。"""
    from .config import check_fixture_oracle_consistency, load_fixtures, load_oracle
    from .service import INITIAL_N

    n = runs if runs is not None else INITIAL_N
    try:
        oracle = load_oracle(oracle_file)
        fixtures = load_fixtures(findings_dir)
        check_fixture_oracle_consistency(fixtures, oracle)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from e

    if emit_manifest:
        manifest = [
            {"fixture_id": fx.id, "run": i, "finding_text": fx.finding_text}
            for fx in fixtures.fixtures
            for i in range(n)
        ]
        click.echo(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    if disp_file is None:
        click.echo(
            "[FAIL] 請提供 --dispositions <file>，或先以 --emit-manifest 產生判定任務", err=True
        )
        raise SystemExit(1)

    from .models import Disposition, RunOutcome
    from .service import evaluate_fixture

    try:
        recorded = json.loads(disp_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"[FAIL] 讀取 dispositions 失敗：{disp_file}", err=True)
        raise SystemExit(1) from e

    verdicts = []
    nonconformant = 0
    for fx in fixtures.fixtures:
        raw = recorded.get(fx.id, [])
        outcomes = [
            RunOutcome(disposition=Disposition(d)) if d else RunOutcome(error="執行失敗")
            for d in raw
        ]
        fv = evaluate_fixture(fx.id, fx.expected_disposition, outcomes)
        verdicts.append(fv)
        if fv.verdict.value != "conformant":
            nonconformant += 1

    from .models import ConservationResult
    from .service import render_report

    # 守恆檢查在此 CLI 未帶輸出 finding 時視為 vacuously ok（守恆對照見單元測試）。
    click.echo(render_report(ConservationResult(ok=True), verdicts))
    if nonconformant:
        click.echo(f"[FAIL] {nonconformant} 個 fixture 非 CONFORMANT", err=True)
        raise SystemExit(1)
    click.echo("[OK] 全部 CONFORMANT")


@cli.command("mutation-verify")
@click.option("--findings-dir", type=click.Path(path_type=Path), help="fixture 目錄（測試用）")
@click.option(
    "--skill", "skill_file", type=click.Path(path_type=Path), help="目標 SKILL.md（測試用）"
)
def mutation_verify(findings_dir: Path | None, skill_file: Path | None) -> None:
    """核對每個 fixture 的 mutation anchor 都存在於目標 SKILL.md；任一缺失即 [FAIL]。

    這是 mutation 驗證的可決定性部分（anchor 在場即可套用）。實際「套用 mutation ->
    重跑 agent -> 確認由 CONFORMANT 轉 NONCONFORMANT」需 agent session，見 change 的驗收 runbook。
    """
    from .config import load_fixtures

    target = skill_file or _skill_path()
    if not target.is_file():
        click.echo(f"[FAIL] 找不到目標 SKILL.md：{target}", err=True)
        raise SystemExit(1)
    text = target.read_text(encoding="utf-8")
    try:
        fixtures = load_fixtures(findings_dir)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from e

    missing = [fx.id for fx in fixtures.fixtures if fx.mutation.anchor not in text]
    for fx in fixtures.fixtures:
        status = "[OK]" if fx.mutation.anchor in text else "[FAIL]"
        click.echo(f"  {status} {fx.id}: {fx.mutation.anchor}")
    if missing:
        click.echo(
            f"[FAIL] 下列 fixture 的 anchor 在 SKILL.md 中找不到：{', '.join(missing)}", err=True
        )
        raise SystemExit(1)
    click.echo(f"[OK] {len(fixtures.fixtures)} 個 fixture 的 mutation anchor 皆在場")


@cli.command("sunset-report")
@click.option(
    "--window",
    "window_file",
    required=True,
    type=click.Path(path_type=Path),
    help="窗口狀態 JSON（fixture 紀錄 + suite 窗口 + superseded 旗標）",
)
def sunset_report(window_file: Path) -> None:
    """依窗口狀態產出每個 fixture 的 prune 建議與 suite 層 sunset 求值。"""
    from .models import FixtureWindowRecord, SuiteWindow
    from .sunset import classify_prune, evaluate_suite_sunset

    try:
        data = json.loads(window_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"[FAIL] 讀取窗口狀態失敗：{window_file}", err=True)
        raise SystemExit(1) from e

    records = [FixtureWindowRecord.model_validate(r) for r in data.get("fixtures", [])]
    windows = [SuiteWindow.model_validate(w) for w in data.get("windows", [])]
    superseded = bool(data.get("superseded_by_code", False))

    click.echo("## fixture prune 建議")
    for rec in records:
        r = classify_prune(rec)
        click.echo(f"  {r.fixture_id}: {r.action} — {r.reason}")

    suite = evaluate_suite_sunset(windows, superseded)
    click.echo("## suite sunset 求值")
    if suite.due_for_removal:
        click.echo(f"  [DUE] 進入移除評估，觸發：{', '.join(t.value for t in suite.triggers)}")
        for note in suite.notes:
            click.echo(f"    - {note}")
    else:
        click.echo("  [OK] 未觸發任何 sunset 條件")

"""CLI 入口：skill 觸發準確度評測。"""

import json
from pathlib import Path

import click

from .models import TriggerEvalFixture


@click.group()
def cli() -> None:
    """skill 觸發準確度評測（trigger-eval runner + regression gate）。"""


def _resolve_skills(skill: tuple[str, ...], all_skills: bool, skills_dir: Path | None) -> list[str]:
    """決定要評測的 skill 清單；缺選擇時報錯退出。"""
    from .config import discover_fixtures

    if all_skills:
        names = discover_fixtures(skills_dir)
        if not names:
            click.echo("[FAIL] 找不到任何含 trigger_eval.json 的 skill", err=True)
            raise SystemExit(1)
        return names
    if skill:
        return list(skill)
    click.echo("[FAIL] 請以 --skill <name>（可多次）或 --all 指定要評測的 skill", err=True)
    raise SystemExit(1)


def _load_fixtures(names: list[str], skills_dir: Path | None) -> list[TriggerEvalFixture]:
    """載入指定 skill 的 fixture；任一缺失或格式錯誤即報錯退出。"""
    from .config import load_fixture

    fixtures: list[TriggerEvalFixture] = []
    for name in names:
        try:
            fixtures.append(load_fixture(name, skills_dir))
        except RuntimeError as e:
            click.echo(f"[FAIL] {e}", err=True)
            raise SystemExit(1) from e
    return fixtures


def _read_judgments(path: Path) -> list[bool]:
    """讀取 judgments 檔（JSON 布林陣列）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"[FAIL] 讀取 judgments 失敗：{path}", err=True)
        raise SystemExit(1) from e
    if not isinstance(data, list) or not all(isinstance(x, bool) for x in data):
        click.echo("[FAIL] judgments 檔必須是布林值陣列（每個 task 是否觸發）", err=True)
        raise SystemExit(1)
    return data


@cli.command()
@click.option("--skill", "-s", multiple=True, help="要評測的 skill（可多次）")
@click.option("--all", "all_skills", is_flag=True, help="評測所有含 fixture 的 skill")
@click.option("--emit-manifest", is_flag=True, help="只印判斷任務 manifest（供 agent 判斷）")
@click.option(
    "--judgments",
    "judgments_file",
    type=click.Path(path_type=Path),
    help="judgments JSON（布林陣列）",
)
@click.option("--tolerance", default=None, type=float, help="回歸容忍門檻（預設 0.1）")
@click.option(
    "--baseline", "baseline_file", type=click.Path(path_type=Path), help="baseline 檔路徑"
)
@click.option("--skills-dir", type=click.Path(path_type=Path), help="skills 目錄（測試用）")
# 注意：此處 eval 是 spec 要求的 CLI subcommand 名稱（Click 以函式名為指令名），
# 與 Python 內建 eval() 無關，不執行任意程式碼。
def eval(  # noqa: A001 — 對映 spec「eval subcommand」命名
    skill: tuple[str, ...],
    all_skills: bool,
    emit_manifest: bool,
    judgments_file: Path | None,
    tolerance: float | None,
    baseline_file: Path | None,
    skills_dir: Path | None,
) -> None:
    """評測 skill 觸發準確度並與 baseline 比對；偵測到回歸時 exit 1。"""
    from .config import load_baseline
    from .judges import AgentJudge
    from .service import DEFAULT_TOLERANCE, build_tasks, run_eval

    names = _resolve_skills(skill, all_skills, skills_dir)
    fixtures = _load_fixtures(names, skills_dir)
    tasks = build_tasks(fixtures)

    if emit_manifest:
        click.echo(json.dumps([t.model_dump() for t in tasks], ensure_ascii=False, indent=2))
        return

    if judgments_file is None:
        click.echo("[FAIL] 請提供 --judgments <file> 或改用 --emit-manifest 產生任務清單", err=True)
        raise SystemExit(1)

    judgments = _read_judgments(judgments_file)
    judge = AgentJudge()
    tol = DEFAULT_TOLERANCE if tolerance is None else tolerance
    try:
        report = run_eval(judge, tasks, judgments, load_baseline(baseline_file), tol)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from e

    for result in report.results:
        click.echo(f"{result.skill}")
        for score in result.scores:
            click.echo(f"  {score.cls}: {score.passed}/{score.total} = {score.pass_rate:.2f}")
    if report.has_regression:
        click.echo("[FAIL] 偵測到觸發回歸：", err=True)
        for reg in report.regressions:
            click.echo(
                f"  {reg.skill} {reg.cls}: {reg.current:.2f} < baseline {reg.baseline:.2f} - {tol}",
                err=True,
            )
        raise SystemExit(1)
    click.echo("[OK] 無回歸")


@cli.command()
@click.option("--skill", "-s", multiple=True, help="要寫入 baseline 的 skill（可多次）")
@click.option("--all", "all_skills", is_flag=True, help="所有含 fixture 的 skill")
@click.option(
    "--judgments",
    "judgments_file",
    required=True,
    type=click.Path(path_type=Path),
    help="judgments JSON（布林陣列）",
)
@click.option(
    "--baseline", "baseline_file", type=click.Path(path_type=Path), help="baseline 檔路徑"
)
@click.option("--skills-dir", type=click.Path(path_type=Path), help="skills 目錄（測試用）")
def baseline(
    skill: tuple[str, ...],
    all_skills: bool,
    judgments_file: Path,
    baseline_file: Path | None,
    skills_dir: Path | None,
) -> None:
    """以當前 judgments 計算 pass rate 並寫成新的 baseline。"""
    from .config import save_baseline
    from .judges import AgentJudge
    from .service import build_tasks, results_to_baseline, score_verdicts

    names = _resolve_skills(skill, all_skills, skills_dir)
    fixtures = _load_fixtures(names, skills_dir)
    tasks = build_tasks(fixtures)
    judgments = _read_judgments(judgments_file)

    judge = AgentJudge()
    try:
        verdicts = judge.score(judge.build_manifest(tasks), judgments)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from e

    baseline_data = results_to_baseline(score_verdicts(verdicts))
    path = save_baseline(baseline_data, baseline_file)
    click.echo(f"[OK] baseline 已寫入：{path}")

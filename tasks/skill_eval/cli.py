"""CLI 入口：skill 觸發準確度評測。"""

import json
from pathlib import Path

import click

from .models import JudgeTask, TriggerEvalFixture


@click.group()
def cli() -> None:
    """skill 觸發準確度評測（trigger-eval runner + regression gate）。"""


def _warn_orphan_fixtures(skills_dir: Path | None) -> None:
    """--all 時顯式警告 plugins/ 底下未被涵蓋的 fixture，避免靜默漏評。

    custom skills_dir（測試/非預設佈局）比對其 sibling `plugins/`，不誤報 repo 全域
    plugins；預設佈局（skills_dir=None）比對 repo 的 PLUGINS_DIR。輸出相對路徑。
    """
    from tasks._paths import PROJECT_ROOT

    from .config import orphan_plugin_fixtures

    plugins_dir = (skills_dir.parent / "plugins") if skills_dir is not None else None
    orphans = orphan_plugin_fixtures(skills_dir, plugins_dir)
    if not orphans:
        return
    base = skills_dir.parent if skills_dir is not None else PROJECT_ROOT
    # 只陳述可觀察事實（未被涵蓋），不斷言成因：巢狀 sub-skill 的 fixture 即使 symlink 存在，
    # 也會因 discover_fixtures 只掃 skills/ 第一層而落在此清單——說「未 symlink」會叫使用者
    # 去建一個早就存在的 symlink。
    click.echo(
        f"[WARN] --all 只涵蓋 skills/ 第一層的 fixture；下列 {len(orphans)} 個 plugin 底下的 "
        "fixture 未被評測：",
        err=True,
    )
    for path in orphans:
        try:
            shown: Path = path.relative_to(base)
        except ValueError:
            shown = path
        click.echo(f"  {shown}", err=True)


def _assert_nonempty_fixtures(fixtures: list[TriggerEvalFixture]) -> None:
    """每個 fixture 至少要有一個 prompt；否則 [FAIL]。

    per-skill 檢查（非 aggregate）：--all 下某個三類全空的 fixture 不會靜默地從
    regression gate 消失（score_verdicts/compare_baseline 只走有 verdict 的 skill）。

    範圍僅止於「三類皆空」。單一類別被清空（如只刪 negative）仍會靜默離開 gate——
    那是 compare_baseline 只走當前 results、不走 baseline ∪ current 的結構性問題，
    見 issue #219，不在此 guard 涵蓋範圍內。
    """
    empty = [fx.skill for fx in fixtures if not (fx.direct or fx.indirect or fx.negative)]
    if empty:
        click.echo(
            f"[FAIL] 下列 skill 的 fixture 三類皆空，無可評測項目：{', '.join(empty)}",
            err=True,
        )
        raise SystemExit(1)


def _validate_tolerance(tolerance: float) -> float:
    """容忍門檻須落在 [0.0, 1.0)；否則 [FAIL]。

    nan 會讓所有 `pass_rate < base - tol` 比較恆為 False，>= 1.0 則讓門檻寬到永遠不觸發——
    兩者都是「gate 靜默失效」而非「gate 較寬鬆」，故不接受。

    單一值域比較即可涵蓋 nan 與 ±inf，無須另加 math.isfinite()：nan 的所有比較皆為 False，
    故 `0.0 <= nan` 為 False；inf 則卡在 `< 1.0`。額外的 isfinite() 是永不改變結果的死碼。
    """
    if not 0.0 <= tolerance < 1.0:
        click.echo(
            f"[FAIL] --tolerance 須落在 0.0 <= t < 1.0，收到：{tolerance}"
            "（nan 或 >= 1.0 會讓回歸偵測恆不觸發，等同關閉 gate）",
            err=True,
        )
        raise SystemExit(1)
    return tolerance


def _resolve_skills(skill: tuple[str, ...], all_skills: bool, skills_dir: Path | None) -> list[str]:
    """決定要評測的 skill 清單；缺選擇時報錯退出。"""
    from .config import discover_fixtures

    if all_skills:
        names = discover_fixtures(skills_dir)
        # 先報 orphan 再判空：全部 fixture 都是 plugin-only 時 names 為空，此處若先 [FAIL]
        # 就會告訴使用者「找不到任何 fixture」，而實際上有 N 個躺在 plugins/ 只是搆不到——
        # 正是這個 [WARN] 存在的理由。
        _warn_orphan_fixtures(skills_dir)
        if not names:
            click.echo("[FAIL] 找不到任何含 trigger_eval.json 的 skill（skills/ 底下）", err=True)
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


def _check_manifest_binding(manifest_file: Path, tasks: list[JudgeTask]) -> None:
    """核對先前 emit 的 manifest 與當前 build_tasks，攔截 judgments 對位錯亂造成的靜默錯誤。

    不符代表 manifest 與當前任務清單不對應——fixture 在 emit-manifest 後變動，或 --skill/--all
    的選擇與 emit 當下不同，或傳入了別的 skills-dir 產生的 manifest。三者都讓 index 對位失效，
    故一律 [FAIL]；此處無法（也不需要）分辨是哪一種。
    """
    from .service import manifest_signature

    try:
        saved = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"[FAIL] 讀取 manifest 失敗：{manifest_file}", err=True)
        raise SystemExit(1) from e
    if not isinstance(saved, list) or not all(isinstance(t, dict) for t in saved):
        click.echo("[FAIL] manifest 檔格式錯誤（應為 emit-manifest 產出的任務陣列）", err=True)
        raise SystemExit(1)
    saved_sig = [
        [t.get("index"), t.get("skill"), t.get("cls"), t.get("prompt"), t.get("expect_trigger")]
        for t in saved
    ]
    if saved_sig != manifest_signature(tasks):
        click.echo(
            "[FAIL] manifest 與當前 fixture 不符（fixture 可能在 emit-manifest 後變動）；"
            "請重新 --emit-manifest 並重判 judgments",
            err=True,
        )
        raise SystemExit(1)


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
@click.option(
    "--manifest",
    "manifest_file",
    type=click.Path(path_type=Path),
    help="先前 --emit-manifest 的輸出；核對 fixture 未在其間變動（與 --judgments 併用時必要）",
)
@click.option(
    "--no-manifest-check",
    is_flag=True,
    help="顯式跳過 fixture 漂移核對（不建議；漂移將靜默產生錯誤 pass rate）",
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
    manifest_file: Path | None,
    no_manifest_check: bool,
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
    _assert_nonempty_fixtures(fixtures)
    tasks = build_tasks(fixtures)

    if emit_manifest:
        click.echo(json.dumps([t.model_dump() for t in tasks], ensure_ascii=False, indent=2))
        return

    if judgments_file is None:
        click.echo("[FAIL] 請提供 --judgments <file> 或改用 --emit-manifest 產生任務清單", err=True)
        raise SystemExit(1)

    if manifest_file is None and not no_manifest_check:
        click.echo(
            "[FAIL] 請提供 --manifest <file>（--emit-manifest 的輸出）以核對 fixture 未在其間變動。"
            "judgments 依 index 對位，fixture 一改就會靜默錯位；judgments 必然來自先前的 "
            "--emit-manifest，故一定有 manifest 可傳。確需跳過請顯式加 --no-manifest-check",
            err=True,
        )
        raise SystemExit(1)
    if manifest_file is not None:
        _check_manifest_binding(manifest_file, tasks)
    else:
        click.echo(
            "[WARN] --no-manifest-check：跳過 fixture 漂移核對。同數量的 fixture 變動"
            "（改字、換順序、翻 expect_trigger、改 skill 名）皆不會被偵測，pass rate 可能靜默錯誤",
            err=True,
        )

    judgments = _read_judgments(judgments_file)
    judge = AgentJudge()
    tol = DEFAULT_TOLERANCE if tolerance is None else _validate_tolerance(tolerance)
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
    "--manifest",
    "manifest_file",
    required=True,
    type=click.Path(path_type=Path),
    help="先前 --emit-manifest 的輸出；核對 fixture 未在其間變動（baseline 寫入持久狀態，故必要）",
)
@click.option(
    "--baseline", "baseline_file", type=click.Path(path_type=Path), help="baseline 檔路徑"
)
@click.option("--skills-dir", type=click.Path(path_type=Path), help="skills 目錄（測試用）")
def baseline(
    skill: tuple[str, ...],
    all_skills: bool,
    judgments_file: Path,
    manifest_file: Path,
    baseline_file: Path | None,
    skills_dir: Path | None,
) -> None:
    """以當前 judgments 計算 pass rate 並寫成新的 baseline。

    --manifest 在此為必要（eval 可用 --no-manifest-check 跳過，baseline 不行）：eval 算錯只是
    一次性輸出，baseline 卻會把錯位的 pass rate 寫成往後每次 gate 的比較基準，污染是持久的。
    """
    from .config import save_baseline
    from .judges import AgentJudge
    from .service import build_tasks, results_to_baseline, score_verdicts

    names = _resolve_skills(skill, all_skills, skills_dir)
    fixtures = _load_fixtures(names, skills_dir)
    _assert_nonempty_fixtures(fixtures)
    tasks = build_tasks(fixtures)
    _check_manifest_binding(manifest_file, tasks)
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

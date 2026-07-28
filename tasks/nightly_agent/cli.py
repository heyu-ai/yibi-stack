"""CLI 入口：夜間自我改善 Agent。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import click

from tasks._paths import RUNTIME_DIR


@click.group()
def cli() -> None:
    """夜間自我改善 Agent — 讀取 transcripts、聚類 friction、草擬預防規則、開 PR。"""


@cli.command()
@click.option("--hours", default=24, help="回溯時間視窗（小時）")
@click.option("--dry-run", is_flag=True, help="只分析，不草擬 artifact 或開 PR")
@click.option("--config", "config_path", default=None, type=click.Path(), help="設定檔路徑")
def run(hours: int, dry_run: bool, config_path: str | None) -> None:
    """執行完整的夜間分析 → 聚類 → 草擬 → 測試 → PR 流程。"""
    from .classifier import FrictionClassifier, classify_mycelium_lessons
    from .clusterer import FrictionClusterer
    from .config import load_config
    from .drafter import ArtifactDrafter
    from .extractor import TranscriptExtractor
    from .governance import FrictionRegistry
    from .pr_creator import PRCreator
    from .tester import TestValidator, _get_main_repo

    config = load_config(Path(config_path) if config_path else None)
    config.lookback_hours = hours

    date_str = datetime.now().strftime("%Y-%m-%d")
    errors: list[str] = []
    # errors 是給 digest 看的完整記錄（含已知的良性降級，例如舊 handover.db 缺 lessons
    # table、或 friction 已被處理而 test 提前通過）；fatal_errors 只收真正的執行失敗
    # （草擬 / PR 建立 / friction-state 寫入的 RuntimeError，以及驗證後仍失敗的 test）。
    # 排程的 exit code 只看 fatal_errors，避免良性降級被誤報成「排程失敗」。
    fatal_errors: list[str] = []
    from .models import PRRecord

    prs: list[PRRecord] = []
    skipped = 0

    # --- Step 1: Extract transcripts ---
    click.echo(f"[1/6] 讀取最近 {hours}h transcript sessions …")
    extractor = TranscriptExtractor(lookback_hours=hours)
    sessions = extractor.extract(extra_paths=config.extra_transcript_paths)
    click.echo(f"      {len(sessions)} sessions found")

    # --- Step 2: Read mycelium lessons ---
    click.echo("[2/6] 讀取 mycelium lessons …")
    lessons = _load_mycelium_lessons(hours, config.lesson_types, errors, fatal_errors)
    click.echo(f"      {len(lessons)} lessons found")

    # --- Step 3: Classify friction events ---
    click.echo("[3/6] 分類 friction events …")
    classifier = FrictionClassifier()
    events = classifier.classify(sessions)
    events += classify_mycelium_lessons(lessons)
    click.echo(f"      {len(events)} friction events found")

    # --- Step 4: Cluster ---
    click.echo("[4/6] 聚類 friction events …")
    clusterer = FrictionClusterer(
        threshold=config.jaccard_threshold,
        min_cluster_size=config.min_cluster_size,
    )
    all_clusters = clusterer.cluster(events)
    eligible = clusterer.eligible(all_clusters)
    click.echo(
        f"      {len(all_clusters)} clusters ({len(eligible)} eligible ≥{config.min_cluster_size})"
    )

    if not eligible:
        click.echo("[INFO] 沒有 eligible clusters，結束。")
        _finalize_run(
            config, date_str, hours, events, all_clusters, prs, skipped, errors, fatal_errors
        )
        return

    if dry_run:
        click.echo("[DRY RUN] Eligible clusters:")
        for c in eligible:
            click.echo(f"  {c.friction_type} ×{c.count}: {', '.join(c.common_keywords[:5])}")
        _finalize_run(
            config, date_str, hours, events, all_clusters, prs, skipped, errors, fatal_errors
        )
        return

    # --- Step 5: Draft & validate ---
    click.echo("[5/6] 草擬 artifacts 並驗證 failing→passing test …")
    drafter = ArtifactDrafter(config)
    tester = TestValidator(config.generated_tests_dir)
    registry = FrictionRegistry(config.friction_state_file, _get_main_repo(), config.github_repo)

    for cluster in eligible:
        duplicate_reason = registry.find_duplicate(cluster)
        if duplicate_reason:
            click.echo(
                f"  [SKIP] 重複 friction（{cluster.friction_type}）：{duplicate_reason}", err=True
            )
            skipped += 1
            continue
        try:
            proposal = drafter.draft(cluster)
        except RuntimeError as e:
            click.echo(f"  [SKIP] 草擬失敗 ({cluster.friction_type}): {e}", err=True)
            errors.append(str(e))
            fatal_errors.append(str(e))
            skipped += 1
            continue

        result = tester.validate(proposal)
        if not result.passed:
            click.echo(f"  [SKIP] test 未通過 ({proposal.title}): {result.error}", err=True)
            errors.append(f"test failed: {proposal.title}")
            if result.previously_failed:
                # 套用 artifact 前 test 本來就失敗，套用後仍失敗 -> 驗證真的沒過，是執行失敗。
                fatal_errors.append(f"test failed: {proposal.title}")
            else:
                # 套用 artifact 前 test 就已經通過，代表 friction 已被處理，不是失敗。
                click.echo("  [INFO] test 在 artifact 前就通過，代表 friction 已被處理", err=True)
            skipped += 1
            continue

        # --- Step 6: Create PR ---
        try:
            pr_creator = PRCreator(config)
            pr_record = pr_creator.create_pr(proposal, result)
            prs.append(pr_record)
            click.echo(f"  [OK] PR #{pr_record.pr_number}: {pr_record.pr_url}")
            if not pr_record.cleanup_ok:
                # PR 本身已成功建立（GitHub 上真的存在），不因清理未完全乾淨而回報這次
                # create_pr 失敗；但排程層需要知道「這次執行沒有完全乾淨」，所以計入
                # fatal_errors 讓 exit code 反映出來，不影響已開的 PR。
                click.echo(
                    f"  [WARN] PR 已建立，但 worktree/分支清理未完全成功：{pr_record.branch}",
                    err=True,
                )
                cleanup_msg = (
                    f"cleanup incomplete for PR #{pr_record.pr_number} ({pr_record.branch})"
                )
                errors.append(cleanup_msg)
                fatal_errors.append(cleanup_msg)
        except RuntimeError as e:
            click.echo(f"  [SKIP] PR 建立失敗 ({proposal.title}): {e}", err=True)
            errors.append(str(e))
            fatal_errors.append(str(e))
            skipped += 1
            continue
        try:
            registry.record(cluster, "pr_opened")
        except RuntimeError as e:
            click.echo(f"  [WARN] PR 已建立，但 friction state 寫入失敗：{e}", err=True)
            errors.append(str(e))
            fatal_errors.append(str(e))

    click.echo(f"[6/6] 完成：{len(prs)} PRs opened, {skipped} skipped")

    _finalize_run(config, date_str, hours, events, all_clusters, prs, skipped, errors, fatal_errors)


@cli.command()
@click.option("--hours", default=24, help="回溯時間視窗（小時）")
@click.option("--output", default="-", help="輸出 JSON 路徑（- = stdout）")
def analyze(hours: int, output: str) -> None:
    """只做分析：列出 friction events 和 clusters（不草擬、不開 PR）。"""
    from .classifier import FrictionClassifier, classify_mycelium_lessons
    from .clusterer import FrictionClusterer
    from .config import load_config
    from .extractor import TranscriptExtractor

    config = load_config()
    extractor = TranscriptExtractor(lookback_hours=hours)
    sessions = extractor.extract(extra_paths=config.extra_transcript_paths)
    classifier = FrictionClassifier()
    events = classifier.classify(sessions)
    events += classify_mycelium_lessons(_load_mycelium_lessons(hours, config.lesson_types, []))
    clusterer = FrictionClusterer(
        threshold=config.jaccard_threshold,
        min_cluster_size=config.min_cluster_size,
    )
    clusters = clusterer.cluster(events)

    report = {
        "date": datetime.now().isoformat(),
        "hours": hours,
        "events": len(events),
        "clusters": [
            {
                "id": c.id,
                "friction_type": c.friction_type,
                "count": c.count,
                "keywords": c.common_keywords,
                "sessions": c.source_session_ids,
            }
            for c in clusters
        ],
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if output == "-":
        click.echo(payload)
    else:
        Path(output).write_text(payload, encoding="utf-8")
        click.echo(f"Wrote report to {output}")


@cli.command()
@click.option("--date", default="today", help="日期（YYYY-MM-DD 或 today）")
def digest(date: str) -> None:
    """顯示指定日期的 digest。"""
    from .config import load_config

    config = load_config()
    if date == "today":
        date = datetime.now().strftime("%Y-%m-%d")
    digest_dir = (
        Path(config.digest_dir) if config.digest_dir else RUNTIME_DIR / "nightly_agent" / "digests"
    )
    digest_path = digest_dir / f"digest-{date}.md"
    if not digest_path.exists():
        click.echo(f"Digest not found: {digest_path}", err=True)
        raise SystemExit(1)
    click.echo(digest_path.read_text(encoding="utf-8"))


@cli.command()
def setup() -> None:
    """建立預設設定檔。"""
    from .config import generate_default_config

    path = generate_default_config()
    click.echo(f"✓ 設定檔建立於：{path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _excluded_lesson_ids(conn: sqlite3.Connection, columns: set[str]) -> set[str]:
    """回傳「不該進 nightly digest」的 lesson id：parked（Tier 3）與 retired。

    為什麼要有這個函式：`_load_mycelium_lessons` 繞過 `lessons_service` 直接讀
    `handover.db`，因此拿不到 service 層的預設排除。Evidence Gate 判為 Tier 3 而 park 的
    教訓，正是「無可接受證據形式、不得進 always-loaded 面」的那些；不過濾的話它們當晚就會
    從側門重新進入 nightly 的 rule 生成管線並可能被 cluster 成 rule 提案——park 的目的正是
    防這件事。retired 同理：`show` / `search` / `distill` / tier 升降級都已排除，只有這條
    query 沒有（本 PR 之前就存在的漏洞，一併補）。

    `tags` / `retired_at` 都是 `db.py` 那批 `ALTER TABLE` 補的欄位，舊 `handover.db` 可能
    沒有。**各自獨立判斷**（不合併成單一「新 schema」旗標）：兩者的 migration 不同步時，
    有哪個就用哪個，而不是整組退回不過濾。缺欄位等同「該功能當時還不存在」，不過濾是正確的。
    查詢維持完整靜態字串（不用 f-string 拼欄位），避免 bandit B608 誤判。
    """
    excluded: set[str] = set()
    if "retired_at" in columns:
        excluded.update(
            str(r["id"])
            for r in conn.execute("SELECT id FROM lessons WHERE retired_at IS NOT NULL")
        )
    if "tags" in columns:
        excluded.update(
            str(r["id"])
            for r in conn.execute("SELECT id FROM lessons WHERE tags LIKE '%\"parked\"%'")
        )
    return excluded


def _load_mycelium_lessons(
    hours: int,
    lesson_types: list[str],
    errors: list[str],
    fatal_errors: list[str] | None = None,
) -> list[dict[str, object]]:
    """從 mycelium 的 lessons table 讀取最近 hours 小時的 typed lessons。

    lessons 已與 handover 分家：schema 支援 handover_id（`/handover`，Phase B 尚未串接，
    見 `commands/lessons.md`「Skill integration contract」）與 retrospective_id
    （`/pr-retro`，已在用），或透過 `/lessons add` 獨立寫入（兩者皆空）。
    三者仍共用同一實體檔案 `~/.agents/handover/handover.db`（見
    `tasks/mycelium/config.py` 的 `HANDOVER_DB_PATH`），但 `lessons` 是與 `handovers`/
    `retrospectives` 平行的獨立 table，故 SELECT 需一併帶出 `retrospective_id`。

    `sqlite3.OperationalError`（如缺 `lessons` table，代表尚未 migrate 的舊 schema）與
    `OSError`（磁碟讀取失敗、權限問題、DB 檔案被並發寫入毀損等真正的 I/O 故障）分開處理：
    前者是已知、支援的降級路徑（`test_missing_lessons_table_returns_empty_with_warning`
    明確涵蓋），後者是真正的基礎設施故障，必須算進 `fatal_errors`——否則無論多嚴重的
    儲存層問題都只會產生一則 `[WARN]`，exit code 仍是 0，排程層完全看不到。
    """
    try:
        db_path = Path.home() / ".agents" / "handover" / "handover.db"
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # retrospective_id 是後補的 migration 欄位（見 tasks/mycelium/db.py 的
            # ALTER TABLE），只透過 AgentsDB.init_db() 套用；舊的 handover.db 可能還沒有
            # 這個欄位。這裡刻意保持唯讀（不對 handover.db 執行 ALTER TABLE）：把讀取路徑
            # 變成寫入路徑，在唯讀掛載或被其他 mycelium 指令鎖住時會讓整批 lessons 讀取失敗，
            # 比原本缺欄位的問題更糟。改用 PRAGMA table_info（唯讀）偵測欄位是否存在，
            # 缺欄位時退回 NULL AS retrospective_id。
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(lessons)")}
            # 兩條完整靜態 SQL 字串（而非用 f-string 插入欄位片段），避免動態組字串
            # 觸發 bandit B608 誤判，也讓兩種 schema 各自的查詢一目瞭然。
            #
            if "retrospective_id" in columns:
                select_sql = (
                    "SELECT id, ts, project, type, key, insight, confidence, source, "
                    "handover_id, retrospective_id "
                    "FROM lessons "
                    "WHERE ts >= datetime('now', ? || ' hours') "
                    "ORDER BY ts DESC LIMIT 200"
                )
            else:
                select_sql = (
                    "SELECT id, ts, project, type, key, insight, confidence, source, "
                    "handover_id, NULL AS retrospective_id "
                    "FROM lessons "
                    "WHERE ts >= datetime('now', ? || ' hours') "
                    "ORDER BY ts DESC LIMIT 200"
                )
            # SQLite datetime arithmetic: last N hours
            rows = conn.execute(select_sql, (f"-{hours}",)).fetchall()
            excluded = _excluded_lesson_ids(conn, columns)
        finally:
            conn.close()
        result = []
        for row in rows:
            d = dict(row)
            # 兩端都 `str()`：SQLite 無強型別，任何以 int 寫入 `lessons.id` 的來源會讓
            # `"5" != 5` 而靜默漏過過濾——parked 教訓回到 nightly 管線，正是本過濾要防的事。
            if d.get("type") in lesson_types and str(d.get("id")) not in excluded:
                result.append(d)
        return result
    except sqlite3.OperationalError as e:
        # sqlite3.OperationalError 涵蓋的範圍比「缺 lessons table」廣得多，也包含
        # database is locked、unable to open database file 等真正的資料庫層故障
        # （Codex round-2 mob review 指出：全部歸為良性會讓這類故障也悄悄變成 exit 0）。
        # 只有「缺 lessons table」是已知、支援的 schema-drift 降級路徑，其餘一律視為 fatal
        # （Codex round-3 mob review：比對字串應鎖定 lessons，不是任何 "no such table"——
        # 本函式目前只查 lessons 這一張表，故現況不可達，但收緊比對防止未來加查詢時誤放行）。
        if "no such table: lessons" in str(e).lower():
            click.echo(f"[WARN] mycelium read error: {e}", err=True)
            errors.append(f"mycelium read error: {e}")
        else:
            click.echo(f"[WARN] mycelium read error (database issue): {e}", err=True)
            errors.append(f"mycelium read error (database issue): {e}")
            if fatal_errors is not None:
                fatal_errors.append(f"mycelium read error (database issue): {e}")
        return []
    except OSError as e:
        click.echo(f"[WARN] mycelium read error (I/O failure): {e}", err=True)
        errors.append(f"mycelium read error (I/O failure): {e}")
        if fatal_errors is not None:
            fatal_errors.append(f"mycelium read error (I/O failure): {e}")
        return []


def _write_digest(  # type: ignore[no-untyped-def]
    writer, date_str, hours, events, all_clusters, prs, skipped, errors, min_cluster_size=2
) -> Path:
    digest = writer.build(
        date_str, hours, len(events), all_clusters, prs, skipped, errors, min_cluster_size
    )
    result: Path = writer.write(digest)
    return result


def _finalize_run(  # type: ignore[no-untyped-def]
    config, date_str, hours, events, all_clusters, prs, skipped, errors, fatal_errors
) -> None:
    """寫 digest、視情況發出失敗訊號，並在真正的執行失敗時以非零 exit code 結束。

    `errors`（給 digest 看的完整記錄，含良性降級）與 `fatal_errors`（真正的執行失敗）
    分開判斷：`run()` 的三個結束點（無 eligible cluster／dry-run／正常跑完）共用同一套
    收尾邏輯，避免各自維護一份、漂移出不一致的行為。
    """
    from .digest import DigestWriter

    digest_path = _write_digest(
        DigestWriter(config.digest_dir),
        date_str,
        hours,
        events,
        all_clusters,
        prs,
        skipped,
        errors,
        config.min_cluster_size,
    )
    click.echo(f"      Digest: {digest_path}")
    if errors:
        # fatal_errors 非空時措辭維持「執行失敗」；只有良性降級時改用較輕的措辭，避免
        # 讀 LAST_FAILURE marker 的人誤以為排程真的壞了（machine signal 的 exit code
        # 已經正確區分兩者，這裡只是讓 human-facing 的文字跟著一致）。
        if fatal_errors:
            emit_failure_signal(RuntimeError("；".join(errors)), config.digest_dir)
        else:
            emit_failure_signal(
                RuntimeError(f"（僅良性降級，非致命）{'；'.join(errors)}"), config.digest_dir
            )
    if fatal_errors:
        raise SystemExit(1)


def emit_failure_signal(error: BaseException, digest_dir: str | Path | None = None) -> Path:
    """排程非預期失敗時寫入可見 marker 與當日 digest。"""
    target_dir = Path(digest_dir) if digest_dir else RUNTIME_DIR / "nightly_agent" / "digests"
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[FAIL] {timestamp} nightly-agent 執行失敗：{error}\n"
    marker = target_dir.parent / "LAST_FAILURE"
    digest_path = target_dir / f"digest-{datetime.now().strftime('%Y-%m-%d')}.md"
    try:
        marker.write_text(line, encoding="utf-8")
        with digest_path.open("a", encoding="utf-8") as stream:
            stream.write(line)
    except OSError as e:
        click.echo(f"[WARN] 無法寫入 nightly-agent 失敗訊號：{target_dir}：{e}", err=True)
        raise error from e
    click.echo(line.rstrip(), err=True)
    return marker

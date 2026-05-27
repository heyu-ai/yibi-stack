"""CLI 入口：夜間自我改善 Agent。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click

from tasks._paths import PROJECT_ROOT, RUNTIME_DIR


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
    from .digest import DigestWriter
    from .drafter import ArtifactDrafter
    from .extractor import TranscriptExtractor
    from .pr_creator import PRCreator
    from .tester import TestValidator

    config = load_config(Path(config_path) if config_path else None)
    config.lookback_hours = hours

    date_str = datetime.now().strftime("%Y-%m-%d")
    errors: list[str] = []
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
    lessons = _load_mycelium_lessons(hours, config.lesson_types, errors)
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
        _write_digest(
            DigestWriter(config.digest_dir),
            date_str,
            hours,
            events,
            all_clusters,
            prs,
            skipped,
            errors,
        )
        return

    if dry_run:
        click.echo("[DRY RUN] Eligible clusters:")
        for c in eligible:
            click.echo(f"  {c.friction_type} ×{c.count}: {', '.join(c.common_keywords[:5])}")
        _write_digest(
            DigestWriter(config.digest_dir),
            date_str,
            hours,
            events,
            all_clusters,
            prs,
            skipped,
            errors,
        )
        return

    # --- Step 5: Draft & validate ---
    click.echo("[5/6] 草擬 artifacts 並驗證 failing→passing test …")
    drafter = ArtifactDrafter(config)
    tester = TestValidator(config.generated_tests_dir)

    for cluster in eligible:
        try:
            proposal = drafter.draft(cluster)
        except RuntimeError as e:
            click.echo(f"  [SKIP] 草擬失敗 ({cluster.friction_type}): {e}", err=True)
            errors.append(str(e))
            skipped += 1
            continue

        result = tester.validate(proposal)
        if not result.passed:
            click.echo(f"  [SKIP] test 未通過 ({proposal.title}): {result.error}", err=True)
            if not result.previously_failed:
                click.echo("  [INFO] test 在 artifact 前就通過，代表 friction 已被處理", err=True)
            errors.append(f"test failed: {proposal.title}")
            skipped += 1
            continue

        # --- Step 6: Create PR ---
        try:
            pr_creator = PRCreator(config)
            pr_record = pr_creator.create_pr(proposal, result)
            prs.append(pr_record)
            click.echo(f"  [OK] PR #{pr_record.pr_number}: {pr_record.pr_url}")
        except RuntimeError as e:
            click.echo(f"  [SKIP] PR 建立失敗 ({proposal.title}): {e}", err=True)
            errors.append(str(e))
            skipped += 1

    click.echo(f"[6/6] 完成：{len(prs)} PRs opened, {skipped} skipped")

    digest_path = _write_digest(
        DigestWriter(config.digest_dir), date_str, hours, events, all_clusters, prs, skipped, errors
    )
    click.echo(f"      Digest: {digest_path}")


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
    sessions = extractor.extract()
    classifier = FrictionClassifier()
    events = classifier.classify(sessions)
    events += classify_mycelium_lessons(_load_mycelium_lessons(hours, config.lesson_types, []))
    clusterer = FrictionClusterer()
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
        Path(config.digest_dir) if config.digest_dir else RUNTIME_DIR / "nightly-agent" / "digests"
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


def _load_mycelium_lessons(
    hours: int, lesson_types: list[str], errors: list[str]
) -> list[dict[str, object]]:
    """從 mycelium handover.db 讀取最近 hours 小時的 lessons。"""
    try:
        import sqlite3  # noqa: PLC0415

        db_path = Path.home() / ".agents" / "handover" / "handover.db"
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # SQLite datetime arithmetic: last N hours
            rows = conn.execute(  # nosec B608
                "SELECT id, ts, project, type, key, insight, confidence, source, handover_id "
                "FROM lessons "
                "WHERE ts >= datetime('now', ? || ' hours') "
                "ORDER BY ts DESC LIMIT 200",
                (f"-{hours}",),
            ).fetchall()
        finally:
            conn.close()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("type") in lesson_types:
                result.append(d)
        return result
    except Exception as e:
        errors.append(f"mycelium read error: {e}")
        return []


def _write_digest(writer, date_str, hours, events, all_clusters, prs, skipped, errors) -> Path:  # type: ignore[no-untyped-def]
    digest = writer.build(date_str, hours, len(events), all_clusters, prs, skipped, errors)
    result: Path = writer.write(digest)
    return result

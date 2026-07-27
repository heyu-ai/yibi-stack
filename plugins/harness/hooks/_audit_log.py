"""bash-hygiene hook 共用 audit logger（Python hooks 使用）。

Fail-safe 合約：任何 exception 靜默吞掉，絕不影響 hook 判斷。
呼叫方式：
    from _audit_log import log_event
    log_event("ap2", command, exit_code=0, duration_ms=elapsed_ms, rule_id="13")

── 只記 block，不記 allow（PR #262）──
每次 hook 放行都寫一筆 330 bytes，只為了記錄「什麼都沒發生」。實測 2026-07-17：
94.3 MB / 299,280 筆 / 39 天，其中 **94.84% 是 allow**——只留 block 檔案剩 4.74%。
成長率從 2.4 MB/天 降到約 0.11 MB/天。
allow 唯一的用途是 `stats` 的 allow/block 比例，經使用者確認不需要。

── 每日輪替、保留 N 天（PR #262）──
輪替**不綁定消費端**：檔名帶日期，寫入時順手清掉過期的檔案。
這是刻意的設計——這個 log 的消費端是 nightly-agent，而它實測可以連續 4 晚
（實際可能更久）啟動即死而無人察覺（PR #261）。把資料生命週期綁在一個會壞掉的元件上，
結果就是 log 無限長：39 天沒有任何東西消費過它。時間到就刪，不問任何人。
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess  # nosec B404
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

CONFIG_PATH = Path.home() / ".agents" / "bash-hygiene.json"
PREVIEW_CHARS = 200
HOOK_VERSION = "2"

# 保留天數。30 天讓 nightly-agent（daily，做 friction clustering）有足夠樣本看趨勢，
# 同時上限固定：30 天 x 約 0.11 MB/天（只記 block）約 3.3 MB。
RETENTION_DAYS = 30
LOG_STEM = "bash-hygiene-audit"
LOG_GLOB = f"{LOG_STEM}-*.jsonl"


def _enabled() -> bool:
    try:
        if not CONFIG_PATH.is_file():
            return False
        return bool(json.loads(CONFIG_PATH.read_text("utf-8")).get("audit_enabled"))
    except Exception:
        return False


def _log_dir() -> Path | None:
    try:
        r = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode != 0:
            return None
        # --git-common-dir returns the .git dir; parent is repo root (works in worktrees too)
        d = Path(r.stdout.strip()).parent / ".runtime" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return None


def _log_path(today: date | None = None) -> Path | None:
    """今日的 log 檔：`bash-hygiene-audit-YYYY-MM-DD.jsonl`。"""
    d = _log_dir()
    if d is None:
        return None
    day = today or datetime.now(UTC).date()
    return d / f"{LOG_STEM}-{day.isoformat()}.jsonl"


def _prune_old_logs(today: date | None = None) -> None:
    """刪掉超過 RETENTION_DAYS 的每日 log。

    日期從**檔名**解析，不看 mtime：mtime 會被 `cp -p`、rsync、備份還原等動作改掉，
    而檔名是這個檔案自己宣告的歸屬日，比較誠實（本 repo 的 shutil.copy2 保留 mtime
    導致建置工具誤判的坑，就是同一類問題）。

    解析不出日期的檔案一律不動——寧可留下也不誤刪。
    """
    d = _log_dir()
    if d is None:
        return
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=RETENTION_DAYS)
    for f in d.glob(LOG_GLOB):
        stamp = f.stem[len(LOG_STEM) + 1 :]  # `bash-hygiene-audit-` 之後的部分
        try:
            file_day = date.fromisoformat(stamp)
        except ValueError:
            continue  # 檔名不符預期 -> 不是我們產的，別碰
        if file_day < cutoff:
            with contextlib.suppress(OSError):  # 清不掉就算了，絕不影響 hook 判斷
                f.unlink()


def log_event(
    hook: str,
    command: str,
    exit_code: int,
    block_reason: str | None = None,
    duration_ms: int | None = None,
    rule_id: str = "",
) -> None:
    if not _enabled():
        return
    # 只記非 allow。exit_code 0 = 放行 = 「什麼都沒發生」，佔實測資料的 94.84%（見檔頭）。
    # error（非 0 非 2）仍要記：那是 hook 自己出問題，正是最需要留痕的。
    if exit_code == 0:
        return
    try:
        path = _log_path()
        if path is None:
            return
        _prune_old_logs()
        record = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hook": hook,
            "hook_version": HOOK_VERSION,
            "exit_code": exit_code,
            "verdict": "block" if exit_code == 2 else ("allow" if exit_code == 0 else "error"),
            "block_reason": block_reason,
            "rule_id": rule_id,
            "cmd_snippet": command[:PREVIEW_CHARS],
            "command_hash": hashlib.sha256(command.encode("utf-8")).hexdigest()[:16],
            "session_id": os.environ.get("CLAUDE_SESSION_ID"),
            "duration_ms": duration_ms,
        }
        with path.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # nosec B110
        pass


# CLI entry 供非 bash hook 使用；bash hook 應改用 _audit_log.sh
def _main_cli() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="bash-hygiene audit logger CLI")
    parser.add_argument("--hook", required=True)
    parser.add_argument("--verdict", required=True, choices=["allow", "block"])
    parser.add_argument("--command", required=True)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--duration-ms", type=int, default=None, dest="duration_ms")
    parser.add_argument("--rule-id", default="", dest="rule_id")
    args = parser.parse_args()
    exit_code = 2 if args.verdict == "block" else 0
    log_event(args.hook, args.command, exit_code, args.reason, args.duration_ms, args.rule_id)


if __name__ == "__main__":
    _main_cli()

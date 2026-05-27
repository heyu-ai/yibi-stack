"""Recap Collector — Claude Code Stop hook 入口 + install / uninstall 設定。

Stop hook entry point (`run_hook`)：
  - 讀 stdin 的 hook payload（JSON）
  - 從 transcript 擷取 type=system, subtype=away_summary 條目
  - 以 entry.uuid 去重後 append 到 ~/.agents/recap/session-recap.jsonl

任何錯誤都靜默退出，絕不阻斷 Claude 的 Stop 流程。
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import RecapRecord

# settings.json 中用於比對冪等的特徵字串
_HOOK_COMMAND_MARKER = "tasks.mycelium recap collect"


def run_hook(
    stdin_text: str | None = None,
    output_path: Path | None = None,
) -> int:
    """Stop hook entry point。回傳 0（永遠不阻斷）。

    參數用於測試注入；正式執行時 stdin_text=None 會從 sys.stdin 讀取。
    """
    # 模組 import 延遲到函式內，確保 import 失敗不會阻斷 Stop event
    try:
        from .account import detect_account, detect_device
        from .config import RECAP_JSONL_PATH, to_portable_path
    except Exception as e:
        print(f"[agents-recap] 模組載入失敗，跳過：{e}", file=sys.stderr)
        return 0

    try:
        raw = stdin_text if stdin_text is not None else sys.stdin.read()
    except OSError as e:
        print(f"[agents-recap] 無法讀取 stdin：{e}", file=sys.stderr)
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[agents-recap] hook payload JSON 解析失敗：{e}", file=sys.stderr)
        return 0

    if payload.get("hook_event_name") != "Stop":
        return 0

    reason = payload.get("reason", "")
    transcript_path = payload.get("transcript_path", "")

    if not transcript_path or not Path(transcript_path).is_file():
        return 0

    try:
        away_summaries = _extract_away_summaries(transcript_path)
    except Exception as e:
        print(f"[agents-recap] transcript 解析失敗：{e}", file=sys.stderr)
        return 0

    if not away_summaries:
        return 0

    out_path = output_path or RECAP_JSONL_PATH

    # 先建立所有 record（可能因 validator 失敗拋出），再寫入
    try:
        account = detect_account(warn=False)
        device = detect_device()
        seen_uuids = _load_seen_uuids(out_path)
        new_records = [
            _build_record(s, reason, account, device, to_portable_path)
            for s in away_summaries
            if s.get("uuid") not in seen_uuids
        ]
    except Exception as e:
        print(f"[agents-recap] 建立記錄失敗：{e}", file=sys.stderr)
        return 0

    if not new_records:
        return 0

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as fp:
            for r in new_records:
                fp.write(r.model_dump_json() + "\n")
    except Exception as e:
        print(f"[agents-recap] 無法寫入 session-recap.jsonl：{e}", file=sys.stderr)

    return 0


def _extract_away_summaries(transcript_path: str) -> list[dict[str, Any]]:
    """逐行讀 transcript JSONL，回傳所有 away_summary 條目。"""
    results: list[dict[str, Any]] = []
    decode_failures = 0
    with open(transcript_path, encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                decode_failures += 1
                continue
            if entry.get("type") == "system" and entry.get("subtype") == "away_summary":
                results.append(entry)
    if decode_failures:
        print(
            f"[agents-recap] transcript 中有 {decode_failures} 行 JSON 解析失敗",
            file=sys.stderr,
        )
    return results


def _load_seen_uuids(path: Path) -> set[str]:
    """讀現有 JSONL，回傳所有已存在的 id set（用 entry uuid 作為冪等 key）。"""
    if not path.exists():
        return set()
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec_id := rec.get("id"):
                    seen.add(rec_id)
            except json.JSONDecodeError:
                continue
    return seen


def _build_record(
    entry: dict[str, Any],
    reason: str,
    account: str,
    device: str | None,
    to_portable_path: Callable[[str], str],
) -> RecapRecord:
    """把 transcript away_summary 條目轉為 RecapRecord。"""
    cwd = entry.get("cwd", "")
    return RecapRecord(
        id=entry.get("uuid", ""),
        timestamp=entry.get("timestamp", ""),
        session_id=entry.get("sessionId", ""),
        project=os.path.basename(cwd),
        working_dir=to_portable_path(cwd),
        branch=entry.get("gitBranch", ""),
        agent_type="claude",
        account=account,
        device=device,
        recap_text=entry.get("content", ""),
        cc_version=entry.get("version", ""),
        session_reason=reason,
    )


# ─────────────────────────────────────────────────────────────────────────
# Install / uninstall Stop hook
# ─────────────────────────────────────────────────────────────────────────


def install_hook(
    settings_path: Path | None = None,
    hook_command: str | None = None,
) -> tuple[bool, str]:
    """把 Stop hook 註冊到 ~/.claude/settings.json。

    回傳 (is_new, message)。is_new=True 表示新增；False 表示已存在跳過。
    """
    from ._hook_utils import install_stop_hook

    return install_stop_hook(
        marker=_HOOK_COMMAND_MARKER,
        hook_label="recap",
        settings_path=settings_path,
        hook_command=hook_command or _default_hook_command(),
    )


def uninstall_hook(settings_path: Path | None = None) -> tuple[bool, str]:
    """移除 Stop hook；回傳 (removed, message)。"""
    from ._hook_utils import uninstall_stop_hook

    return uninstall_stop_hook(
        marker=_HOOK_COMMAND_MARKER,
        hook_label="agents recap",
        settings_path=settings_path,
    )


def _default_hook_command() -> str:
    """回傳預設 hook command（tasks.mycelium recap collect）。"""
    repo_root = Path(__file__).resolve().parents[2]
    return f"uv run --project {repo_root} python -m tasks.mycelium recap collect"


# ─────────────────────────────────────────────────────────────────────────
# SessionStart hook — 自動注入 hot lesson
# ─────────────────────────────────────────────────────────────────────────


def run_session_start_hook(
    stdin_text: str | None = None,
) -> int:
    """SessionStart hook entry point。

    讀取 DB 中 tier="hot" 的 lessons（top 3，依 effective_confidence 降序），
    格式化為「★ Recalled lessons:」區塊輸出到 stdout，供 Claude Code 注入 session context。

    任何錯誤都靜默退出（回傳 0），絕不阻斷 SessionStart 流程。
    """
    try:
        raw = stdin_text if stdin_text is not None else sys.stdin.read()
    except OSError:
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    if payload.get("hook_event_name") != "SessionStart":
        return 0

    try:
        from .lessons_service import get_lessons

        rows = get_lessons(tier_filter=["hot"], limit=3)
    except Exception as e:
        print(f"[mycelium-session] get_lessons 失敗：{e}", file=sys.stderr)
        return 0

    if not rows:
        return 0

    lines = ["★ Recalled lessons:"]
    for r in rows:
        insight = r.get("insight", "").strip()
        if insight:
            lines.append(f"- {insight}")

    if len(lines) > 1:
        print("\n".join(lines))

    # Dream digest display（Phase 5 功能；依賴 dream skill 落地後啟動）
    _try_display_dream_digest()

    return 0


def _try_display_dream_digest(
    dreams_dir: str | None = None,
    max_age_seconds: float = 86400,
) -> None:
    """若 ~/.agents/dreams/latest.md 存在且距今 < 24 小時，輸出 dream digest。"""
    import os
    import time

    dreams_latest = Path(dreams_dir or (Path.home() / ".agents" / "dreams")) / "latest.md"
    if not dreams_latest.is_file():
        return

    try:
        mtime = dreams_latest.stat().st_mtime
        age = time.time() - mtime
        if age >= max_age_seconds:
            return

        content = dreams_latest.read_text(encoding="utf-8")[:200]
        print(f"★ Dream digest:\n{content}")
    except OSError:
        pass

"""PR Orchestrator 設定載入與儲存。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import click
from pydantic import BaseModel

from .._paths import RUNTIME_DIR

if TYPE_CHECKING:
    from .models import OrchestratorState

_STATE_DIR = RUNTIME_DIR / "pr_orchestrator"
_ARCHIVE_BASE = Path.home() / ".claude" / "pr_orchestrator"
_CONFIG_PATH = _STATE_DIR / "config.json"


class OrchestratorConfig(BaseModel):
    version: str = "1.0"
    max_fix_iterations: int = 3
    allow_fork_fix: bool = False
    base_branch: str = "main"
    auto_merge: bool = False


def state_path(pr_number: int) -> Path:
    return _STATE_DIR / f"{pr_number}.json"


def archive_path(repo: str, pr_number: int) -> Path:
    safe_repo = repo.replace("/", "-").replace("\\", "-")
    return _ARCHIVE_BASE / safe_repo / f"{pr_number}.json"


def load_config(path: Path | None = None) -> OrchestratorConfig:
    config_path = path or _CONFIG_PATH
    if not config_path.is_file():
        return OrchestratorConfig()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise RuntimeError(f"設定檔讀取失敗：{config_path}") from e
    return OrchestratorConfig.model_validate(data)


def save_config(cfg: OrchestratorConfig, path: Path | None = None) -> None:
    config_path = path or _CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(cfg.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_state_file(pr_number: int) -> dict:  # type: ignore[type-arg]
    from .models import OrchestratorState

    p = state_path(pr_number)
    if not p.is_file():
        raise RuntimeError(f"找不到 PR #{pr_number} 的 state 檔：{p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as e:
        raise RuntimeError(f"State 檔讀取失敗：{p}") from e
    return OrchestratorState.model_validate(data).model_dump()


def persist_state(state: OrchestratorState) -> None:
    """原子寫入 state file（tmp + os.replace）。"""
    import os

    from .models import OrchestratorState as _S

    if not isinstance(state, _S):
        raise TypeError(f"expect OrchestratorState, got {type(state)}")

    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = state_path(state.pr_number)
    tmp = p.with_suffix(".json.tmp")
    try:
        tmp.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        raise RuntimeError(f"State 檔寫入失敗：{p}") from e
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def archive_state(state: OrchestratorState) -> None:
    """CLEANED 後把 state file 搬到 ~/.claude/pr_orchestrator/<repo>/ 作為歸檔。"""

    dest = archive_path(state.repo or "unknown", state.pr_number)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = state_path(state.pr_number)
    if src.is_file():
        import sys
        try:
            import shutil as _sh
            _sh.copy2(str(src), str(dest))
            src.unlink()
            click.echo(f"State 已歸檔：{dest}")
        except OSError as e:
            print(f"[WARN] State 歸檔失敗：{e}", file=sys.stderr)


def find_latest_state() -> int | None:
    """找到最新（last_transition_at 最大）的 active state file，回傳 PR 號碼。"""
    import json as _json

    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    candidates = list(_STATE_DIR.glob("*.json"))
    if not candidates:
        return None

    best_pr: int | None = None
    best_ts = ""
    for p in candidates:
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue
        ts = data.get("last_transition_at", "")
        if ts > best_ts:
            best_ts = ts
            best_pr = data.get("pr_number")
    return best_pr

"""Job 執行層：command（subprocess）、claude / skill（ACP Gateway HTTP）。"""

from __future__ import annotations

import json
import logging
import re
import subprocess  # nosec B404 — job 執行需要 subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import IO

from .._paths import PROJECT_ROOT
from .models import JobConfig, JobRun, JobRunStatus

logger = logging.getLogger(__name__)

_ACP_GATEWAY_ENV_PATH = Path.home() / ".config" / "acp-gateway" / ".env"
_DEFAULT_ACP_GATEWAY_URL = "http://localhost:7865/v1/prompt"


def _load_acp_config() -> tuple[str, str]:
    """從 ~/.config/acp-gateway/.env 讀取 token 和 port。

    回傳 (token, url)。
    """
    token = ""  # nosec B105 — 預設空字串，從檔案讀取覆寫
    port = "7865"

    if _ACP_GATEWAY_ENV_PATH.exists():
        for line in _ACP_GATEWAY_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ACP_GATEWAY_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("ACP_GATEWAY_PORT="):
                port = line.split("=", 1)[1].strip().strip('"').strip("'")
    else:
        logger.warning(
            "ACP Gateway 設定檔不存在：%s — claude/skill 類型 job 將無法認證",
            _ACP_GATEWAY_ENV_PATH,
        )

    if not token:
        logger.warning("ACP Gateway token 為空，claude/skill 類型 job 可能認證失敗")

    url = f"http://localhost:{port}/v1/prompt"
    return token, url


def _render_prompt(template: str, date: str) -> str:
    """替換 prompt template 中的 {{date}} placeholder。"""
    return re.sub(r"\{\{date\}\}", date, template)


def run_command_job(
    job: JobConfig,
    log_file: IO[str],
) -> tuple[int, str | None]:
    """執行 command 類型 job，回傳 (exit_code, error_message)。"""
    assert job.command is not None
    try:
        result = subprocess.run(  # nosec B603
            job.command,
            cwd=PROJECT_ROOT,
            stdout=log_file,
            stderr=log_file,
            timeout=job.timeout_seconds,
            text=True,
        )
        return result.returncode, None
    except subprocess.TimeoutExpired:
        return 1, f"timeout after {job.timeout_seconds}s"
    except OSError as e:
        return 1, f"指令執行失敗（{job.command[0]}）：{e}"


def run_claude_job(
    job: JobConfig,
    log_file: IO[str],
    now: datetime,
) -> tuple[int, str | None]:
    """透過 MiniShell ACP Gateway 執行 claude/skill 類型 job。

    回傳 (exit_code, error_message)。
    若 ACP Gateway 未啟動，記錄錯誤並回傳 exit_code=1。
    """
    token, url = _load_acp_config()
    date_str = now.strftime("%Y-%m-%d")
    timeout_ms = job.timeout_seconds * 1000

    # 組建 prompt
    if job.claude is not None:
        prompt_path = PROJECT_ROOT / job.claude.prompt_file
        if not prompt_path.exists():
            return 1, f"prompt_file 不存在：{prompt_path}"
        template = prompt_path.read_text(encoding="utf-8")
        prompt = _render_prompt(template, date_str)
        if job.claude.timeout_ms is not None:
            timeout_ms = job.claude.timeout_ms
    elif job.skill is not None:
        skill_path = PROJECT_ROOT / "skills" / job.skill / "SKILL.md"
        if not skill_path.exists():
            return 1, f"SKILL.md 不存在：{skill_path}"
        skill_content = skill_path.read_text(encoding="utf-8")
        prompt = f"請依照以下 SKILL.md 的步驟執行（今日日期：{date_str}）：\n\n{skill_content}"
    else:
        return 1, "job 未設定 claude 或 skill"

    # 呼叫 ACP Gateway
    payload = json.dumps(
        {"prompt": prompt, "timeout_ms": timeout_ms, "caller": f"ainization-scheduler/{job.id}"}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=job.timeout_seconds + 30) as resp:  # nosec B310
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        msg = (
            f"ACP Gateway 連線失敗（{url}）：{e.reason}\n"
            "請確認 MiniShell ACP Gateway 已啟動：bash scripts/start-acp-gateway.sh"
        )
        log_file.write(msg + "\n")
        return 1, msg
    except json.JSONDecodeError as e:
        msg = f"ACP Gateway 回傳非 JSON 格式：{e}"
        log_file.write(msg + "\n")
        return 1, msg
    except Exception as e:
        msg = f"ACP Gateway 呼叫發生例外：{type(e).__name__}: {e}"
        log_file.write(msg + "\n")
        return 1, msg

    output = body.get("output", "")
    success = body.get("success", False)
    duration_ms = body.get("duration_ms", 0)

    log_file.write(f"=== ACP Gateway 回應（{duration_ms}ms）===\n")
    log_file.write(output + "\n")

    if body.get("timed_out"):
        return 1, f"ACP Gateway timeout（{timeout_ms}ms）"
    if not success:
        return 1, f"Claude 執行失敗：{output[:200]}"
    return 0, None


def run_job(job: JobConfig, log_dir: Path, now: datetime | None = None) -> JobRun:
    """統一 job 執行入口，根據 job 類型分派。

    回傳 JobRun（不含 DB id，由呼叫方記錄）。
    """
    if now is None:
        now = datetime.now()
    started_at = now.isoformat()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job.id}_{now.strftime('%Y%m%d_%H%M%S')}.log"

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"=== {job.id} started at {started_at} ===\n")

        if job.command is not None:
            exit_code, error = run_command_job(job, log_file)
        else:
            exit_code, error = run_claude_job(job, log_file, now)

        finished_at = datetime.now().isoformat()
        status = JobRunStatus.success if exit_code == 0 else JobRunStatus.failed
        log_file.write(
            f"\n=== finished at {finished_at} | status={status} exit_code={exit_code} ===\n"
        )

    return JobRun(
        job_id=job.id,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        exit_code=exit_code,
        log_path=str(log_path),
        error_message=error,
    )

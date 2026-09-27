#!/usr/bin/env python3
"""detect_voices.py：pr-cycle-deep／mob-code-review-only Step 0 的外部 reviewer 偵測。

為什麼是 script：這段偵測原本是 SKILL.md 裡的 5 段 inline bash（多行 if/elif + 內嵌
`python -c`），agent 每次都照意圖重寫一份再跑——跑的版本不保證等於文件寫的版本、沒有測試守著，
而且多行指令無法用 prefix allow-list 覆蓋，每次 mob review 都要手動按確認。收進一支 script 後，
allow-list 只需一條絕對路徑 entry。

輸出（stdout，一行一項；前綴是 SKILL.md Mode determination 表與 mob-detection-cache 的介面，
不要改字串）：
  CODEX: BINARY_OK | NOT_FOUND
  CODEX_AUTH: KEY_SET | KEY_WHITESPACE_PREFIX | FILE_EXISTS | NOT_AUTHED
  GEMINI: BINARY_OK | NOT_FOUND            （agy；保留 GEMINI 前綴以相容 cache 的 GEMINI_OK）
  GEMINI_AUTH: ONBOARDED | KEY_SET | KEY_WHITESPACE_PREFIX | NOT_AUTHED
  GEMINI_ALLOW_LIST: OK | MISSING

用法：
  python3 detect_voices.py              # Step 0b：完整偵測（5 行）
  python3 detect_voices.py --auth-only  # Step 0a warm path：只重驗 auth（2 行）

退出碼：0 偵測完成（不論結果——NOT_FOUND／NOT_AUTHED 是偵測結果，不是 script 失敗）；
2 參數錯誤。

安全：只輸出狀態字串，絕不印出任何 key 的值。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

CODEX_KEYS = ("CODEX_API_KEY", "OPENAI_API_KEY")
GEMINI_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
AGY_SCRIPTS = ("agy-r1-stage1.sh", "agy-r1-stage2.sh", "agy-r2.sh")


def _key_state(env: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    """回傳 key 狀態：任一 key 以非空白字元開頭 → KEY_SET；否則任一以空白開頭 →
    KEY_WHITESPACE_PREFIX；都沒有 → None。

    空字串視為未設定（對應原 bash 的 `=[^[:space:]]` / `=[[:space:]]` 兩者都不匹配空值）。
    """
    values = [env.get(k) or "" for k in keys]
    if any(v and not v[0].isspace() for v in values):
        return "KEY_SET"
    if any(v and v[0].isspace() for v in values):
        return "KEY_WHITESPACE_PREFIX"
    return None


def _read_json(path: Path, label: str) -> object | None:
    """讀 JSON；檔案不存在回 None（正常情況，不警告），讀取或解析失敗回 None 並在 stderr 警告。"""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[WARN] 無法讀取 {label}（{path}）：{e}", file=sys.stderr)
        return None


def codex_auth(env: Mapping[str, str], home: Path) -> str:
    state = _key_state(env, CODEX_KEYS)
    if state is not None:
        return state
    auth_file = home / ".codex" / "auth.json"
    if auth_file.is_file() and auth_file.stat().st_size > 0:
        return "FILE_EXISTS"
    return "NOT_AUTHED"


def gemini_auth(env: Mapping[str, str], home: Path) -> str:
    # onboardingComplete 才是 OAuth 完成的可靠指標；installation_id 在 OAuth 完成前就存在
    onboarding = _read_json(
        home / ".gemini" / "antigravity-cli" / "cache" / "onboarding.json", "agy onboarding.json"
    )
    if isinstance(onboarding, dict) and onboarding.get("onboardingComplete"):
        return "ONBOARDED"
    return _key_state(env, GEMINI_KEYS) or "NOT_AUTHED"


def agy_allow_list(home: Path) -> str:
    """三支 agy script 的 `Bash(bash <abs path>)` entry 是否都在 ~/.claude/settings.json。"""
    settings = _read_json(home / ".claude" / "settings.json", "~/.claude/settings.json")
    permissions = settings.get("permissions") if isinstance(settings, dict) else None
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    if not isinstance(allow, list):
        return "MISSING"
    scripts_dir = home / ".agents" / "skills" / "pr-cycle-deep" / "scripts"
    needed = {f"Bash(bash {scripts_dir / name})" for name in AGY_SCRIPTS}
    return "OK" if needed.issubset(allow) else "MISSING"


def _binary(name: str, env: Mapping[str, str]) -> str:
    return "BINARY_OK" if shutil.which(name, path=env.get("PATH")) else "NOT_FOUND"


def detect(env: Mapping[str, str], home: Path, *, auth_only: bool) -> list[str]:
    if auth_only:
        return [
            f"CODEX_AUTH: {codex_auth(env, home)}",
            f"GEMINI_AUTH: {gemini_auth(env, home)}",
        ]
    return [
        f"CODEX: {_binary('codex', env)}",
        f"CODEX_AUTH: {codex_auth(env, home)}",
        f"GEMINI: {_binary('agy', env)}",
        f"GEMINI_AUTH: {gemini_auth(env, home)}",
        f"GEMINI_ALLOW_LIST: {agy_allow_list(home)}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="偵測 mob review 可用的外部 reviewer（codex / agy）"
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="只重驗 auth（Step 0a cache warm path 用），不檢查 binary 與 allow-list",
    )
    args = parser.parse_args(argv)
    for line in detect(os.environ, Path.home(), auth_only=args.auth_only):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

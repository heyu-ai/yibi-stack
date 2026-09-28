#!/usr/bin/env python3
"""detect_voices.py：pr-cycle-deep／mob-code-review-only Step 0 的外部 reviewer 偵測。

為什麼是 script：這段偵測原本是 SKILL.md 裡的 5 段 inline bash（多行 if/elif + 內嵌
`python -c`），agent 每次都照意圖重寫一份再跑——跑的版本不保證等於文件寫的版本、沒有測試守著，
而且多行指令無法用 prefix allow-list 覆蓋，每次 mob review 都要手動按確認。收進一支 script 後，
allow-list 只需兩條精確 entry（預設模式與 `--auth-only` 各一條絕對路徑）。

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

退出碼：0 偵測完成（不論結果——NOT_FOUND／NOT_AUTHED 是偵測結果，不是 script 失敗；
設定檔讀不到、壞掉或形狀不對時在 stderr 印 [WARN] 並視為不存在，仍 exit 0）；2 參數錯誤。
其他非 0（python 找不到 script 本身也是 exit 2，stderr 為 `can't open file`）都代表 script
沒跑成，呼叫端必須以 [FAIL] 停下，不可當成 0 個 voice。

安全：只輸出狀態字串，絕不印出任何 key 的值。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

CODEX_KEYS = ("CODEX_API_KEY", "OPENAI_API_KEY")
GEMINI_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
AGY_SCRIPTS = ("agy-r1-stage1.sh", "agy-r1-stage2.sh", "agy-r2.sh")
# 「讀不到檔案」與「JSON 內容是 null」要分開：前者是正常的沒安裝，後者是形狀錯誤要警告
_ABSENT = object()


def _key_state(env: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    """回傳 key 狀態：任一 key 以非空白字元開頭 → KEY_SET；否則任一以空白開頭 →
    KEY_WHITESPACE_PREFIX；都沒有 → None。

    空字串視為未設定（對應原 bash 的 `=[^[:space:]]` / `=[[:space:]]` 兩者都不匹配空值）。
    「空白」用 `str.isspace()`：原 inline bash 在使用者的 UTF-8 locale 下跑，macOS grep 的
    `[[:space:]]` 也匹配 U+00A0 等 Unicode 空白（`LANG=en_US.UTF-8` 實測），兩者一致。

    與原 `env | grep` 唯一刻意的差異：值以換行開頭時，原本逐行比對的 grep 看到的是 `KEY=` 後面
    沒有字元的一行，兩個 pattern 都不匹配而往下掉；這裡直接看值的首字元，判為
    KEY_WHITESPACE_PREFIX（較合理：使用者確實設了一把壞掉的 key）。
    """
    values = [env.get(k) or "" for k in keys]
    if any(v and not v[0].isspace() for v in values):
        return "KEY_SET"
    if any(v and v[0].isspace() for v in values):
        return "KEY_WHITESPACE_PREFIX"
    return None


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def _read_json(path: Path, label: str) -> object:
    """讀 JSON，回傳解析結果（可能是 None，代表檔案內容是 JSON null）。

    檔案不存在或不是一般檔案回 `_ABSENT`（正常情況，不警告）；讀取或解析失敗也回 `_ABSENT`，
    但在 stderr 警告。存在與否用 `stat()` 判斷而不用 `is_file()`：Python 3.14 的 `is_file()`
    遇到權限錯誤會回 False 而不 raise，會把「讀不到」誤當成「不存在」而靜默。
    ValueError 同時涵蓋 JSONDecodeError 與非 UTF-8 的 UnicodeDecodeError。
    """
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return _ABSENT
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        # 不存在，或 stat() 與 read_text() 之間被刪（TOCTOU）：等同沒安裝，不警告
        return _ABSENT
    except (OSError, ValueError) as e:
        _warn(f"無法讀取 {label}（{path}）：{e}")
        return _ABSENT


def _nonempty_file(path: Path) -> bool:
    """近似 bash `test -s`：存在且大小 > 0；刻意多要求是一般檔案（名為 auth.json 的目錄不算登入）。

    只 stat 一次（避免 is_file() 與 stat() 之間的 TOCTOU）；不存在時靜默回 False，
    其他讀取錯誤（例如上層目錄無權限）印 [WARN] 後同樣回 False。
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        return False
    except OSError as e:
        _warn(f"無法讀取 {path}：{e}（視為不存在）")
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size > 0


def codex_auth(env: Mapping[str, str], home: Path) -> str:
    state = _key_state(env, CODEX_KEYS)
    if state is not None:
        return state
    if _nonempty_file(home / ".codex" / "auth.json"):
        return "FILE_EXISTS"
    return "NOT_AUTHED"


def gemini_auth(env: Mapping[str, str], home: Path) -> str:
    # onboardingComplete 才是 OAuth 完成的可靠指標；installation_id 在 OAuth 完成前就存在
    onboarding = _read_json(
        home / ".gemini" / "antigravity-cli" / "cache" / "onboarding.json", "agy onboarding.json"
    )
    if onboarding is not _ABSENT and not isinstance(onboarding, dict):
        _warn("agy onboarding.json 頂層不是 object，視為未完成 onboarding")
    elif isinstance(onboarding, dict) and onboarding.get("onboardingComplete"):
        return "ONBOARDED"
    return _key_state(env, GEMINI_KEYS) or "NOT_AUTHED"


def agy_allow_list(home: Path) -> str:
    """三支 agy script 的 `Bash(bash <abs path>)` entry 是否都在 ~/.claude/settings.json。

    key 不存在（沒有 permissions／allow）是「沒設 allow-list」→ MISSING，不警告；
    key 存在但型別不對才是形狀錯誤 → MISSING + [WARN]。
    """
    label = "~/.claude/settings.json"
    settings = _read_json(home / ".claude" / "settings.json", label)
    if settings is _ABSENT:
        return "MISSING"
    if not isinstance(settings, dict):
        _warn(f"{label} 頂層不是 object，視為沒有 allow-list")
        return "MISSING"
    if "permissions" not in settings:
        return "MISSING"
    permissions = settings["permissions"]
    if not isinstance(permissions, dict):
        _warn(f"{label} 的 permissions 不是 object，視為沒有 allow-list")
        return "MISSING"
    if "allow" not in permissions:
        return "MISSING"
    allow = permissions["allow"]
    if not isinstance(allow, list):
        _warn(f"{label} 的 permissions.allow 不是 list，視為沒有 allow-list")
        return "MISSING"
    scripts_dir = home / ".agents" / "skills" / "pr-cycle-deep" / "scripts"
    needed = [f"Bash(bash {scripts_dir / name})" for name in AGY_SCRIPTS]
    # 用 list 成員比對而非 set.issubset：allow 可能含 dict 等不可 hash 的元素
    return "OK" if all(e in allow for e in needed) else "MISSING"


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

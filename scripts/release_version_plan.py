#!/usr/bin/env python3
"""決定 `make release` 要升一級版號，還是沿用 PR 已升好的 plugin 版號。

PR 改到 plugin 出貨內容時必須在 PR 內 lockstep 升版（`scripts/check_plugin_version_bump.py`），
但 `scripts/sync-plugin-versions.sh` 只改 plugin 的版號檔，不改 `pyproject.toml`。
`bump.sh` 又以 `pyproject.toml` 為基準升一級，所以兩個 PR 各自升版後（plugin 1.24.5、
pyproject 1.24.3），舊流程會算出 1.24.4，再把所有 plugin 從 1.24.5 降回 1.24.4。
只拿過第一個 PR 內容的使用者手上已是 1.24.4，不會再更新，第二個 PR 的內容就到不了。

規則（比較 `pyproject.toml` 與 plugin 的 lockstep 版號）：
- plugin 版號 > pyproject：MODE=adopt，發版版號沿用 plugin 版號，不再升一級；
- plugin 版號 == pyproject：MODE=bump，照舊由 `bump.sh` 依 TYPE 升一級；
- plugin 版號 < pyproject，或 plugin 之間版號不一致：失敗，需要人工處理。

`--apply` 只在 MODE=adopt 時把 `pyproject.toml` 的 version 改成 plugin 版號；
MODE=bump 時不改任何檔案。

輸出（stdout）：`MODE=bump|adopt` 與 `VERSION=<X.Y.Z>`（MODE=bump 時為目前版號）。
Exit code：0 = 成功；1 = 版號狀態不允許發版；2 = 讀不到或解析不了版號檔。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_PYPROJECT_VERSION = re.compile(r'^version = "([^"]*)"$', re.M)


class PlanError(RuntimeError):
    """版號狀態不允許發版；對應 exit 1。"""


class DataError(RuntimeError):
    """讀不到或解析不了版號檔；對應 exit 2。"""


def _parse(value: object, where: str) -> tuple[int, int, int]:
    match = _SEMVER.match(value) if isinstance(value, str) else None
    if match is None:
        raise DataError(f"{where} 的 version 不是 X.Y.Z：{value!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _fmt(v: tuple[int, int, int]) -> str:
    return ".".join(str(x) for x in v)


def pyproject_version(root: Path) -> tuple[int, int, int]:
    path = root / "pyproject.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise DataError(f"讀不到 {path}：{e}") from e
    matches = _PYPROJECT_VERSION.findall(text)
    if len(matches) != 1:
        raise DataError(f'{path} 應恰好有 1 行 version = "X.Y.Z"，實際 {len(matches)} 行')
    return _parse(matches[0], str(path))


def plugin_versions(root: Path) -> dict[str, tuple[int, int, int]]:
    files = sorted(
        list(root.glob("plugins/*/.claude-plugin/plugin.json"))
        + list(root.glob("plugins/*/package.json"))
    )
    if not files:
        raise DataError(f"{root}/plugins 底下找不到任何版號檔")
    found: dict[str, tuple[int, int, int]] = {}
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise DataError(f"讀不到或解析不了 {path}：{e}") from e
        if not isinstance(data, dict):
            raise DataError(f"{path} 不是 JSON 物件")
        found[str(path.relative_to(root))] = _parse(data.get("version"), str(path))
    return found


def plan(root: Path) -> tuple[str, tuple[int, int, int]]:
    """回傳 (MODE, VERSION)。"""
    versions = plugin_versions(root)
    distinct = sorted(set(versions.values()))
    if len(distinct) != 1:
        detail = ", ".join(f"{p}={_fmt(v)}" for p, v in sorted(versions.items()))
        raise PlanError(f"plugin 版號不一致，先用 scripts/sync-plugin-versions.sh 對齊：{detail}")
    plugin = distinct[0]
    project = pyproject_version(root)
    if plugin > project:
        return "adopt", plugin
    if plugin == project:
        return "bump", project
    raise PlanError(
        f"plugin 版號 {_fmt(plugin)} 小於 pyproject.toml 的 {_fmt(project)}，"
        "代表有人把 plugin 降版或手改了 pyproject.toml；先查明再發版"
    )


def apply_adopt(root: Path, version: tuple[int, int, int]) -> None:
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    new_text, count = _PYPROJECT_VERSION.subn(f'version = "{_fmt(version)}"', text, count=1)
    if count != 1:
        raise DataError(f"{path} 的 version 行沒有被更新")
    path.write_text(new_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repo 根目錄")
    parser.add_argument(
        "--apply", action="store_true", help="MODE=adopt 時把 pyproject.toml 對齊 plugin 版號"
    )
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        mode, version = plan(root)
        if args.apply and mode == "adopt":
            apply_adopt(root, version)
    except PlanError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 1
    except DataError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    print(f"MODE={mode}")
    print(f"VERSION={_fmt(version)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

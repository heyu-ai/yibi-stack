"""驗證 wheel 的打包範圍符合 ADR-0004 的宣稱。

由 scripts/packaging_smoke_test.sh 呼叫。fail loud：任何一項不符即 exit 1。

檢查項目對應 ADR-0004 / plugin-primary-plan.md Phase 1 的驗證閘門：
- 必須含 tasks/（否則 wheel 是空殼）
- 不得含 scripts/（個人帳務工具，硬編碼 localhost:5435/ledgerone，不該出貨）
- 不得含 plugins/ 或 .venv（打包範圍失控）
- 不得含測試（原本佔 wheel 檔案數的 38%）
- entry_points.txt 必須註冊 pyproject 宣告的每個 console script
"""

from __future__ import annotations

import configparser
import sys
import tomllib
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _declared_scripts() -> dict[str, str]:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data.get("project", {}).get("scripts", {})


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        _fail("用法：check_wheel_contents.py <wheel path>")

    wheel_path = Path(sys.argv[1])
    if not wheel_path.is_file():
        _fail(f"wheel 不存在：{wheel_path}")

    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
        entry_points_txt = next(
            (n for n in names if n.endswith(".dist-info/entry_points.txt")), None
        )
        entry_points_raw = zf.read(entry_points_txt).decode("utf-8") if entry_points_txt else ""

    tasks_files = [n for n in names if n.startswith("tasks/")]
    if not tasks_files:
        _fail("wheel 不含 tasks/，打包範圍錯誤")

    forbidden = {
        "scripts/": [n for n in names if n.startswith("scripts/")],
        "plugins/": [n for n in names if n.startswith("plugins/")],
        ".venv": [n for n in names if ".venv" in n],
        "tests": [n for n in names if "/tests/" in n],
    }
    for label, hits in forbidden.items():
        if hits:
            _fail(f"wheel 不該含 {label}，實得 {len(hits)} 個檔案，例如 {hits[0]}")

    declared = _declared_scripts()
    if not declared:
        _fail("pyproject.toml 的 [project.scripts] 是空的")
    if not entry_points_txt:
        _fail("wheel 的 dist-info 缺少 entry_points.txt；console script 不會被安裝")

    parser = configparser.ConfigParser()
    parser.read_string(entry_points_raw)
    shipped = dict(parser["console_scripts"]) if parser.has_section("console_scripts") else {}

    for name, target in declared.items():
        if name not in shipped:
            _fail(f"entry_points.txt 未註冊 {name!r}；安裝後不會有該指令")
        if shipped[name] != target:
            _fail(f"{name} 的 entry point 不符：wheel={shipped[name]!r} pyproject={target!r}")

    print(f"[OK] wheel 內容：{len(names)} 檔，全部在 tasks/ 之下")
    print("[OK] 無 scripts/ / plugins/ / .venv / tests")
    print(f"[OK] entry_points 已註冊：{', '.join(sorted(shipped))}")


if __name__ == "__main__":
    main()

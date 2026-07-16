"""驗證 wheel 的打包範圍符合 ADR-0004 的宣稱。

由 scripts/packaging_smoke_test.sh 呼叫。fail loud：任何一項不符即 exit 1。

**allow-list，不是 block-list。** 這是刻意的：本檔的第一版擋 4 個寫死的前綴
（scripts/ plugins/ .venv /tests/）卻印「全部在 tasks/ 之下」——一句它從未檢查的話。
PR #249 的 review 用合成 wheel 證明了後果：帶 `openspec/`、頂層 `tests/`、根目錄 `.env`
的 wheel 全都通過，其中一個還夾帶 `localhost:5435/ledgerone` DSN（正是本閘門宣稱要擋的
東西）。block-list 只擋得住你想得到的名字；allow-list 擋得住你想不到的。

檢查項目：
- wheel 只得含 tasks/ 與 *.dist-info/（任何越界檔案即 fail，不需預先列舉壞名字）
- 必須含 tasks/（否則 wheel 是空殼）
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

    # allow-list：只有 tasks/ 與 dist-info metadata 可以出現。任何其他路徑一律 fail，
    # 不論它叫什麼——這才讓下方的 [OK] 訊息成為真的斷言而非裝飾。
    stray = [n for n in names if not (n.startswith("tasks/") or ".dist-info/" in n)]
    if stray:
        _fail(
            f"wheel 只該含 tasks/ 與 dist-info，實得 {len(stray)} 個越界檔案："
            f"{', '.join(sorted(stray)[:5])}"
        )

    # 測試不出貨。與 stray 檢查獨立：tests 在 tasks/ 之下，allow-list 放行它們。
    test_files = [n for n in names if "/tests/" in n or n.startswith("tests/")]
    if test_files:
        _fail(f"wheel 不該含測試，實得 {len(test_files)} 個檔案，例如 {test_files[0]}")

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

    print(f"[OK] wheel 內容：{len(names)} 檔，僅 tasks/（{len(tasks_files)}）與 dist-info")
    print("[OK] 無測試")
    print(f"[OK] entry_points 已註冊：{', '.join(sorted(shipped))}")


if __name__ == "__main__":
    main()

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
import re
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


def _top_level(name: str) -> str:
    """回傳 wheel 內路徑的頂層元件（zip 路徑一律用 /）。"""
    return name.split("/", 1)[0]


def _is_allowed(name: str) -> bool:
    """路徑是否屬於允許的頂層目錄：tasks/ 或 <name>.dist-info/。

    以**頂層目錄**判斷而非子字串——見上方 stray 檢查的註解。
    """
    top = _top_level(name)
    return top == "tasks" or top.endswith(".dist-info")


def _sole_dist_info(names: list[str]) -> str:
    """回傳唯一的頂層 dist-info 目錄名；不是剛好一個、或名稱不符 distribution 即 fail。

    為何要求「剛好一個」而非「找到一個就好」：本檔第一版用
    `next(n for n in names if n.endswith(".dist-info/entry_points.txt"))` 取第一個命中，
    於是一個含**兩個** dist-info 的 wheel 可以讓誘餌勝出——實測（PR #249 round 3）：
    誘餌帶正確的 entry point、真品帶壞的，守衛讀誘餌後放行，而安裝出來的指令是壞的。
    wheel 規格本來就只該有一個 dist-info，所以「剛好一個」是免費的正確性。

    名稱也要對得上：PEP 427 的 dist-info 目錄是 `<normalized-name>-<version>.dist-info`，
    normalize 規則見 PEP 503（- 與 . 轉 _）。
    """
    dist_infos = sorted({_top_level(n) for n in names if _top_level(n).endswith(".dist-info")})
    if len(dist_infos) != 1:
        _fail(f"wheel 應剛好含 1 個頂層 dist-info，實得 {len(dist_infos)} 個：{dist_infos}")

    dist_info = dist_infos[0]
    expected_prefix = _normalized_project_name() + "-"
    if not dist_info.startswith(expected_prefix):
        _fail(
            f"dist-info 名稱與 distribution 不符：實得 {dist_info!r}，應以 {expected_prefix!r} 開頭"
        )
    return dist_info


def _normalized_project_name() -> str:
    """pyproject 的 project.name 依 PEP 503 正規化（用於比對 dist-info 目錄名）。"""
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    name = data.get("project", {}).get("name", "")
    if not name:
        _fail("pyproject.toml 缺少 project.name")
    return re.sub(r"[-_.]+", "_", name)


def main() -> None:
    if len(sys.argv) < 2:
        _fail("用法：check_wheel_contents.py <wheel path>")

    wheel_path = Path(sys.argv[1])
    if not wheel_path.is_file():
        _fail(f"wheel 不存在：{wheel_path}")

    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
        # 拒絕非正規成員名稱：絕對路徑、反斜線、或含 `..` 路徑元件。正常 uv build 不會產出
        # 這類名稱；用頂層目錄判斷 allow-list 前先擋掉，避免 `tasks/../evil.py` 之類藉頂層
        # 目錄偽裝通過（防禦縱深，回應 mob review 的路徑遍歷 finding）。
        malformed = [
            n for n in names if n.startswith("/") or "\\" in n or ".." in n.split("/")
        ]
        if malformed:
            _fail(
                f"wheel 含非正規成員名稱（絕對路徑／反斜線／.. 遍歷），拒絕："
                f"{', '.join(sorted(malformed)[:5])}"
            )
        dist_info = _sole_dist_info(names)
        entry_points_name = f"{dist_info}/entry_points.txt"
        entry_points_txt = entry_points_name if entry_points_name in names else None
        entry_points_raw = zf.read(entry_points_txt).decode("utf-8") if entry_points_txt else ""

    tasks_files = [n for n in names if n.startswith("tasks/")]
    if not tasks_files:
        _fail("wheel 不含 tasks/，打包範圍錯誤")

    # allow-list：只有 tasks/ 與**頂層**的 <name>.dist-info/ 可以出現。
    #
    # 比對頂層目錄，不用子字串。`".dist-info/" in n` 看似等價，實則讓
    # `plugins/my.dist-info/evil.py` 整個通過——實測確認（PR #249 round 3）。這與 round 2
    # 修掉的 `"/tests/" in n` 漏掉頂層 tests/ 是**同一類缺陷**：用子字串回答「這個路徑屬於
    # 哪個頂層目錄」永遠會被構造出的名字繞過。問結構，不要問子字串。
    stray = [n for n in names if not _is_allowed(n)]
    if stray:
        _fail(
            f"wheel 只該含 tasks/ 與頂層 *.dist-info/，實得 {len(stray)} 個越界檔案："
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
    parser.optionxform = str  # 保留 entry-point 名稱大小寫（configparser 預設轉小寫）
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

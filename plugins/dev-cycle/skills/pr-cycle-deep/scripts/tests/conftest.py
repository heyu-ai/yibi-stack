"""共用 script import 路徑與獨立安裝 runtime fixtures。"""

import shutil
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def review_runtime_copy(tmp_path: Path) -> Path:
    """複製實際發佈檔案，避免 drift 測試改到工作樹或全域安裝。"""
    source = Path(__file__).resolve().parent.parent
    target = tmp_path / "installed-review-skill"
    target.mkdir()
    for name in (
        "review_markdown.py",
        "review_scope.py",
        "review_scope.py.lock",
        "check_review_counts.py",
        "check_review_counts.py.lock",
        "setup-review-dir.sh",
    ):
        shutil.copy2(source / name, target / name)
    return target


@pytest.fixture
def drift_review_metadata() -> Callable[[Path], None]:
    """加入已鎖定的傳遞依賴作為直接依賴，製造可解析但未更新 lock 的 metadata。"""

    def drift(script: Path) -> None:
        lock = tomllib.loads(script.with_suffix(".py.lock").read_text(encoding="utf-8"))
        direct = {item["name"] for item in lock["manifest"]["requirements"]}
        extra = next(package for package in lock["package"] if package["name"] not in direct)
        requirement = f"{extra['name']}=={extra['version']}"
        original = script.read_text(encoding="utf-8")
        changed = original.replace("# dependencies = [", f'# dependencies = ["{requirement}", ', 1)
        if changed == original:
            raise AssertionError("無法建立 metadata drift fixture")
        script.write_text(changed, encoding="utf-8")

    return drift

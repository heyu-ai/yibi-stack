"""共用 script import 路徑與獨立安裝 runtime fixtures。"""

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import shutil
import subprocess  # nosec B404
import sys
import tomllib
import zipfile
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
        "pre_review_check.py",
        "amplifier-verify.py",
        "amplifier-verify.py.lock",
    ):
        shutil.copy2(source / name, target / name)
    return target


@pytest.fixture(scope="session")
def review_dependency_wheels(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """重建已安裝的真實依賴 wheels，保留原始 ABI／平台標籤與套件內容。"""
    target = tmp_path_factory.mktemp("review-dependency-wheels")
    for name in ("markdown-it-py", "mdurl", "PyYAML"):
        distribution = importlib.metadata.distribution(name)
        files = list(distribution.files or ())
        info = next(
            item.parent
            for item in files
            if item.name == "METADATA" and item.parent.name.endswith(".dist-info")
        )
        wheel_metadata = distribution.read_text("WHEEL")
        if wheel_metadata is None:
            raise AssertionError(f"依賴缺少 WHEEL metadata：{name}")
        tag = next(
            line.removeprefix("Tag: ")
            for line in wheel_metadata.splitlines()
            if line.startswith("Tag: ")
        )
        wheel = target / f"{name.lower().replace('-', '_')}-{distribution.version}-{tag}.whl"
        records = []
        with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in files:
                if (
                    ".." in item.parts
                    or "__pycache__" in item.parts
                    or item.name in ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json")
                ):
                    continue
                content = Path(distribution.locate_file(item)).read_bytes()
                archive.writestr(item.as_posix(), content)
                digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=")
                records.append((item.as_posix(), "sha256=" + digest.decode(), str(len(content))))
            record_path = (info / "RECORD").as_posix()
            records.append((record_path, "", ""))
            record = io.StringIO()
            csv.writer(record, lineterminator="\n").writerows(records)
            archive.writestr(record_path, record.getvalue())
    return target


@pytest.fixture
def drift_review_metadata(review_dependency_wheels: Path) -> Callable[[Path], bytes]:
    """在 shipped-lock 正向對照後，改用本機 wheel feed，建立不依賴 registry cache 的 drift。"""

    def drift(script: Path) -> bytes:
        original = script.read_text(encoding="utf-8")
        settings = (
            "\n# [tool.uv]\n# no-index = true\n"
            f"# find-links = [{json.dumps(str(review_dependency_wheels))}]\n# ///\n"
        )
        local = original.replace("\n# ///\n", settings, 1)
        if local == original:
            raise AssertionError("無法建立本機 runtime fixture")
        script.write_text(local, encoding="utf-8")
        subprocess.run(  # nosec B603 B607
            ["uv", "lock", "--offline", "--no-config", "--script", str(script)],
            cwd=script.parent,
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        before = script.with_suffix(".py.lock").read_bytes()
        lock = tomllib.loads(before.decode("utf-8"))
        direct = {item["name"] for item in lock["manifest"]["requirements"]}
        extra = next(package for package in lock["package"] if package["name"] not in direct)
        requirement = f"{extra['name']}=={extra['version']}"
        changed = local.replace("# dependencies = [", f'# dependencies = ["{requirement}", ', 1)
        if changed == local:
            raise AssertionError("無法建立 metadata drift fixture")
        script.write_text(changed, encoding="utf-8")
        return before

    return drift


@pytest.fixture(scope="session")
def review_uv() -> Path:
    """在原 HOME 下解析 uv 真實執行檔，避免隔離 HOME 使 asdf／mise shim 失效。"""
    executable = shutil.which("uv")
    if executable is None:
        pytest.skip("找不到 uv，無法執行 locked standalone launcher 行為測試")
    candidate = Path(executable)
    if candidate.parent.name == "shims":
        for name in ("asdf", "mise"):
            manager = shutil.which(name)
            if manager is None:
                continue
            resolved = subprocess.run(  # nosec B603
                [manager, "which", "uv"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if resolved.returncode == 0 and resolved.stdout.strip():
                candidate = Path(resolved.stdout.strip()).resolve()
                break
        else:
            pytest.fail("uv 存在但無法透過原本的 tool manager 解析真實執行檔")
    if not candidate.is_file():
        pytest.fail(f"uv 執行檔無法讀取：{candidate}")
    return candidate.resolve()

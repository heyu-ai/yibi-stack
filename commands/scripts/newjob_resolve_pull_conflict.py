"""git pull 前自動解決 untracked 檔案衝突（僅刪除與 origin/main 完全相同的檔案）。"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path


def parse_conflicting_files(stderr: str) -> list[str]:
    """從 git pull 的 stderr 中解析出衝突的 untracked 檔案路徑。"""
    files: list[str] = []
    in_list = False
    for line in stderr.splitlines():
        if "would be overwritten by merge" in line:
            in_list = True
            continue
        if in_list:
            stripped = line.strip()
            if not stripped or stripped.startswith("Please"):
                break
            files.append(stripped)
    return files


def get_origin_content(path: str) -> bytes | None:
    """取得 origin/main 上的檔案內容；若不存在則回傳 None。"""
    result = subprocess.run(  # nosec B603
        ["git", "show", f"origin/main:{path}"],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def is_identical_to_origin(path: str) -> bool:
    """比對本地 untracked 檔案與 origin/main 版本是否 byte-for-byte 相同。"""
    local = Path(path)
    if not local.exists():
        return False
    origin = get_origin_content(path)
    if origin is None:
        return False
    return local.read_bytes() == origin


def try_pull() -> tuple[bool, str]:
    """執行 git pull origin main，回傳 (成功與否, stderr)。"""
    result = subprocess.run(  # nosec B603
        ["git", "pull", "origin", "main"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr


def main() -> int:
    """執行 pull 並自動解決 identical untracked 檔案衝突；回傳 exit code。"""
    success, stderr = try_pull()
    if success:
        print("[OK] git pull succeeded")
        return 0

    conflicting = parse_conflicting_files(stderr)
    if not conflicting:
        print(f"[FAIL] git pull failed for unexpected reason:\n{stderr}", file=sys.stderr)
        return 1

    safe: list[str] = []
    modified: list[str] = []
    for f in conflicting:
        if is_identical_to_origin(f):
            safe.append(f)
        else:
            modified.append(f)

    if modified:
        msg = "[FAIL] untracked files differ from origin/main -- manual resolution required:"
        print(msg, file=sys.stderr)
        for f in modified:
            print(f"  {f}", file=sys.stderr)
        return 1

    for f in safe:
        Path(f).unlink()
        print(f"  [OK] removed identical untracked file: {f}")

    success, stderr = try_pull()
    if not success:
        print(f"[FAIL] git pull failed after conflict resolution:\n{stderr}", file=sys.stderr)
        return 1

    print("[OK] git pull succeeded after resolving conflicts")
    return 0


if __name__ == "__main__":
    sys.exit(main())

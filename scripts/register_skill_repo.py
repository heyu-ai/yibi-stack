"""將 skill_repo 路徑寫入 ~/.agents/config.json。"""

import json
import pathlib
import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("  ✗ 使用方式：register_skill_repo.py <repo_path>", file=sys.stderr)
        sys.exit(1)

    repo_path = sys.argv[1]
    p = pathlib.Path.home() / ".agents" / "config.json"

    try:
        raw = p.read_text(encoding="utf-8") if p.exists() else "{}"
    except OSError as e:
        print(f"  ✗ 無法讀取 {p}：{e}", file=sys.stderr)
        sys.exit(1)

    try:
        c = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ✗ config.json JSON 格式錯誤（{e}），請檢查或刪除該檔案：{p}", file=sys.stderr)
        sys.exit(1)

    c["skill_repo"] = repo_path

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"  ✗ 無法寫入 {p}：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

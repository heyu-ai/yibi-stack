"""將 skill_repo 路徑寫入 ~/.agents/config.json 的 per-repo map。

背景（issue #197）：`~/.agents/config.json` 原本只有單一 `skill_repo` 欄位，
yibi-stack 與 ainization-skill 兩個 repo 的 `make install` 都會把它覆寫成自己，
誰最後安裝誰贏，形成乒乓球式 config drift。

根治：改寫 `skill_repos["<repo-name>"]`（key = repo 目錄名），讓 N 個 skill repo
共存、互不覆寫；頂層 `skill_repo` 只保留為 legacy fallback（過渡期向下相容），
**不再覆寫**——僅在完全缺席時以 setdefault 補一份，供尚未升級的舊 reader 使用。
"""

import json
import pathlib
import sys


def register(repo_path: str, config_path: pathlib.Path) -> None:
    """把 repo_path 註冊進 config_path 的 skill_repos map；不覆寫頂層 skill_repo。"""
    try:
        raw = config_path.read_text(encoding="utf-8") if config_path.exists() else "{}"
    except OSError as e:
        print(f"  ✗ 無法讀取 {config_path}：{e}", file=sys.stderr)
        raise SystemExit(1) from e

    try:
        c = json.loads(raw)
    except json.JSONDecodeError as e:
        print(
            f"  ✗ config.json JSON 格式錯誤（{e}），請檢查或刪除該檔案：{config_path}",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    repo_name = pathlib.Path(repo_path).name

    skill_repos = c.get("skill_repos")
    if not isinstance(skill_repos, dict):
        # 第一次以新版 register 安裝：把現有頂層 legacy 值搬進 map，再建立本 repo 的 entry。
        skill_repos = {}
        legacy = c.get("skill_repo")
        if isinstance(legacy, str) and legacy:
            skill_repos[pathlib.Path(legacy).name] = legacy

    skill_repos[repo_name] = repo_path
    c["skill_repos"] = skill_repos

    # 不覆寫頂層 skill_repo（避免多 repo 互搶）；僅在缺席時補一份給舊 reader 過渡。
    c.setdefault("skill_repo", repo_path)

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"  ✗ 無法寫入 {config_path}：{e}", file=sys.stderr)
        raise SystemExit(1) from e


def main() -> None:
    if len(sys.argv) < 2:
        print("  ✗ 使用方式：register_skill_repo.py <repo_path>", file=sys.stderr)
        raise SystemExit(1)

    config_path = pathlib.Path.home() / ".agents" / "config.json"
    register(sys.argv[1], config_path)


if __name__ == "__main__":
    main()

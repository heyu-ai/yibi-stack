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


def register(repo_path: str, config_path: pathlib.Path, repo_name: str | None = None) -> None:
    """把 repo_path 註冊進 config_path 的 skill_repos map；不覆寫頂層 skill_repo。

    repo_name 是 map 的 canonical key（例如 "yibi-stack"）。呼叫端（Makefile）應**顯式**傳入
    repo 的正規識別名，讓 writer 寫入的 key 與 reader 端硬編碼查詢的 key 一致——不因 checkout
    目錄改名 / worktree / fork 而算出不同的 key（issue #199 mob review Critical）。未指定時退回
    目錄 basename（向下相容既有呼叫）。
    """
    # anchor 成絕對路徑：Makefile 傳 $(CURDIR) 已是絕對，此處防手動以相對路徑呼叫而寫入相對路徑
    # （稍後會被 AgentsConfig 絕對路徑驗證擋下，使所有 reader 整批失效）。不 resolve symlink，
    # 保留 worktree / symlink 原始路徑。
    repo_path = str(pathlib.Path(repo_path).absolute())

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

    if repo_name is None:
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
        print(
            "  ✗ 使用方式：register_skill_repo.py <repo_path> [repo_name]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    config_path = pathlib.Path.home() / ".agents" / "config.json"
    repo_name = sys.argv[2] if len(sys.argv) > 2 else None
    register(sys.argv[1], config_path, repo_name)


if __name__ == "__main__":
    main()

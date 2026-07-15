"""將 skill_repo 路徑寫入 ~/.agents/config.json 的 per-repo map。

背景（issue #197）：`~/.agents/config.json` 原本只有單一 `skill_repo` 欄位，
yibi-stack 與 ainization-skill 兩個 repo 的 `make install` 都會把它覆寫成自己，
誰最後安裝誰贏，形成乒乓球式 config drift。

根治：改寫 `skill_repos["<repo-name>"]`，讓 N 個 skill repo 共存、互不覆寫。map key 是
安裝端顯式提供的 **canonical repo 識別名**（Makefile 傳 `SKILL_REPO_KEY`，例如 "yibi-stack"），
與 reader 端硬編碼查詢的 key 一致；**不可**用 checkout 目錄 basename，否則在 worktree /
改名 / fork clone 下 key 會漂掉、reader 永遠 miss（issue #199）。未顯式指定時才退回目錄
basename（legacy / 手動呼叫）。頂層 `skill_repo` 只保留為 legacy fallback（過渡期向下相容），
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
        skill_repos = {}

    # 遷移現有頂層 legacy skill_repo 進 map（idempotent：以 basename 為 key，只在缺席時補；
    # 與 map 是否已存在解耦，避免「skill_repos 已被建成 {} 但 legacy 尚未搬入」的漏遷）。
    legacy = c.get("skill_repo")
    if isinstance(legacy, str) and legacy:
        skill_repos.setdefault(pathlib.Path(legacy).name, legacy)

    skill_repos[repo_name] = repo_path
    c["skill_repos"] = skill_repos

    # 不覆寫「有效」的頂層 skill_repo（避免多 repo 互搶）；但當它 falsy（缺席 / "" / null）時
    # 補一份當前路徑給尚未升級、只讀頂層的舊 reader（setdefault 無法處理已存在的 falsy 值）。
    if not c.get("skill_repo"):
        c["skill_repo"] = repo_path

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

    # scripts/ 刻意不是 package（見 scripts/tests/test_register_skill_repo.py 的說明），
    # 故 `python3 scripts/register_skill_repo.py` 的 sys.path[0] 是 scripts/ 而非 repo 根，
    # 直接 `import tasks.*` 會 ModuleNotFoundError。這裡把 repo 根補進 sys.path 以重用
    # 唯一的 guard 實作——寧可在 main() 做這個受限的 bootstrap，也不要把 fail-closed 的
    # 包裝邏輯在此複製一份（rule 11：不要把已收斂成單一實作的邏輯重新散開）。
    # 只在 main() 做：測試以 importlib 載入本模組並直接呼叫 register()，不受影響。
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tasks._worktree_guard import assert_not_worktree

    # 守 **argv[1]**（要被寫進 config.json 的那個路徑），而不是本腳本自身的位置：
    # 被寫進 ~/.agents/config.json（機器層級）的毒是 repo_path，不是 __file__。
    assert_not_worktree(
        f"python3 scripts/register_skill_repo.py {sys.argv[1]}",
        repo_root=pathlib.Path(sys.argv[1]),
    )

    config_path = pathlib.Path.home() / ".agents" / "config.json"
    repo_name = sys.argv[2] if len(sys.argv) > 2 else None
    register(sys.argv[1], config_path, repo_name)


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Usage: link_claude_skill.sh <repo_root> <skill_name> <claude_skill_dir>
#
# 把 <repo_root>/skills/<skill_name> 連到 <claude_skill_dir>/<skill_name>，
# 但「由 plugin 提供」的 skill 例外。
#
# 判準：<repo_root>/skills/<skill_name> 本身是 symlink（指向 plugins/<pack>/skills/...）
# 代表這個 skill 的正本在 plugin 裡，Claude Code 會經由 plugin 機制載入它
# （skill 清單裡的 `dev-cycle:pr-cycle-deep`）。再連一份到 ~/.claude/skills/
# 會讓同一個 skill 出現兩次（`pr-cycle-deep` 與 `dev-cycle:pr-cycle-deep`），
# 且兩者指向不同來源（本機 checkout vs plugin cache），內容可能不同步。
#
# 這種情況下：
#   - 不建立連結；
#   - 若 dst 已是先前 make install 留下、指向本 repo 該 skill 的 symlink，移除它。
#     只移除 readlink 與預期完全相符的連結——其他來源的 symlink 或實體目錄一律不碰。
#
# Exit：0 成功或 no-op；其餘沿用 safe_symlink.sh 的 exit code（1 執行失敗、2 被實體路徑擋住）。

set -u

if [ "$#" -ne 3 ]; then
    echo "  [FAIL] link_claude_skill.sh: 需要 3 個參數 <repo_root> <skill_name> <claude_skill_dir>" >&2
    exit 1
fi

REPO_ROOT="$1"
NAME="$2"
DST_DIR="$3"

SRC="${REPO_ROOT}/skills/${NAME}"
DST="${DST_DIR}/${NAME}"
SCRIPT_DIR=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ -L "$SRC" ]; then
    if [ -L "$DST" ]; then
        CURRENT=$(readlink "$DST")
        if [ "$CURRENT" = "$SRC" ]; then
            if ! rm "$DST"; then
                echo "  [FAIL] ${NAME}: 無法移除重複連結 ${DST}" >&2
                exit 1
            fi
            echo "  [OK] ${NAME}: 已移除與 plugin 重複的連結 (${DST_DIR})"
            exit 0
        fi
    fi
    echo "  [SKIP] ${NAME}: 由 plugin 提供，不安裝到 ${DST_DIR}" >&2
    exit 0
fi

exec "${SCRIPT_DIR}/safe_symlink.sh" "$SRC" "$DST"

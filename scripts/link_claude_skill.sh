#!/usr/bin/env bash
# Usage: link_claude_skill.sh <repo_root> <skill_name> <claude_skill_dir>
#        link_claude_skill.sh --check <repo_root> <skill_name>
#
# --check：唯讀。stdout 印 `plugin`（由 plugin 提供）或 `native`，exit 0；
#          不建立也不移除任何連結。供 make status-own 與安裝路徑共用同一份判準。
#
# 把 <repo_root>/skills/<skill_name> 連到 <claude_skill_dir>/<skill_name>，
# 但「由 plugin 提供」的 skill 例外。
#
# 判準：<repo_root>/skills/<skill_name> 是 symlink，且解析後的實體路徑落在
# <repo_root>/plugins/ 之下，代表這個 skill 的正本在 plugin 裡，
# Claude Code 會經由 plugin 機制載入它（不驗證該 plugin 是否已安裝）
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

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=1
    shift
    if [ "$#" -ne 2 ]; then
        echo "  [FAIL] link_claude_skill.sh --check: 需要 2 個參數 <repo_root> <skill_name>" >&2
        exit 1
    fi
    REPO_ROOT="$1"
    NAME="$2"
    DST_DIR=""
else
    if [ "$#" -ne 3 ]; then
        echo "  [FAIL] link_claude_skill.sh: 需要 3 個參數 <repo_root> <skill_name> <claude_skill_dir>" >&2
        exit 1
    fi
    REPO_ROOT="$1"
    NAME="$2"
    DST_DIR="$3"
fi

SRC="${REPO_ROOT}/skills/${NAME}"
DST="${DST_DIR}/${NAME}"
SCRIPT_DIR=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# 「由 plugin 提供」= SRC 是 symlink，且解析後的實體目錄落在 <repo>/plugins/ 之下。
# 只看 -L 太寬：指向 plugins/ 以外（或已失效）的 symlink 並不是 plugin 提供的，
# 把它當成 plugin skill 會讓該 skill 在 Claude Code 憑空消失。
# 兩個路徑都用 cd -P + pwd -P 取實體路徑，避免 macOS 的 /var -> /private/var 造成前綴不符。
PLUGIN_PROVIDED=0
if [ -L "$SRC" ]; then
    if ! RESOLVED_SRC=$(cd -P "$SRC" 2>/dev/null && pwd -P); then
        RESOLVED_SRC=""
    fi
    if ! RESOLVED_ROOT=$(cd -P "$REPO_ROOT" 2>/dev/null && pwd -P); then
        RESOLVED_ROOT=""
    fi
    if [ -n "$RESOLVED_SRC" ] && [ -n "$RESOLVED_ROOT" ]; then
        case "$RESOLVED_SRC" in
            "${RESOLVED_ROOT}/plugins/"*) PLUGIN_PROVIDED=1 ;;
        esac
    fi
fi

if [ "$CHECK_ONLY" = "1" ]; then
    # 唯讀：只回報判準結果，供 make status-own 等呼叫端共用同一份判準，不碰任何檔案。
    if [ "$PLUGIN_PROVIDED" = "1" ]; then
        echo "plugin"
    else
        echo "native"
    fi
    exit 0
fi

if [ "$PLUGIN_PROVIDED" = "1" ]; then
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

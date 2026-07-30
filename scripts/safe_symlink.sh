#!/usr/bin/env bash
# Usage: safe_symlink.sh [--force] <src> <dst>
# Creates symlink dst→src with dangling/existing/real-dir state handling.
# --force: remove real directory/file at dst before linking.
# Exits 0 on success or no-op; exits 1 on ln failure.

FORCE=0
if [ "$1" = "--force" ]; then
    FORCE=1
    shift
fi

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "  ✗ safe_symlink.sh: src and dst arguments are required" >&2
    exit 1
fi

src="$1"
dst="$2"
name=$(basename "$dst")
dir=$(dirname "$dst")

if [ -L "$dst" ] && [ ! -e "$dst" ]; then
    rm -f "$dst" && ln -sf "$src" "$dst" \
        && echo "  ⚠ $name → relinked ($dir)" \
        || { echo "  ✗ $name → relink FAILED in $dir" >&2; exit 1; }
elif [ -L "$dst" ]; then
    # 既有且有效的 symlink：必須比對目標，不能無條件當作 no-op。
    # 舊版直接印 ↻ 略過，導致 checkout 搬移或換一份 checkout 重跑 make install 時
    # symlink 仍指向舊 checkout，之後所有經此連結執行的腳本都靜默跑在錯的 repo 上
    # （self-locate 解析出的正是這個舊路徑）。此處目標不符即重指。
    current=$(readlink "$dst")
    if [ "$current" = "$src" ]; then
        echo "  ↻ $name ($dir)"
    else
        rm -f "$dst" && ln -sf "$src" "$dst" \
            && echo "  ⚠ $name → repointed ($dir): $current → $src" \
            || { echo "  ✗ $name → repoint FAILED in $dir" >&2; exit 1; }
    fi
elif [ -e "$dst" ]; then
    if [ "$FORCE" = "1" ]; then
        if [ ! -e "$src" ] && [ ! -L "$src" ]; then
            echo "  ✗ $name → src does not exist: $src" >&2; exit 1
        fi
        rm -rf "$dst" && ln -sf "$src" "$dst" \
            && echo "  ✓ $name → $dir (forced)" \
            || { echo "  ✗ $name → force FAILED in $dir" >&2; exit 1; }
    else
        # 不覆蓋是對的——破壞性動作只在 --force 時發生。但**不能 exit 0**：
        # 呼叫端（make install 的 for 迴圈）只讀 exit code，靜默成功會讓整個
        # 安裝回報 OK 卻少裝一個 skill，失敗只存在於一行沒人讀的 stderr。
        # exit 2 專表「被實體路徑擋住，需操作者介入」，與 exit 1 的「真正執行
        # 失敗（ln 壞了、參數缺了）」分開，呼叫端才能對症給出 --force 修法。
        echo "  ✗ $name → real path exists (not a symlink), NOT installed: $dst" >&2
        echo "    Remove it, or re-run with --force to overwrite" >&2
        exit 2
    fi
else
    ln -sf "$src" "$dst" \
        && echo "  ✓ $name → $dir" \
        || { echo "  ✗ $name → $dir FAILED" >&2; exit 1; }
fi

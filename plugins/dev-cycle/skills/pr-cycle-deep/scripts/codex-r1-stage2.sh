#!/usr/bin/env bash
# pr-cycle-deep Step 3.2 — Codex R1 Stage 2：Extract（raw → JSON）
#
# 用法：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage2.sh
#
# 副作用：
#   - codex-r1.json 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/codex-r1.extract.log
#   - 暫存 codex-extract-input.md（完成後自動刪除）
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

EXTRACT_PROMPT=~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md

if [ ! -f "$EXTRACT_PROMPT" ]; then
    echo "[FAIL] extract prompt 不存在；請執行 make install" >&2
    exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if [ ! -f "$REVIEW_DIR/codex-r1-raw.md" ]; then
    echo "[FAIL] codex-r1-raw.md 不存在；請確認 Stage 1 已成功完成" >&2
    exit 1
fi

if ! cat "$EXTRACT_PROMPT" "$REVIEW_DIR/codex-r1-raw.md" > "$REVIEW_DIR/codex-extract-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

printf '\n---END RAW OUTPUT---\n' >> "$REVIEW_DIR/codex-extract-input.md"

# 模型固定為 gpt-5.6-luna 並帶 --ignore-user-config（issue #444）：
#   - 萃取只是把 raw markdown 轉成 JSON，不需推理，故不用 stage1／R2 pin 的 frontier tier
#     （CDXS-DT-011）；但也不能不 pin。不 pin 等於繼承 ~/.codex/config.toml，實測 codex-cli
#     0.149.0 搭配 config 裡的 gpt-6-astra 時每次都回 400「requires a newer version of Codex」，
#     而且繼承到的反而可能是比 frontier 更貴的 tier。
#   - --ignore-user-config 連同 config 裡的 MCP server、plugin 一起不載入：這個機械轉換用不到
#     它們，實測同一個 luna 呼叫的 token 用量從 16,645 降到 9,339。auth 不受影響（仍讀 CODEX_HOME）。
# gpt-5.6-luna 取自 ~/.codex/models_cache.json（codex-cli 0.149.0，「Fast and affordable agentic
# coding model」）；codex 升級後若回報 model 不存在，先查該檔的 slug 清單再更新這裡與測試常數。
if ! codex exec --ignore-user-config -m gpt-5.6-luna \
    -C "$WT_ROOT" -s read-only -c 'model_reasoning_effort="low"' \
    < "$REVIEW_DIR/codex-extract-input.md" \
    2>"$REVIEW_DIR/codex-r1.extract.log" \
    | tee "$REVIEW_DIR/codex-r1.json" > /dev/null; then
    echo "[FAIL] codex extract 失敗，請查看 $REVIEW_DIR/codex-r1.extract.log" >&2
    rm -f "$REVIEW_DIR/codex-extract-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/codex-extract-input.md"

if [ ! -s "$REVIEW_DIR/codex-r1.json" ]; then
    echo "[FAIL] codex-r1.json 空白，Extract 輸出異常" >&2
    exit 1
fi

echo "Codex R1 Stage 2 complete"

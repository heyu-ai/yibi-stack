#!/bin/bash
# 列出 ~/.claude/skills/ 下所有非 gstack skill
# 排除條件：symlink SKILL.md 的目標路徑含 /gstack/
# 用法：bash scripts/list_non_gstack_skills.sh
set -euo pipefail

SKILLS_DIR="${HOME}/.claude/skills"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "[FAIL] 目錄不存在：$SKILLS_DIR" >&2
    exit 1
fi

ALL_SKILLS=$(ls "$SKILLS_DIR" | sort)
GSTACK_SKILLS=""

for d in "$SKILLS_DIR"/*/; do
    name=$(basename "$d")
    target=$(readlink "${d}SKILL.md" 2>/dev/null || true)
    if [ -n "$target" ]; then
        case "$target" in
            */gstack/*)
                GSTACK_SKILLS="${GSTACK_SKILLS}${name}"$'\n'
                ;;
        esac
    fi
done

GSTACK_SORTED=$(printf '%s' "$GSTACK_SKILLS" | sort)

comm -23 \
    <(printf '%s\n' $ALL_SKILLS) \
    <(printf '%s\n' $GSTACK_SORTED | grep -v '^$')

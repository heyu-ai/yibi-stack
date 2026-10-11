#!/usr/bin/env bash
# Existing-PR fix pushes only. Run immediately before push in the same && chain:
#   bash preflight-pr-push.sh <pr-number> <expected-pr-head> && git push
# Reads the caller's Git/GitHub context; never pushes or changes refs itself.
# Exit 0: OPEN, expected remote head, matching branch and local fast-forward.
# Exit 1: usage, unavailable tools/API, malformed response or invalid local state.
# Exit 2: MERGED/CLOSED. Exit 3: branch/head mismatch or non-fast-forward.
# This is a preflight, not an atomic GitHub-state/Git-push lock. Keep the post-push check.

set -euo pipefail

fail() {
    echo "[FAIL] $*" >&2
    exit 1
}

if [ "$#" -ne 2 ]; then
    fail "Usage: bash preflight-pr-push.sh <pr-number> <expected-pr-head>"
fi
PR_NUMBER="$1"
EXPECTED_HEAD="$2"
if ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ && "$EXPECTED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
    fail "PR number must be positive and expected head must be a full 40-hex commit SHA"
fi
for tool in git gh jq; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required tool unavailable: $tool"
done
if ! LOCAL_BRANCH=$(git symbolic-ref --quiet --short HEAD); then
    fail "Not on a Git branch; do not push review fixes from a detached HEAD"
fi
if ! LOCAL_HEAD=$(git rev-parse --verify HEAD); then
    fail "Cannot resolve the local commit to push"
fi

if ! PR_JSON=$(gh pr view "$PR_NUMBER" --json number,state,headRefName,headRefOid); then
    fail "gh pr view failed for PR #$PR_NUMBER; no push authorized"
fi
if ! jq -e --argjson number "$PR_NUMBER" '
    type == "object" and .number == $number
    and (.state | type == "string")
    and (.headRefName | type == "string" and length > 0)
    and (.headRefOid | type == "string" and test("^[0-9a-f]{40}$"))
' <<< "$PR_JSON" >/dev/null; then
    fail "PR #$PR_NUMBER returned incomplete or malformed metadata; no push authorized"
fi
PR_STATE=$(jq -r '.state' <<< "$PR_JSON")
PR_BRANCH=$(jq -r '.headRefName' <<< "$PR_JSON")
PR_HEAD=$(jq -r '.headRefOid' <<< "$PR_JSON")

case "$PR_STATE" in
    OPEN) ;;
    MERGED|CLOSED)
        echo "[STOP] PR #$PR_NUMBER is $PR_STATE; keep local fixes, do not push or recreate its branch" >&2
        exit 2
        ;;
    *) fail "Unexpected PR state: $PR_STATE; no push authorized" ;;
esac
if ! git check-ref-format "refs/heads/$PR_BRANCH" >/dev/null; then
    fail "Invalid PR head branch; no push authorized"
fi
if [ "$LOCAL_BRANCH" != "$PR_BRANCH" ]; then
    echo "[STOP] Current branch '$LOCAL_BRANCH' is not PR #$PR_NUMBER head '$PR_BRANCH'" >&2
    exit 3
fi
if [ "$PR_HEAD" != "$EXPECTED_HEAD" ]; then
    echo "[STOP] PR #$PR_NUMBER head moved: expected $EXPECTED_HEAD, got $PR_HEAD; re-review before pushing" >&2
    exit 3
fi
if ! git merge-base --is-ancestor "$EXPECTED_HEAD" "$LOCAL_HEAD"; then
    echo "[STOP] Local HEAD $LOCAL_HEAD is not a fast-forward of PR head $EXPECTED_HEAD" >&2
    exit 3
fi
printf '[OK] PR #%s is OPEN; branch=%s PR_HEAD=%s LOCAL_HEAD=%s\n' \
    "$PR_NUMBER" "$PR_BRANCH" "$PR_HEAD" "$LOCAL_HEAD"

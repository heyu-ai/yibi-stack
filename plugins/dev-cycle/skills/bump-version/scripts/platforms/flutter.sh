#!/usr/bin/env bash
# platforms/flutter.sh — Flutter post-release hook
# 在 git tag 推上後，驗證 GitHub Actions CI workflow 已被觸發
# TestFlight 上傳由 CI 處理（tag push 觸發 GitHub Actions）

set -euo pipefail

RESULT_ENV="/tmp/bump_version_result.env"
if [ ! -f "$RESULT_ENV" ]; then
  echo "[FAIL] 找不到 $RESULT_ENV，請先執行 bump.sh" >&2
  exit 1
fi
source "$RESULT_ENV"

TAG="v${TAG_VERSION}"

echo "[OK] Flutter platform hook：等待 GitHub Actions 接收 tag push..."
sleep 5

RUN_INFO=$(gh run list --limit 1 --branch "$TAG" --json databaseId,name,url \
  --jq 'if length == 0 then "" else .[0] | [.databaseId, .name, .url] | @tsv end' 2>/dev/null || true)

if [ -z "$RUN_INFO" ]; then
  echo "[WARN] 找不到對應 $TAG 的 GitHub Actions workflow run"
  echo "      可能原因："
  echo "        1. CI workflow 尚未接收到 tag（稍後再確認：gh run list）"
  echo "        2. 專案尚未設定監聽 tag push 的 workflow"
  echo "           參考 references/flutter-ci-testflight.md 建立 workflow"
  exit 0
fi

RUN_ID=$(echo "$RUN_INFO" | cut -f1)
RUN_NAME=$(echo "$RUN_INFO" | cut -f2)
RUN_URL=$(echo "$RUN_INFO" | cut -f3)

echo "[OK] GitHub Actions workflow 已觸發"
echo "      Workflow : $RUN_NAME"
echo "      Run URL  : $RUN_URL"
echo ""
echo "TestFlight 上傳由 CI 自動處理（約 10-20 分鐘）"
echo "完成後可至："
echo "  - GitHub Actions : $RUN_URL"
echo "  - App Store Connect : https://appstoreconnect.apple.com/apps"
echo ""
echo "若需即時追蹤建置進度："
echo "  gh run watch $RUN_ID"

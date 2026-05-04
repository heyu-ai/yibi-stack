#!/usr/bin/env bash
# bump.sh — 通用 project-level 版本 bump 腳本
# 用法：bump.sh [patch|minor|major]
# 自動偵測 Flutter/Python/Node.js/Go 並更新對應版本檔

set -euo pipefail

BUMP_TYPE="${1:-patch}"

case "$BUMP_TYPE" in
  patch|minor|major) ;;
  *) echo "[FAIL] bump type 必須是 patch、minor 或 major" >&2; exit 1 ;;
esac

# ---------- 偵測專案類型 ----------

detect_project() {
  if [ -f pubspec.yaml ]; then
    echo "flutter"
  elif [ -f pyproject.toml ] && grep -q '^version = "' pyproject.toml; then
    echo "python"
  elif [ -f package.json ]; then
    echo "nodejs"
  elif [ -f go.mod ]; then
    echo "go"
  else
    echo "unknown"
  fi
}

# ---------- semver 計算 ----------

bump_semver() {
  local version="$1"
  local type="$2"
  local major minor patch
  major=$(echo "$version" | cut -d. -f1)
  minor=$(echo "$version" | cut -d. -f2)
  patch=$(echo "$version" | cut -d. -f3 | cut -d+ -f1)

  if ! echo "$major.$minor.$patch" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "[FAIL] 無法解析版本號：$version" >&2
    exit 1
  fi

  case "$type" in
    major) major=$((major + 1)); minor=0; patch=0 ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    patch) patch=$((patch + 1)) ;;
  esac

  echo "${major}.${minor}.${patch}"
}

# ---------- sed 替換並驗證 ----------

sed_replace_and_verify() {
  local file="$1"
  local pattern="$2"
  local replacement="$3"

  cp "$file" "${file}.bak"
  sed -i.bak2 "s/${pattern}/${replacement}/" "$file"
  rm -f "${file}.bak2"

  if diff -q "$file" "${file}.bak" > /dev/null 2>&1; then
    echo "[FAIL] $file 版本欄位未更新，請確認格式正確" >&2
    mv "${file}.bak" "$file"
    exit 1
  fi
  rm -f "${file}.bak"
}

# ---------- 各語言 bump 實作 ----------

bump_flutter() {
  local match_count
  match_count=$(grep -c '^version:' pubspec.yaml || true)
  if [ "$match_count" -ne 1 ]; then
    echo "[FAIL] pubspec.yaml 中找到 $match_count 個 version 欄位（期望恰好 1 個）" >&2
    exit 1
  fi

  local full_version
  full_version=$(grep -m 1 '^version:' pubspec.yaml | sed 's/^version:[[:space:]]*//')

  if [ -z "$full_version" ]; then
    echo "[FAIL] pubspec.yaml 中找不到版本號" >&2
    exit 1
  fi

  local new_version
  if echo "$full_version" | grep -q '+'; then
    local semver build_num
    semver=$(echo "$full_version" | cut -d+ -f1)
    build_num=$(echo "$full_version" | cut -d+ -f2)
    semver=$(bump_semver "$semver" "$BUMP_TYPE")
    new_version="${semver}+$((build_num + 1))"
  else
    new_version=$(bump_semver "$full_version" "$BUMP_TYPE")
  fi

  sed_replace_and_verify pubspec.yaml "^version:.*" "version: ${new_version}"
  echo "$new_version"
}

bump_python() {
  local current_version
  current_version=$(grep '^version = "' pyproject.toml | head -1 | sed 's/^version = "//; s/".*//')

  if [ -z "$current_version" ]; then
    echo "[FAIL] pyproject.toml 中找不到 version 欄位（格式必須為 version = \"x.y.z\"）" >&2
    exit 1
  fi

  local new_version
  new_version=$(bump_semver "$current_version" "$BUMP_TYPE")

  python3 - "$new_version" << 'PYEOF'
import sys, re
new_ver = sys.argv[1]
content = open("pyproject.toml", encoding="utf-8").read()
result = re.sub(r'^version = "[^"]*"', f'version = "{new_ver}"', content, count=1, flags=re.MULTILINE)
if result == content:
    print(f"[FAIL] pyproject.toml 版本欄位未更新", file=sys.stderr)
    sys.exit(1)
open("pyproject.toml", "w", encoding="utf-8").write(result)
PYEOF
  echo "$new_version"
}

bump_nodejs() {
  local current_version
  current_version=$(python3 -c "import json,sys; d=json.load(open('package.json')); print(d.get('version',''))" 2>/dev/null || true)

  if [ -z "$current_version" ]; then
    echo "[FAIL] package.json 中找不到 version 欄位" >&2
    exit 1
  fi

  local new_version
  new_version=$(bump_semver "$current_version" "$BUMP_TYPE")

  python3 - "$new_version" << 'PYEOF'
import json, sys
new_ver = sys.argv[1]
path = "package.json"
data = json.loads(open(path).read())
data["version"] = new_ver
open(path, "w").write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PYEOF

  echo "$new_version"
}

bump_go() {
  local latest_tag
  latest_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
  local current_version="${latest_tag#v}"

  local new_version
  new_version=$(bump_semver "$current_version" "$BUMP_TYPE")

  if [ "$BUMP_TYPE" = "major" ] && [ "$(echo "$new_version" | cut -d. -f1)" -ge 2 ]; then
    echo "[WARN] Go major version bump: 需手動更新 go.mod 的 module 行（加 /v$(echo "$new_version" | cut -d. -f1) 後綴）" >&2
  fi

  echo "[WARN] Go 版本由 git tag 管理，請在此腳本完成後執行：git tag v${new_version}" >&2
  echo "$new_version"
}

# ---------- 主流程 ----------

PROJECT_TYPE=$(detect_project)
echo "[OK] 偵測到專案類型：$PROJECT_TYPE"

case "$PROJECT_TYPE" in
  flutter)
    NEW_VERSION=$(bump_flutter)
    VERSION_FILE="pubspec.yaml"
    ;;
  python)
    NEW_VERSION=$(bump_python)
    VERSION_FILE="pyproject.toml"
    ;;
  nodejs)
    NEW_VERSION=$(bump_nodejs)
    VERSION_FILE="package.json"
    # 提示 package-lock.json
    if [ -f "package-lock.json" ]; then
      echo "[WARN] 偵測到 package-lock.json，請執行：npm install --package-lock-only" >&2
    fi
    ;;
  go)
    NEW_VERSION=$(bump_go)
    VERSION_FILE="git-tag-only"
    ;;
  unknown)
    echo "[FAIL] 無法偵測專案類型（找不到 pubspec.yaml / pyproject.toml / package.json / go.mod）" >&2
    exit 1
    ;;
esac

echo "[OK] $BUMP_TYPE bump: v${NEW_VERSION}"
echo "[OK] 版本檔：$VERSION_FILE"

# 結果輸出（供 agent 讀取）
# Flutter 的 TAG_VERSION 去掉 +build，其他語言與 BUMP_VERSION 相同
TAG_VERSION=$(echo "$NEW_VERSION" | cut -d+ -f1)

RESULT_ENV="/tmp/bump_version_result.env"
printf 'BUMP_VERSION=%s\nTAG_VERSION=%s\nVERSION_FILE=%s\n' "$NEW_VERSION" "$TAG_VERSION" "$VERSION_FILE" > "$RESULT_ENV"
echo "[OK] 結果寫入：$RESULT_ENV"

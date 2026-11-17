#!/usr/bin/env bash
# bump.sh — 通用 project-level 版本 bump 腳本
# 用法：bump.sh [--dir <path>] [patch|minor|major]
# 自動偵測 Flutter/Python/Node.js/Go 並更新對應版本檔
#
# --dir：monorepo 的元件目錄（例：backend、story-lab）。只升該目錄的版號檔，路徑必須在
#        repo 內。不帶 --dir 時處理目前目錄，行為與舊版相同（scripts/release-full.sh 依賴此點）：
#        不 cd、VERSION_FILE 維持相對於目前目錄、COMPONENT_DIR 為 "."。
# BUMP_RESULT_ENV：結果檔路徑，預設 /tmp/bump_version_result.env；相對路徑相對於執行時的目錄。
#        只有 bump.sh 認得此變數，gates.sh / release.sh / platforms 仍讀 /tmp/bump_version_result.env。
# Go 專案的版本只存在 git tag，無法依元件分開，所以搭配非 "." 的 --dir 會直接 [FAIL]。

set -euo pipefail
# 清掉 CDPATH：否則 cd 會先搜尋 CDPATH，命中時多印一行目的地到 stdout（見 rule 17，同 scripts/release-full.sh）
export CDPATH=

BUMP_TYPE=""
COMPONENT_DIR="."
DIR_GIVEN=0
INVOKE_DIR=$(pwd -P)

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        echo "[FAIL] --dir 需要一個目錄參數（用法：bump.sh [--dir <path>] [patch|minor|major]）" >&2
        exit 1
      fi
      if [ "$DIR_GIVEN" -eq 1 ]; then
        echo "[FAIL] --dir 只能指定一次" >&2
        exit 1
      fi
      DIR_GIVEN=1
      COMPONENT_DIR="$2"
      shift 2
      ;;
    --dir=*)
      echo "[FAIL] --dir 與路徑之間要用空格，不是等號（用法：bump.sh --dir <path> [patch|minor|major]）" >&2
      exit 1
      ;;
    patch|minor|major)
      if [ -n "$BUMP_TYPE" ]; then
        echo "[FAIL] bump type 只能指定一次（已有：${BUMP_TYPE}，又收到：${1}）" >&2
        exit 1
      fi
      BUMP_TYPE="$1"
      shift
      ;;
    *)
      echo "[FAIL] bump type 必須是 patch、minor 或 major（收到：${1}）" >&2
      exit 1
      ;;
  esac
done

BUMP_TYPE="${BUMP_TYPE:-patch}"

# 結果檔：相對路徑在 cd 之前轉成絕對路徑；改任何版號檔之前先驗證可寫，並清掉過期結果檔，
# 讓失敗的執行不會留下上一次的結果。
RESULT_ENV="${BUMP_RESULT_ENV:-/tmp/bump_version_result.env}"
case "$RESULT_ENV" in
  /*) ;;
  *) RESULT_ENV="${INVOKE_DIR}/${RESULT_ENV}" ;;
esac
if ! ( : >> "$RESULT_ENV" ) 2>/dev/null; then
  echo "[FAIL] 結果檔無法寫入：${RESULT_ENV}（尚未修改任何版號檔）" >&2
  exit 1
fi
rm -f "$RESULT_ENV"

REPO_ROOT_PATH=$(git rev-parse --show-toplevel)
REL_DIR="."

if [ "$DIR_GIVEN" -eq 1 ]; then
  if [ ! -d "$COMPONENT_DIR" ]; then
    echo "[FAIL] --dir 目錄不存在：$COMPONENT_DIR" >&2
    exit 1
  fi

  ROOT_REAL=$(cd "$REPO_ROOT_PATH" && pwd -P)
  if ! DIR_REAL=$(cd "$COMPONENT_DIR" && pwd -P); then
    echo "[FAIL] 無法進入 --dir 目錄：${COMPONENT_DIR}" >&2
    exit 1
  fi

  case "$DIR_REAL/" in
    "$ROOT_REAL"/*) ;;
    *)
      echo "[FAIL] --dir 不在 repo 內：${COMPONENT_DIR}（repo 根目錄：${ROOT_REAL}）" >&2
      exit 1
      ;;
  esac

  # 相對於 repo 根目錄的元件路徑；根目錄本身記為 "."
  REL_DIR="${DIR_REAL#"$ROOT_REAL"}"
  REL_DIR="${REL_DIR#/}"
  if [ -z "$REL_DIR" ]; then
    REL_DIR="."
  fi

  cd "$DIR_REAL"
fi

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

if [ "$PROJECT_TYPE" = "go" ] && [ "$REL_DIR" != "." ]; then
  echo "[FAIL] Go 專案的版本只存在 git tag，無法依元件目錄分開升版（--dir：${REL_DIR}）；請改用政策指定的指令或在 repo 根目錄手動打 tag" >&2
  exit 1
fi

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
# 輸出變數：BUMP_VERSION、TAG_VERSION、VERSION_FILE、PROJECT_TYPE、REPO_ROOT、COMPONENT_DIR
# VERSION_FILE 只有在帶 --dir 時才是相對於 repo 根目錄的路徑，不帶 --dir 時相對於目前目錄
# Flutter 的 TAG_VERSION 去掉 +build，其他語言與 BUMP_VERSION 相同
TAG_VERSION=$(echo "$NEW_VERSION" | cut -d+ -f1)

# Flutter 專案：若根目錄存在 VERSION 純文字檔（CI 讀此檔做 tag 驗證），同步更新
# 搜尋順序：當前目錄 → 上一層（pubspec.yaml 在 mobile/ 而 VERSION 在 repo root 的 monorepo 結構）
if [ "$PROJECT_TYPE" = "flutter" ]; then
  for _version_path in "VERSION" "../VERSION"; do
    if [ -f "$_version_path" ]; then
      echo "$TAG_VERSION" > "$_version_path"
      echo "[OK] 同步 VERSION 檔案：$_version_path → $TAG_VERSION"
      _version_display="$_version_path"
      if [ "$DIR_GIVEN" -eq 1 ] && [ "$REL_DIR" != "." ]; then
        # 帶 --dir 時，複合 VERSION_FILE 內每個路徑都改成 repo 根目錄相對
        if [ "$_version_path" = "../VERSION" ]; then
          _parent_rel=$(dirname "$REL_DIR")
          if [ "$_parent_rel" = "." ]; then
            _version_display="VERSION"
          else
            _version_display="${_parent_rel}/VERSION"
          fi
        else
          _version_display="${REL_DIR}/VERSION"
        fi
      fi
      VERSION_FILE="pubspec.yaml + ${_version_display}"
      break
    fi
  done
fi

if [ "$DIR_GIVEN" -eq 1 ] && [ "$REL_DIR" != "." ] && [ "$VERSION_FILE" != "git-tag-only" ]; then
  case "$VERSION_FILE" in
    "pubspec.yaml + "*) VERSION_FILE="${REL_DIR}/pubspec.yaml + ${VERSION_FILE#pubspec.yaml + }" ;;
    *) VERSION_FILE="${REL_DIR}/${VERSION_FILE}" ;;
  esac
fi

printf 'BUMP_VERSION=%q\nTAG_VERSION=%q\nVERSION_FILE=%q\nPROJECT_TYPE=%q\nREPO_ROOT=%q\nCOMPONENT_DIR=%q\n' "$NEW_VERSION" "$TAG_VERSION" "$VERSION_FILE" "$PROJECT_TYPE" "$REPO_ROOT_PATH" "$REL_DIR" > "$RESULT_ENV"
echo "[OK] 結果寫入：$RESULT_ENV"

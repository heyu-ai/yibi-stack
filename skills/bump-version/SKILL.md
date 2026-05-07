---
name: bump-version
type: know
scope: global
description: >
  Project-level 版本號 bump + CHANGELOG 生成 + git tag 發布流程。
  自動偵測 Flutter（pubspec.yaml）、Python（pyproject.toml）、Node.js（package.json）、Go（git tag only）。
  觸發情境：「bump version」「版本升級」「release」「發布」「tag」「CHANGELOG」
  「patch/minor/major」「pubspec version」「pyproject version」。
  附帶 commit-msg hook 安裝功能：「安裝 commit hook」「setup commit convention」「commit message 驗證」。
---

# bump-version

Project-level 版本 bump、CHANGELOG 生成、git tag 標準流程。
支援 Flutter / Python / Node.js / Go。

## 腳本位置

腳本住在 skill 目錄，`make install` 安裝後可直接呼叫（有 shebang，無需 `bash` 前綴）：

- `~/.claude/skills/bump-version/scripts/`（Claude Code 路徑，**以下範例均使用此路徑**）
- `~/.agents/skills/bump-version/scripts/`（agents 共用路徑，功能等價；若使用此路徑，將以下所有範例的 `~/.claude/skills/` 替換為 `~/.agents/skills/`）

若 `make install` 或 `make install-one SKILL=bump-version` 尚未執行，腳本不存在，需先安裝。

## 主流程：bump + release

### Step 1: 確認 bump 類型

向使用者確認或依 commit 分析決定 bump 類型：

| bump type | 適用情境 |
|-----------|---------|
| `patch`   | bug fix、文件修正、效能調整（不影響 API） |
| `minor`   | 新功能（向後相容） |
| `major`   | Breaking change（API 不相容） |

若有 git-cliff，可先分析 commit 再建議：

```bash
git-cliff --unreleased --bump 2>/dev/null | head -5
```

### Step 2: 執行版本 bump

```bash
~/.claude/skills/bump-version/scripts/bump.sh {{patch|minor|major}}
```

腳本輸出新版本到 `/tmp/bump_version_result.env`，讀取：

```bash
source /tmp/bump_version_result.env
echo "BUMP_VERSION=$BUMP_VERSION, TAG_VERSION=$TAG_VERSION, VERSION_FILE=$VERSION_FILE"
```

`BUMP_VERSION`：完整版本（Flutter 含 `+build`）；`TAG_VERSION`：純 semver（供 git tag 使用）。

**Go 專案**：腳本不修改任何檔案，會在 stderr 提示需手動執行 `git tag`。
版本偵測細節見 `references/project-types.md`。

### Step 3: 生成 CHANGELOG

```bash
~/.claude/skills/bump-version/scripts/changelog.sh "$TAG_VERSION"
```

工具優先序：git-cliff（有 cliff.toml 或 .cliff.toml） > git-cliff（preset） > git log fallback。
工具差異見 `references/changelog-tools.md`。

### Step 4: Commit + Tag + Push

```bash
git add -A
git commit -m "chore(release): v${TAG_VERSION}"
git tag "v${TAG_VERSION}"
git push
git push --tags
```

**Go 專案**：無版本檔修改，直接從 tag 步驟開始：

```bash
git tag "v${TAG_VERSION}"
git push --tags
```

> **Go major version 注意**：若 bump 到 v2 以上，必須在 tag 前手動更新 `go.mod` 的 module 行
> 加入 `/v2` 後綴（例：`module github.com/org/repo/v2`）。跳過此步驟會產生不符合 Go module
> 規範的 tag。詳見 `references/project-types.md`。

**Node.js 專案**：若有 `package-lock.json`，Step 2 後需更新：

```bash
npm install --package-lock-only
```

### Step 5: 報告

```text
=== Release 完成 ===
版本：v${BUMP_VERSION}
版本檔：${VERSION_FILE}
Tag：v${BUMP_VERSION}
CHANGELOG：已更新
```

---

## 附加功能：安裝 commit-msg hook

適用於想在專案強制 Conventional Commits 格式的情況。

### 安裝

```bash
~/.claude/skills/bump-version/scripts/init-commit-hook.sh
```

安裝後產生：

- `.git/hooks/commit-msg` — 驗證 hook（每次 git commit 自動執行）
- `.claude/hooks/commit-msg-parse.py` — YAML 設定解析器（hook 相依此檔）
- `.claude/commit-convention.yaml` — 設定檔（從 template 產生，可自訂）

### 設定

編輯 `.claude/commit-convention.yaml`：

```yaml
# 允許的 commit type（block list 格式）
types:
  - feat
  - fix
  - docs
  - chore

require_scope: false        # 是否強制填 scope
max_subject_length: 72      # subject 最大長度
ticket_pattern: ""          # Jira/GitHub ticket pattern（空=不驗證）
```

Jira 範例：`ticket_pattern: "(PROJ|MYTEAM)-[0-9]+"`

---

## 常見問題

| 問題 | 處理方式 |
|------|---------|
| `bump-version skill 未安裝` | `make install-one SKILL=bump-version`（在 ainization-skill repo 執行） |
| 無法偵測專案類型 | 確認根目錄有 pubspec.yaml / pyproject.toml / package.json / go.mod 其中之一 |
| Python 偵測失敗 | pyproject.toml 需含頂層 `version = "x.y.z"` 行（Poetry 需使用 PEP 621 格式） |
| Go major bump 後 module path 需更新 | 手動修改 `go.mod` 的 `module` 行，加 `/v2` 後綴 |
| git-cliff 格式與現有 CHANGELOG 不符 | 建立 `cliff.toml` 自訂格式，見 `references/changelog-tools.md` |
| commit hook 擋住 Merge commit | 正常，hook 已跳過 `Merge` 開頭的 commit |
| commit-convention.yaml 設定未生效 | 確認 `.claude/hooks/commit-msg-parse.py` 存在（重新執行 init-commit-hook.sh） |

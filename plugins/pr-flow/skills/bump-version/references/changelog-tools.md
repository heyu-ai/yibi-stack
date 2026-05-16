# Changelog 生成工具對照

## 優先序

```text
git-cliff（有 cliff.toml 或 .cliff.toml）> git-cliff（preset）> git log fallback
```

若 git-cliff 安裝但執行失敗（cliff.toml 格式錯誤等），自動 fallback 到 git log。

## git-cliff（推薦）

**偵測**：`command -v git-cliff`

**Config 偵測**：`cliff.toml` 或 `.cliff.toml`（二擇一，dotfile 也支援）

**有 `cliff.toml` 或 `.cliff.toml`**：直接使用專案設定：

```bash
git-cliff --tag "v${NEW_VERSION}" -o CHANGELOG.md
```

**無 cliff config**：使用 keepachangelog preset：

```bash
git-cliff --tag "v${NEW_VERSION}" --config keepachangelog -o CHANGELOG.md
```

**安裝**：

```bash
cargo install git-cliff       # Rust toolchain
brew install git-cliff        # macOS Homebrew
```

## git log fallback

不依賴任何外部工具，純 git 指令。

**範圍**：從上一個 tag 到 HEAD（若無 tag，從初始 commit 到 HEAD）

**過濾邏輯**：

- `feat:` / `feat(scope):` → Features 段落
- `fix:` / `fix(scope):` → Bug Fixes 段落
- `type!:` 格式 → Breaking Changes 段落
- 其他 commit（chore/docs/style...）略過，不進 CHANGELOG

**限制**：

- 不支援 `BREAKING CHANGE:` footer（只偵測 subject 的 `!` 語法）
- 無法像 git-cliff 那樣自訂格式

## cliff.toml 最小設定範本

若專案想使用 git-cliff 但無現成設定，可用此範本：

```toml
[changelog]
header = "# CHANGELOG\n"
body = """
{% for group, commits in commits | group_by(attribute="group") %}
### {{ group | striptags | trim | upper_first }}
{% for commit in commits %}
- {{ commit.message | upper_first }}\
{% endfor %}
{% endfor %}\n
"""
trim = true

[git]
conventional_commits = true
filter_unconventional = true
commit_preprocessors = []
commit_parsers = [
  { message = "^feat", group = "Features" },
  { message = "^fix", group = "Bug Fixes" },
  { message = "^docs", group = "Documentation" },
  { message = "^refactor", group = "Refactoring" },
  { message = "^perf", group = "Performance" },
  { skip = true },
]
```

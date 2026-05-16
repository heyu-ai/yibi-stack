# 各語言版本檔對照表

## Flutter

**版本檔**：`pubspec.yaml`

```yaml
version: 1.2.3+45  # semver+build_number（build_number 可省略）
version: 1.2.3     # 也接受無 build_number 的純 semver
```

**bump 規則**：

- semver 部分依 patch/minor/major 規則遞增
- 若有 build number，每次 bump 都 +1（與 bump type 無關）
- 若無 build number，只 bump semver（不自動加 `+1`）
- `major` bump：`1.2.3+45` → `2.0.0+46`
- `minor` bump：`1.2.3+45` → `1.3.0+46`
- `patch` bump：`1.2.3` → `1.2.4`

**tag 格式**：`v1.2.3`（只含 semver，不含 build number）

> 注意：`BUMP_VERSION` 環境變數為完整版本字串（含 `+build`），
> git tag 應使用 `git tag "v$(echo $BUMP_VERSION | cut -d+ -f1)"`。

## Python

**版本檔**：`pyproject.toml`

```toml
[project]
version = "1.2.3"
```

**偵測條件**：頂層必須有 `version = "x.y.z"` 格式的行（`^version = "`）。

**限制**：僅支援 PEP 621（`[project]`）格式。Poetry 專案若使用
`[tool.poetry]` 區段下的 `version`，需改用 PEP 621 格式或手動 bump。

**bump 規則**：標準 semver，精確替換 `^version = "..."` 行。

**tag 格式**：`v1.2.3`

## Node.js

**版本檔**：`package.json`

```json
{
  "version": "1.2.3"
}
```

**bump 規則**：透過 Python json 模組安全修改，不使用 sed（避免巢狀 key 污染）。

**注意**：若有 `package-lock.json`，需同步執行 `npm install --package-lock-only` 更新 lock 檔。

**tag 格式**：`v1.2.3`

## Go

**版本檔**：**無**（go.mod 只記 module path 和 go 版本，不記應用版本號）

**版本來源**：git tag

**bump 規則**：

1. 用 `git describe --tags --abbrev=0` 取最新 tag
2. 解析 tag 的 semver，bump 後產生新版本字串
3. 不修改任何檔案（由 SKILL.md Step 4 手動執行 `git tag`）

**tag 格式**：`v1.2.3`

**major version bump 特例**：Go modules 慣例在 major >= 2 時，module path 需加 `/v2`。
必須在執行 `git tag v2.0.0` **之前**手動更新 `go.mod`：

```text
module github.com/org/repo/v2
```

此 skill 不自動處理，跳過此步驟會產生不符合規範的 module tag。

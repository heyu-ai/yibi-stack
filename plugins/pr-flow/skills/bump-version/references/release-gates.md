# Release Gates 說明

Pre-release test gate 在推 tag 之前執行，確保程式碼品質。
失敗時中斷 release；緊急時可用 `--skip-gates` 略過。

## 執行方式

```bash
# 正常執行（必跑）
~/.claude/skills/bump-version/scripts/gates.sh

# 緊急略過（GitHub Release notes 會加警告）
~/.claude/skills/bump-version/scripts/gates.sh --skip-gates
```

## 各平台預設指令

| 平台 | 偵測依據 | 測試指令 |
|------|---------|---------|
| flutter | `pubspec.yaml` | `flutter analyze` + `flutter test` |
| python | `pyproject.toml` 含 `version = "..."` | `uv run pytest`（或 `pytest`） |
| nodejs | `package.json` | `npm test` |
| go | `go.mod` | `go test ./...` |

## 如何客製化

### 修改指令

各平台的 gate script 住在：

```text
~/.claude/skills/bump-version/scripts/gates/
├── flutter.sh
├── python.sh
├── nodejs.sh
└── go.sh
```

直接編輯對應檔案即可，例如在 `flutter.sh` 加上 integration test：

```bash
# gates/flutter.sh 加入 integration test
( cd "$FLUTTER_DIR" && flutter analyze && flutter test )
( cd "$FLUTTER_DIR" && flutter test integration_test/ )
```

### 新增平台 gate

1. 建立 `gates/<platform>.sh`（記得 `chmod +x`）
2. `gates.sh` 會依 `PROJECT_TYPE` 自動 dispatch

### 完全略過 gate

設定環境變數後執行：

```bash
SKIP_GATES=true ~/.claude/skills/bump-version/scripts/release.sh
```

或在呼叫 `gates.sh` 時加旗標（`release.sh` 會讀 `SKIP_GATES` 環境變數）。

## Flutter Gate 注意事項

- `flutter analyze` 會在任何 warning 時失敗（需確保程式碼無 lint 問題）
- `flutter test` 跑所有 `test/` 下的 unit + widget test
- Integration tests（`integration_test/`）預設不跑（需要模擬器，CI 上才執行）
- Monorepo 結構下若 Flutter app 在 `mobile/` 子目錄，gate 會自動偵測

## 為什麼強制執行 gate

- 避免帶有明顯 bug 的 tag 觸發 CI，浪費 CI minutes
- TestFlight 上傳後使用者才發現問題，回滾成本高
- `--skip-gates` 旗標留下可追蹤的 GitHub Release 警告記錄

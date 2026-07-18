# harness plugin

評估 Claude Code harness 工程就緒度的工具集。

## Skills

| Skill | 說明 |
|---|---|
| `harness-eval` | 8 維度 0-100 分 harness 就緒度評量；PASS/WARN/FAIL 清單；優先 TODO |
| `freeze` | 把編輯範圍鎖到指定目錄：PreToolUse hook 擋掉邊界外的 Edit/Write，防止 agent 順手改到不相關的檔案。未 arm 前 fail-open。改寫自 garrytan/gstack（MIT） |
| `unfreeze` | 清除 `/freeze` 的編輯邊界，恢復全目錄可編輯 |

## 安裝

```bash
make install   # harness-eval 包含於 global skill install
```

## 未來計畫

- `harness-fix`：自動修正 D3 deny list / D7 rule 分類
- `harness-track`：追蹤跨時間的分數變化

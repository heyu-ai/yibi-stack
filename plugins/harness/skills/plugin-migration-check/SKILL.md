---
name: plugin-migration-check
type: exec
scope: global
description: >
  偵測本機已安裝的 yibi-stack marketplace plugin 中，有哪些 pack 已改名／合併／拆分／移除
  但尚未跟著遷移，並印出精確的 claude plugin uninstall / install 修復指令。觸發情境：
  「plugin 用不了」「skill 不見了」「plugin 好像壞了」「pr-flow 找不到」「升級後 plugin 壞掉」
  「plugin migration check」「檢查我的 plugin 安裝」「剛拉了新版怎麼 skill 少了」。
---

# Plugin Migration Check

Claude Code 的 plugin 系統沒有 pack 改名／合併／拆分的遷移機制：一個 pack 從
`marketplace.json` 消失後，任何原本裝了它的使用者就只剩下**孤兒安裝**——
`installed_plugins.json` 裡的紀錄可能繼續留著（指向再也抓不到新內容的舊 cache），
新 pack 名稱不會被自動安裝。使用者感受到的症狀通常是「某個 skill 突然不見了」或
「plugin 好像壞掉了」，但看不出原因。

這個 skill 讀取本機安裝清單，比對本 repo 已知的遷移歷史，把「哪個舊 pack 對應到哪個
新 pack」翻譯成可以直接複製貼上的指令。

## 用法

```bash
python3 ~/.claude/skills/plugin-migration-check/scripts/check_migration.py
```

或若透過 plugin cache 安裝：`claude plugin install harness@yibi-stack` 後，路徑會在
plugin 自己的 cache 目錄下，直接呼叫本檔同目錄的 `scripts/check_migration.py` 即可。

## 輸出範例

```text
=== yibi-stack plugin migration check ===

[stale] <OLD_PACK>@yibi-stack（目前安裝版本 X.Y.Z）已改名/合併，建議執行：
    claude plugin uninstall <OLD_PACK>@yibi-stack
    claude plugin install <NEW_PACK>@yibi-stack

[removed] <RETIRED_PACK>@yibi-stack（目前安裝版本 X.Y.Z）已移除，無替代方案：
    claude plugin uninstall <RETIRED_PACK>@yibi-stack

=== 摘要 ===
2 個孤兒安裝需要處理，3 個正常
```

**不會自動執行任何 `claude plugin` 指令**——只印出建議，交由使用者自行決定並執行。

## 已知限制

- **只能偵測「仍留有安裝紀錄」的孤兒**。若 `installed_plugins.json` 裡的舊 pack 紀錄
  已經被完全清除（不留痕跡），這個工具無法回推「使用者曾經裝過它」，因此也無法建議
  對應的新 pack。這是本工具唯一的資料來源限制——它讀的是「現在還看得到什麼」，不是
  「歷史上裝過什麼」。
- **遷移歷史（`MIGRATION_MAP`）是手動維護的常數**，不會自動從 git history 推導。每次
  本 repo 的 pack 進行 rename / split / merge / delete，都必須同步更新
  `scripts/check_migration.py` 裡的 `MIGRATION_MAP` 與 `CURRENT_PACKS_FALLBACK`，
  否則這個工具本身也會對新的遷移視而不見。
- **只檢查 pack 層級的存在性，不驗證 hook 是否仍在生效**。例如 `bash-hygiene` 併入
  `harness` 之後，即使成功改裝 `harness@yibi-stack`，仍建議依 `plugins/harness/README.md`
  的 Upgrade note 額外跑一次「故意違反 AP2，確認被擋下」的正向對照，才算真的裝好。

## FAQ

| 問題 | 處理方式 |
|------|---------|
| 執行後說「未安裝任何 yibi-stack plugin」但我明明有裝 | 確認 `~/.claude/plugins/installed_plugins.json` 確實存在且可讀；若你是透過 `make install`（symlink 而非 `claude plugin install`）取得 skill，本工具偵測不到，因為那條路徑不寫入 `installed_plugins.json` |
| 印出 `[WARN] ... 找不到已知的遷移路徑` | 代表這個 pack 名稱不在 `MIGRATION_MAP` 裡——去 `.claude-plugin/marketplace.json` 確認目前真正的 pack 清單，或回報 issue 讓維護者更新對照表 |
| 印出 `[WARN] 讀不到本機 marketplace 快取` | 代表 `~/.claude/plugins/marketplaces/yibi-stack/.claude-plugin/marketplace.json` 不存在或格式錯誤，工具改用內建靜態清單（可能不是最新狀態）；執行 `claude plugin marketplace add heyu-ai/yibi-stack` 重新註冊一次即可修正 |
| 建議的 install 指令跑了之後 skill 還是找不到 | 目標 pack 的版本可能也需要刷新——`claude plugin update` 一次，或確認 marketplace 的 `autoUpdate` 設定 |

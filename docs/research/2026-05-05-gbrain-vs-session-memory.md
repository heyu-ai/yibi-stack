# GBrain vs Session-Memory（SQLite + JSONL）優缺點分析

**日期**：2026-05-05
**背景**：評估是否把 `tasks/session_memory/` 的儲存層從 SQLite + JSONL 遷移至 gbrain。
**結論**：handover 短期保持現況（70 筆）；但 insights.jsonl 已有 3,801 筆，insight 搜尋是更迫切的遷移動機。

---

## 現況盤點

```text
handovers:         70 筆（2026-04-12 ~ 05-05，約 23 天，≈ 3 筆/天）
insights.jsonl:  3,801 筆（~/.agents/insight/insights.jsonl）
session-recap.jsonl: 不存在（~/.agents/recap/session-recap.jsonl 尚未建立）
```

---

## 架構速比

| 面向 | 現況（SQLite + JSONL） | gbrain |
|---|---|---|
| 儲存後端 | `~/.agents/handover/handover.db` + `.jsonl` 鏡像；insight/recap/debug 純 JSONL | `~/.gbrain/brain.pglite`（local）或 Supabase Postgres |
| 資料單元 | 2 張 SQL table：`handovers`（22 欄）、`handover_events`（10 欄） | Page（title + tags + markdown body）+ chunks + embeddings + links |
| 查詢介面 | Click CLI + 同 monorepo Python import | `gbrain` Bun binary CLI；`gbrain serve` MCP stdio server |
| 搜尋 | `LIKE` 5 個欄位 OR；無 FTS、無 ranking、無向量 | `gbrain search`（關鍵字 + score）/ `gbrain query`（向量 hybrid）|
| 跨機器同步 | Syncthing + `.stignore`；無合併演算法 | 私有 git repo + JSONL sort-and-dedup merge driver + markdown union driver |
| MCP 整合 | 無 | `gbrain serve`，單行 `claude mcp add` 接入 |
| 代碼擁有 | 自家 ~3,140 行 Python，可任意改 schema | 第三方 binary，schema 不公開，契約是 CLI 介面 |
| 額外依賴 | uv + Python | Bun + git + jq + curl；Supabase 路徑需 PAT；gitleaks 用於 secret scan |

---

## gbrain 帶來的能力（現況沒有的）

1. **向量/語意搜尋**：`gbrain search` 回傳 similarity score；現況只有 LIKE。
2. **MCP server**：一行接入 Claude Code，別的 agent 也能查 handover；現況無對外 surface。
3. **真正的跨機器衝突合併**：git merge driver 自動處理；現況衝突靠人工。
4. **跨 entity 關聯**：`links` 欄位 + entity stub page；現況 lesson → handover 連結靠字串配對。
5. **per-skill 自動 context 注入**：`{{GBRAIN_CONTEXT_LOAD}}` resolver；現況 `/handover-back` 純手動。

---

## 現況比 gbrain 強的地方（遷移會丟掉的）

1. **結構化 metric / event log**：`handover_events` + `aggregate_success_counts()` 支撐 auto-handover 三層防護成功率追蹤；gbrain 沒有事件流模型。
2. **Layer 2 結構化欄位**：`device / agent_type / subscription_account / branch / project` 是 SQL 欄位可直接 `WHERE` 過濾；gbrain 全部降格為 tag 字串。
3. **四層 account fallback + 三家 adapter**：Claude / Codex / Gemini 帳號各自偵測；gbrain 不分帳號。
4. **handover 結構化六元組**：`completed / decisions / blocked / next_priorities / lessons_learned / attempted_approaches` 各自是 JSON array，
   供 `learn` skill 三源統一查詢；`daily-ai-footprint` 透過 runtime 路徑讀取 `~/.agents/insight/insights.jsonl`（非 Python import）；遷移 gbrain 後這些 reader 都要重寫。
5. **零外部依賴 + 完全離線**：uv + Python 而已；gbrain 加 Bun + 可選 Supabase + 可選 gitleaks。
6. **代碼可控**：schema 任意改；gbrain binary 升版風險不在自己手上（v1.15.1 才剛砍掉 HTTP ingest endpoint）。

---

## 三條路徑

### A. 全替換（不建議）

丟掉：handover_events 事件流、account adapter、結構化六元組、daily-ai-footprint JSONL reader、auto-handover metrics。
得到：向量搜尋 + MCP + 跨機器合併。

風險太高，且 gbrain v1.x 仍動盪（PGLite corruption 還在 manual recovery）。

### B. 保持現況（短期推薦）

繼續演化 SQLite。長期四個未解痛點：

1. 搜尋只有 LIKE，內容多後撈不出舊事
2. Syncthing 衝突沒合併
3. 別的 agent 無查詢通道
4. lesson / handover / insight 之間無關聯

### C. 混合：gbrain 當搜尋層，SQLite 仍是 source of truth（中期目標）

```text
write_handover() → SQLite + JSONL（不變）
               ↘  gbrain put_page（新 sink，throttle-aware fire-and-forget）

handover read   → SQLite（結構化查詢）
handover search → gbrain search（向量搜尋，稍後切換）
MCP 查詢        → gbrain serve（新通道）
```

成本：~100~200 行 Python `gbrain_sink.py` + 安裝 Bun/gbrain（一次性）。
可逆：gbrain 壞了 `gbrain import "$dir" --no-embed` 重建。

**Silent failure 風險**（實作時需處理）：

- Sink fire-and-forget 失敗時須至少 `warnings.warn`，否則 gbrain 靜默落後 SQLite 無法察覺
- `gbrain reconcile` 只做全量重 import，建議加 `--dry-run` 比對筆數以偵測 drift
- MCP 安裝後須驗證（`claude mcp list` + `gbrain serve --help`），binary 路徑錯誤會靜默失敗

---

## 決策觸發條件

重新評估路徑 C 的觸發點（任一條件成立）：

| 條件 | 門檻 |
|---|---|
| handover 記錄量 | > 150 筆 |
| 出現「我記得做過但 LIKE 查不到」的實際案例 | 發生一次即觸發 |
| 第二台機器有 session 需要查 handover | 出現跨機器需求 |
| 有 Codex / Gemini session 想查 handover | 出現跨 agent 查詢需求 |

目前（2026-05-05）handover 70 筆尚未到觸發點，但 insights.jsonl 已有 **3,801 筆**——insight 搜尋已是 LIKE 的弱點，可考慮優先把 insight 搜尋切到 gbrain。**預計 2026-07 重新評估。**

---

## 若決定走路徑 C，最小可行步驟

1. 跑 `setup-gbrain` skill，建 PGLite engine（先不接 Supabase）
2. 新增 `tasks/session_memory/gbrain_sink.py`（`sync_handover` / `sync_lesson` / `sync_debug_report`，全 fire-and-forget）
3. 在 `handover_service.write_handover()` / `lessons_service.*` / `debug_report_service.save_debug_report()` 末端掛 sink
4. 加 `python -m tasks.session_memory gbrain reconcile`（從 SQLite 全量重 import，disaster recovery）
5. 觀察 1~2 個月，確認 `gbrain search` 比 LIKE 好用後再把 read 路徑切換
6. 最後 `claude mcp add --scope user gbrain -- gbrain serve`（MCP 整合免費附贈）

**修改範圍**：

- 新增：`tasks/session_memory/gbrain_sink.py`、`tests/test_gbrain_sink.py`
- 修改：`handover_service.py`、`lessons_service.py`、`debug_report_service.py`、`cli.py`
- 修改：`skills/session-memory/SKILL.md`（記載 gbrain sink 為可選元件）

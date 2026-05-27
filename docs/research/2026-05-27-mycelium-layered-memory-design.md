# mycelium 分層記憶設計：從人類認知架構與 gbrain 原理借鏡

**日期**：2026-05-27
**背景**：mycelium 的演進弧為 handover → lesson learn → MemoryAgent。
本文以人類記憶模型為骨架，對照 gbrain 設計目標，識別 mycelium 的現況 gap 與借鏡點。
**前作參考**：`docs/research/2026-05-05-gbrain-vs-session-memory.md`（儲存層元件比較）；
本文補充該文未涵蓋的「認知架構分層 / dream consolidation / 多 bot 協作」視角。

---

## 1. 為什麼寫這份

mycelium 從第一天就不是「個人助理」——它設計成跨單人 session、跨機器、跨 bot（openab 多 agent 協作）的共用記憶層。
當我們看到 MemoryAgent 定義的 8 個能力（持久化、自主累積、記住偏好、跨 session 越準、高效儲存、高效檢索、遺忘過時資訊、context window 內召回關鍵記憶），
直覺反應是「再加幾個 table」——但這樣思考的框架是錯的。

這 8 個能力其實是**人類大腦記憶系統的工程化條列**。
真正的演進不是堆功能，而是先把認知架構想清楚：什麼是 working memory，什麼是 hot vs cold，什麼叫「遺忘」（是刪除還是降權？），以及記憶「寫進去」之後**何時、如何浮出來**。

`gbrain` 是同生態系（gstack）內最成熟的 memory backend。
但研究它的目的不只是看它做了什麼，更要看它**故意不做什麼**——
因為它定位是 infrastructure（不是 cognitive agent），所以把分層、遺忘、dream、retrieval timing 全部推給 caller。
這些「gbrain 故意不做的事」，就是 mycelium 必須自己承擔的演進責任。

前作（2026-05-05）做了儲存層元件的 1:1 比較，結論是保持現況（SQLite + JSONL）並等觸發條件。
本文不重複那些比較，聚焦在**認知架構分層**，以及因此衍生的 8 個獨立借鏡點（A–H）。

---

## 2. 人類記憶模型（設計骨架）

以認知科學的記憶分類為縱軸，對應 agent 的工程現實：

| 維度 | 人類 | agent 對應 | 失效時的體感 |
|---|---|---|---|
| **working memory** | 7±2 chunks；秒到分鐘 | 當前 context window 內的最近交班、in-flight todos | agent 在同一輪內忘了剛剛說過什麼 |
| **long-term memory** | 容量近無上限，需主動檢索才能取用 | SQLite handovers + lessons + insights.jsonl | agent 跨 session 從零開始 |
| **episodic** | 具體事件 + 時空脈絡（「上週二在辦公室討論的那件事」） | `HandoverRecord`（單一事件 + project + branch + timestamp） | 「我記得做過，但說不出在哪個 PR」 |
| **semantic** | 抽象事實 / 概念（「Python dict 是 mutable」） | `LessonRecord` type=pattern/architecture/tool | 反覆踩同樣的 pit，每次都要從頭想 |
| **procedural** | how-to / 肌肉記憶（騎腳踏車不需要想） | `LessonRecord` type=operational + skill scripts | 每次跑 skill 都要重學流程 |
| **hot memory** | 海馬迴近期活化、頻繁取用的記憶，召回快 | 最近 14 天 + access\_count 高 + user-stated trusted | 重要的事被埋在大量舊紀錄底層 |
| **cold memory** | 皮質長期儲存，需強力線索才能喚醒；**人類的「日記、相簿、雲端硬碟」是這層的外掛延伸** | 老舊、低使用率，但偶爾必要的 handover / lesson | 翻不到關鍵歷史脈絡 |
| **archival 外擴**（人類版日記 / 相簿） | 主動把記憶搬出大腦，存到不會自己衰減的介質，需要時可以翻 | 月度 markdown digest / git-backed memory snapshot | 「我記得寫過，但找不到那本日記」 |
| **forgetting curve** | Ebbinghaus 指數衰減；**「忘記」不等於「刪除」**，多半是降低召回優先級；重複喚醒會固化 | confidence × recency × access\_count 加權；低權重 demote 不是 delete | hot/cold 沒分層，要嘛全留導致雜訊，要嘛全丟導致失憶 |
| **recall ranking** | 線索 → 相似度 + 情境匹配，不是先進先出 | semantic search + project scope + recency 排序 | 召回到不相關記憶，更糟是召回到過時的 |
| **retrieval trigger**（**何時取出**） | 線索 cue / 情境匹配 / 主動回想 / 睡夢中浮現 / 別人提醒 | hook 主動 inject / 使用者明示 search / dream consolidation / 跨 bot 廣播 | 記憶有寫進去，但永遠不會自己浮出來 |

**關鍵觀察**：MemoryAgent 的 8 能力幾乎一對一映射到這張表——

- C1 持久化 = long-term
- C2 自主累積 = 海馬迴 encoding（不是人工觸發）
- C3 記住偏好 = semantic 中的 user-specific facts
- C4 跨 session 越準 = procedural strengthening（反覆使用固化）
- C5/C6 高效儲存 + 檢索 = hot/cold 分層 + recall ranking
- C7 遺忘過時 = **重新詮釋為「archival 搬移」而非真正刪除**（見借鏡點 D）
- C8 context window 召回 = working memory budget + retrieval trigger 機制

---

## 2.5 dream / consolidation：補一塊空白

人類睡眠時，大腦把白天進來的 episodic 碎片**重播、抽象化、強化或淘汰**，固化成 semantic / procedural 記憶。
Anthropic 在 Claude 的 long-conversation 處理中也用了類似機制（context 壓縮 + 跨輪摘要）。
對 agent 而言，這對應到一段**離線批次工作**：

| dream 對人類 | 對 agent 的工程對應 |
|---|---|
| 重播當天事件 | 掃過去 24h 的 handover + insight，找重複模式 |
| 抽象化為規則 | 把多筆 `pattern` 類 insight 合併成一條 `LessonRecord` |
| 強化頻繁啟動的連結 | `access_count` 高的 lesson 自動 promote 到 hot tier |
| 淘汰非必要細節 | 低權重 + 無人引用 → demote 到 cold，**但不 delete**，搬去 archival |
| 連結零散事件成劇情 | 找出跨 handover 的因果鏈，產出 retrospective digest |

**衍生建議（不在本研究實作範疇）**：研究文件完成後，獨立提案一個新 skill `/mycelium-dream`，做下列事的其中一個或全部：

1. **每日批次**：把 24h 內的 insight/handover 去重 → 合併 → 重新排序
2. **每週批次**：對過去 7 天的 lesson 跑 confidence/access\_count 校準，產出 weekly digest 推到 cold 層
3. **大改動觸發**：merge 進 main 後跑「post-merge consolidation」，把本 PR 相關的所有 handover/lesson 折疊成一條「milestone memory」

dream skill 是**橫切提案**，等借鏡點 A/D/H 落地後再啟動——沒有四層 tier 和 archival 機制，consolidation 沒有地方可以搬移素材。

---

## 2.6 bot-to-bot 記憶：跟人類記憶的本質差異

mycelium 的設計哲學是跨 Claude Code / Codex / Gemini / openab 多 agent，這跟「個人助理」型記憶 agent 有結構性差異：

| 維度 | 單人 / 單 bot 記憶 | mycelium 多 bot 場景 | 影響的設計借鏡 |
|---|---|---|---|
| **working memory 容量** | 單一 LLM context 限制 | 每個 bot 有自己的 context；可平行 | 不需把所有記憶塞進一個 context，應「按 bot 角色 inject」 |
| **記憶來源信任度** | 都是自己經歷的，信任度一致 | 同事 bot（Codex）的觀察 vs 自己親歷 | 需要 `source_bot` 欄位 + 跨 bot 信任策略（user-stated > 自己 > 其他 bot） |
| **記憶寫入時機** | 隨時可寫，無競爭 | 多 bot 平行寫可能 race / 重複 | 需要去重 + 衝突解決（誰寫的優先） |
| **記憶讀取時機** | 主動回想 + 線索觸發 | 別的 bot 接手時也要被「交班」 | handover 不只是「自己給未來的自己」，也是「自己給隔壁 bot」 |
| **dream / consolidation** | 個人睡眠，自己的大腦跑 | 集中式 batch（誰來跑？哪個 bot 有最終權威？） | dream skill 設計需決定：每個 bot 各跑一次、還是共用一個 orchestrator |
| **forgetting / archival** | 個人決定，自己的記憶 | 多 bot 共用 store，A bot demote 不代表 B bot 不需要 | demotion 預設是 global 但支援 per-bot override |
| **跨 bot 廣播** | 不存在 | 「我學到 X，全體請注意」 | MCP server 暴露不只是讀，還要支援 push notification 給其他 bot |

**對借鏡點的影響**：

- 借鏡點 D（archival/decay）：`access_count` 是 per-bot 還是 global aggregate？建議 global 加權、per-bot override
- 借鏡點 E（MCP server）：不是 gbrain `serve` 直譯，要加 cross-bot trust scoring
- 借鏡點 H（retrieval trigger）：push/pull 雙向設計，不只 pull

---

## 3. gbrain 設計原理與目標

以下從 6 份來源檔案萃取（詳見文末路徑清單）。

### 3.1 gbrain 故意做的事

1. **page-as-atom**：所有記憶單元都是「markdown body + YAML frontmatter」，slug 為主鍵。故意不強制分類型，type 只是 free-form tag——給 caller 完全自由的 schema 決定權。
2. **embedding-as-recall**：所有 page 自動算 embedding（Voyage `voyage-code-3` 1024 維 / OpenAI fallback），檢索預設 hybrid（vector similarity + BM25 fallback）。
3. **MCP-as-protocol**：`gbrain serve` 暴露 `mcp__gbrain__search`、`mcp__gbrain__query`、`mcp__gbrain__get_page`——讓任何 LLM agent（不只 Claude Code）能直接查同一個 store。
4. **federation 而非單一 store**：`sources add --federated`、`.gbrain-source` worktree pin（kubectl context 模式）——每個 worktree、每個 repo、`~/.gstack/` brain 都是獨立 source，query 預設跨 source 排序。
5. **split-engine（v1.34+）**：腦查詢可走 remote-MCP，code symbol 查詢留在 local PGLite——團隊共享 brain + 個人 code 隱私分離。
6. **symbol-aware code surface**：`code-def` / `code-refs` / `code-callers` / `code-callees` 用 tree-sitter（非 LSP）建 call graph，與 embedding 平行——程式碼結構查詢不靠 semantic。

**一句話定位**：「embedded semantic document store with MCP surface and symbol code index」——
它是 long-term memory + recall 的 backend，**故意把分層、遺忘、自主累積、dream、retrieval timing、bot trust 全推給 caller**，
因為它定位是 infrastructure，不是 cognitive agent。

### 3.2 gbrain 故意不做的事（mycelium 的演進空間）

| 不做的事 | 對應的 mycelium 演進責任 |
|---|---|
| 無 TTL / staleness / GC：page 永久存活到 `gbrain delete` | 借鏡點 D：archival 降權搬移機制（demote 不 delete） |
| 無 versioning：同 slug 蓋寫，舊版只在 git history | mycelium 保持 append-only event stream（反例 §6） |
| 無自動 ingestion：必須 explicit `gbrain put` | 借鏡點 G：三層 input trigger（Stop hook / PreCompact / agent 主動） |
| 無 typed schema for preference：只有 free-form tags | mycelium 保持 LessonType 7 值 + trusted bit（反例 §6） |
| 無 reranker：排序純靠 vector + BM25 score | 借鏡點 B/D：effective\_weight ranker 加 access\_count + trust |
| 無 hot/cold 分層：所有 page 平等 | 借鏡點 A：four-tier（working / hot / cold / archival） |
| 無 forgetting / decay / archival：不做降權或搬移 | 借鏡點 D：archival 搬移機制 |
| 無 dream / consolidation：不做合併或摘要 | §2.5 衍生提案：`/mycelium-dream` |
| 無 retrieval trigger：純被動，caller 不問就沒有 | 借鏡點 H：push + pull 雙向 retrieval trigger |
| 無 working memory 概念：caller 自己決定 context 配額 | 借鏡點 F：token-budget recall |
| 無 bot-to-bot 信任策略：所有 source 平等 | 借鏡點 E：MCP server + source\_bot trust scoring |

---

## 4. mycelium 現況：以分層視角檢視

以人類記憶模型 + bot-to-bot 維度為縱軸，評估現有實作：

| 人類層 / bot 維度 | mycelium 現有 | 強度 | gap |
|---|---|---|---|
| working memory | 無顯式概念，靠 LLM context window 自己管 | ❌ 沒概念 | 不知道何時主動 inject「正在發生的事」 |
| long-term episodic | `handovers` table（22 欄）+ `handover_events`（10 欄事件流） | ✅ 強 | — |
| long-term semantic | `LessonRecord` type ∈ {pattern, architecture, tool, ...} | ✅ 強 | 沒 embedding；LIKE 召回隨量增長劣化 |
| long-term procedural | `LessonRecord` type=operational + skill scripts | ✅ 部分 | 沒「執行成功率」回饋；無法自動強化 |
| hot memory | 無顯式概念；`/handover-back --last 3` 硬截 | ⚠️ 隱含於 recency | 沒 access\_count、沒 trusted bit 影響排序 |
| cold memory | 無分層；全在同一 table | ⚠️ 缺 | 大量舊 handovers 拖慢 LIKE 查詢 |
| archival 外擴 | 無；JSONL mirror 是同份資料的鏡像，不是「淘汰後封存」 | ❌ 缺 | 想 demote 但不想刪的記憶無處可去 |
| forgetting / decay | 純 append，無衰減也無搬移 | ❌ 缺 | 過時 preference 不會自動降權 |
| recall ranking | LIKE on 5 欄 OR；無 ranking | ❌ 弱 | 召回靠運氣，量大會崩 |
| retrieval trigger | 純 pull（使用者下 `/handover-back`，agent 主動 search） | ⚠️ 部分 | 無 push（hook inject）；無 dream surface |
| ingestion 自動性 | insight Stop hook ✅；handover 仍要人工 `/handover` | ⚠️ 部分 | C2 自主累積有缺口 |
| cross-agent adapter | 跨 Claude/Codex/Gemini adapter ✅ | ✅ 強 | 但沒 MCP server 給其他 agent 查 |
| bot-to-bot 信任 | 4 種 LessonSource（observed/user-stated/inferred/cross-model） | ✅ 中 | 沒有 `source_bot` 欄位，跨 bot 取用時無法做信任加權 |
| dream / consolidation | 無 | ❌ 缺 | 3,801 條 insight 無人去重合併 |

**mycelium 相對於 gbrain 的優勢**（人類記憶分層視角下值得保留的）：

- **typed semantic memory**：`LessonType` 7 值——gbrain 只有 free-form tag，無法做類型過濾
- **user-stated 自動 trusted bit**：對應人類「親身經歷強過聽說」的記憶強度差異
- **event-stream metric**：`HandoverEvent` 10 欄是「記憶被使用 → 強化」回饋迴路的雛形，gbrain 完全沒有
- **cross-agent adapter**：已經是 bot-to-bot ready 的雛形，只需往「集中式多 bot 學習中樞」方向延伸

---

## 5. 借鏡點（核心交付物）

八個獨立可評估的借鏡點，每點標「人類 / bot 對應 / 借 gbrain 什麼 / 自己做什麼 / 規模 S/M/L」。

### 借鏡點 A：明確區分「working / hot / cold / archival」四層

- **人類對應**：working memory + 海馬迴 + 皮質 + 日記/相簿
- **bot 對應**：每個 bot 有獨立 working；hot/cold/archival 是多 bot 共用層
- **借 gbrain**：page-as-atom 的單元化思維——每筆記憶有獨立 slug 與 metadata，tier 只是 metadata 的一個欄位
- **自己做**：
  - `LessonRecord` 加 `tier: working | hot | cold | archival` 欄位
  - 由 `last_accessed_at + access_count + confidence` 自動 promotion/demotion（background job）
  - working 層：in-flight handover draft，24 小時 TTL
  - archival 層：monthly snapshot markdown，從主表移出但 path 寫入索引，任何 bot 仍可回查
- **規模**：M（schema migration + 一個 background promotion job）

### 借鏡點 B：semantic recall — hybrid vector + keyword

- **人類對應**：海馬迴的 cue-based retrieval（線索 + 相似度匹配）
- **bot 對應**：MCP server 暴露時，每個 bot 用同一個 ranker
- **借 gbrain**：hybrid vector + BM25 fallback 的設計目標（不是直接依賴 gbrain CLI）
- **自己做**：
  - SQLite FTS5 + `sqlite-vec` extension（零外部依賴）
  - 抽 `MemoryIndex` interface，等 gbrain 在更多裝置普及再加 adapter
- **規模**：L（新 module + 重 ingestion pipeline）
- **觸發條件**（沿用前作 doc）：handover > 150 筆，或「我記得做過但 LIKE 找不到」痛點出現

### 借鏡點 C：source-scoped 查詢與 project pin

- **人類對應**：「在哪個情境學到的」這個記憶屬性
- **bot 對應**：「在哪個 repo / 哪個 worktree 學到的」
- **借 gbrain**：`.gbrain-source` 的 kubectl context 模式（每個 worktree 有自己的查詢 scope）
- **自己做**：
  - 用 `~/.agents/_registry/projects.json` 自動 resolve `cwd → project`
  - handover read / lesson search 預設 scope 該 project；跨 project 查詢要 `--global`
- **規模**：S（CLI flag 預設值，registry 已存在）

### 借鏡點 D：archival（不是「forgetting」）——分層降權 + 搬移保留

- **人類對應**：Ebbinghaus 曲線下降，但日記/相簿讓「真正忘記的事仍可回查」——遺忘是降低召回優先級，不是刪除
- **bot 對應**：archival 必須是 global（不是 per-bot delete），任何 bot 都可以回查
- **借 gbrain**：無（這正是 gbrain 故意不做的）
- **自己做**：
  - `LessonRecord` 加 `last_accessed_at`、`access_count` 兩欄
  - 定義 `effective_weight = confidence × decay(now - last_accessed_at) × log(access_count + 1)`
  - `effective_weight` 低 → demote 到 cold tier（不再參與預設召回，但 `--include-cold` 可查）
  - cold tier 持續低權重 → demote 到 archival（搬到 `~/.agents/archive/YYYY-MM.md`，從主表移出，path 寫入索引）
  - `user_stated = True` 不衰減；被 dream skill 重新引用過的 → 重置 `access_count`
  - **四個 tier 都可查，差別只在「預設召回門檻」與「儲存介質」**
- **規模**：M（schema 加兩欄 + ranker function + background promotion job + archival export）

### 借鏡點 E：MCP server 對外暴露（含 bot-to-bot trust）

- **人類對應**：「把我學到的告訴同事」——跨 agent 共享
- **bot 對應**：Codex / Gemini / openab 子 agent 直接查 mycelium；mycelium 從「一人腦延伸」演進為「多 bot 學習中樞」
- **借 gbrain**：`gbrain serve` MCP stdio 設計
- **自己做**：
  - `mycelium serve` 暴露 `mycelium_search`、`mycelium_get_lesson`、`mycelium_save_preference`
  - 每筆寫入帶 `source_bot` 欄位（`claude` / `codex` / `gemini` / `openab-{role}`）
  - search ranker 加 `bot_trust_weight`：user-stated > 自己同 bot > 信任的其他 bot > 未知 bot
  - 預留 push API（給 dream skill 跨 bot 廣播用）
- **規模**：M（新 server module + Pydantic 轉 JSON-RPC + 信任表）

### 借鏡點 F：working memory 召回機制（context window budget）

- **人類對應**：working memory 容量上限（7±2 chunks）
- **bot 對應**：每個 bot context window 大小不同，budget 是 per-call 參數
- **借 gbrain**：無
- **自己做**：
  - `/handover-back` 不再硬截 `--last 3`，改 `--token-budget 2000`
  - 用 `effective_weight` ranker 撈，直到耗盡 budget
  - 可選 `--mode {episodic|semantic|procedural}` 過濾類型
- **規模**：M（ranker + tiktoken 估算）

### 借鏡點 G：自主累積經驗——三層 input trigger（input 側）

- **人類對應**：被動 encoding（看到就記）+ 主動 rehearsal（複習固化）
- **bot 對應**：hook 自動撈 + agent 自己標註 + 其他 bot push
- **借 gbrain**：無（gbrain 純 explicit put，input 全靠外部推）
- **自己做**：
  1. **Stop hook 自動撈 `★ Memory:` 區塊**（沿用 `insight_hook.py` 模式）→ working 層
  2. **PreCompact hook** 在 context 將滿時強制摘要 → hot 層
  3. **agent 主動 `mycelium memory save`** 讓 LLM 自己標記「這條值得記」→ 帶 `source=inferred`
- **規模**：M（兩個 hook + 一個 CLI 子命令）

### 借鏡點 H（新）：retrieval trigger——何時、如何把記憶取出（output 側）

- **人類對應**：cue 觸發 / 別人提醒 / 睡夢中浮現 / 主動回想——記憶不只等你來問，它會自己出現
- **bot 對應**：現有設計重 input（G）輕 output；input/output 必須對稱，否則記憶寫進去出不來
- **借 gbrain**：無（gbrain 完全被動，不會主動浮出任何記憶）
- **自己做**（五種 trigger pattern）：
  1. **Pull（已有）**：使用者下 `/handover-back`、agent 主動 search
  2. **Push by hook（新）**：SessionStart hook 偵測 `cwd` → 自動 inject 該 project 最近 3 條 hot lesson + last handover 摘要到 system prompt
  3. **Push by event（新）**：PreToolUse hook 偵測「正要執行 `git push`」→ 自動撈該 repo 的 `pitfall` 類 lesson 提醒
  4. **Dream surface（新）**：dream skill 跑完 consolidation，產出「本週你做過 / 學到 / 該注意」digest，下次 session 開頭主動 display
  5. **Cross-bot broadcast（新）**：MCP server 加 `mycelium_subscribe`，bot A 寫入高 confidence preference 時，bot B 下次 session 開頭收到 notification
- **input/output 對稱原則**：每加一個 input trigger（G），就應該配一個 output trigger（H）；否則記憶寫進去但永遠不會浮出來
- **規模**：M（SessionStart/PreToolUse hook + subscribe API）

---

## 6. 不借的反例（保留 mycelium 既有優勢）

| 不借的 gbrain 設計 | 原因 |
|---|---|
| **page 同 slug 蓋寫** | mycelium `handover_events` 事件流（10 欄）支撐 auto-handover 三層防護成功率追蹤，必須保持 append-only |
| **flat type tag** | mycelium typed `LessonType` 7 值（特別是 `preference`）+ user-stated trusted bit 是 C3「記住偏好」能力的核心，比 gbrain 強，要保留 |
| **5MB / file 限制** | mycelium 單筆 handover 通常 < 50KB，限制沒有意義 |
| **explicit-only ingestion** | mycelium Stop hook 路徑已驗證可行（3,801 條 insight），要再擴充而非退回純手動 |
| **無 bot 區分** | gbrain 所有 source 平等；mycelium 必須帶 `source_bot` 才能做跨 bot 信任加權 |
| **完全被動 retrieval** | mycelium 已有 hook 基礎設施，retrieval trigger 一定要有 push 模式（借鏡點 H） |

---

## 7. 演進次序建議

按「對 MemoryAgent 8 能力的補強密度」與「改動規模」排序。本研究不涉及實作，僅提供排序依據。

| 階段 | 借鏡點 | 補強的 MemoryAgent 能力 | 改動規模 |
|---|---|---|---|
| **第一階段**（先做） | C 專案 scope + G 三層 input trigger + H Pull 與 SessionStart push | C2 C3 C4 C8 | S + M + M |
| **第二階段** | A 四層 tier + D archival/decay | C7 | M + M |
| **第三階段** | F context budget recall + H 其餘 push 模式 | C8 | M + M |
| **第四階段** | B semantic recall + E MCP server（含 bot trust） | C6 C4 | L + M |
| **獨立提案** | dream / consolidation skill | C7 的長期化 | M（獨立 skill） |

**說明**：

- 第一階段把 C2/C3/C4 補強到接近 MemoryAgent 定義；**H 的 Pull + SessionStart inject 是低成本高回報**，應與 G 同期做（input/output 對稱原則）
- 第二階段才碰分層與 archival：D 不是「刪除」，是「搬移到日記」
- 第四階段（vector + MCP）等觸發條件（handover > 150，或「LIKE 找不到」實際痛點）再啟動，沿用前作 doc 結論
- dream skill 等 A/D/H 落地後才有素材可以 consolidate；建議用 `/mycelium-dream` 子命令 + 每週 launchd / cron

---

## 8. 風險與決策點

| 風險 | 說明 | 建議 |
|---|---|---|
| **gbrain 本機未安裝** | 這台 Mac 找不到 `gbrain` binary 與 `~/.gbrain/`（可能在另一台機器）| 借鏡點 B 的實作不能 hard depend gbrain；必須有 SQLite FTS5 fallback |
| **schema 變更需走 Spectra change** | mycelium 已 merge 到 main（PR #93），任何 schema migration 需正式提案 | 借鏡點 A/D/G 都涉及 schema，先用 `/spectra-propose` 走流程 |
| **觸發條件未達** | 前作 doc 觸發條件：handover > 150（目前 70）、insight 搜尋痛點 | 借鏡點 B 不急；第一/二/三階段可先做，不依賴 B |
| **bot-to-bot trust 模型沒前例** | gbrain 沒做；學界無共識 | 借鏡點 H 的 cross-bot broadcast 最後做；先做 SessionStart inject 驗證效果 |
| **dream skill 設計風險** | consolidation 太保守 = 沒效果；太激進 = 丟掉使用者需要的細節 | 第一版只做「合併重複 + 重新排序」，不做「丟棄」；任何 demote 都進 archival 不 delete |
| **working 層 hook 觸發時機** | Stop hook 是 session 結束才跑；working 層的 24h TTL draft 需要 SessionStart / Periodic hook | 借鏡點 A 的 working tier 設計時，要決定 hook 觸發點 |

---

## 關鍵引用檔案

**既有 mycelium**：

- `tasks/mycelium/models.py:29-355`（LessonRecord、HandoverRecord、HandoverEvent schema）
- `plugins/growth/skills/mycelium/SKILL.md`（umbrella skill；含 cross-agent / cross-account / cross-machine 設計哲學）
- `docs/research/2026-05-05-gbrain-vs-session-memory.md`（前作：儲存層元件比較、觸發條件定義）

**gbrain 設計原理來源**：

- `~/.claude/skills/gstack/USING_GBRAIN_WITH_GSTACK.md`（385 行 operator manual）
- `~/.claude/skills/gstack/bin/gstack-gbrain-sync.ts`（1,103 行 orchestrator）
- `~/.claude/skills/gstack/bin/gstack-memory-ingest.ts`（1,816 行；定義 page-type enum）
- `~/.claude/skills/gstack/lib/gbrain-sources.ts`、`gbrain-local-status.ts`
- `~/.claude/skills/sync-gbrain/SKILL.md`、`~/.claude/skills/setup-gbrain/SKILL.md`

**dream / consolidation 概念參考**（概念類比，非深入引用）：

- 認知科學 sleep consolidation：McClelland 1995、Walker 2009（作為概念對齊）
- Anthropic Claude context management 相關公開文件（between-conversation consolidation 隱喻）

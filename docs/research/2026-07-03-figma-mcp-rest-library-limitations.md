# Figma MCP / REST API 讀取 Design Library 的限制與缺陷

> 日期:2026-07-03
> 背景:PR #180(figma-design-sync skill)mob review 後續。使用者質疑「skill 會不會漏
> Library 和元件」,經 3-model mob review + 雙來源查證(context7 讀 Figma 官方 OpenAPI
> spec `/figma/rest-api-spec` + agy/Gemini 引用 Figma 官方文件 URL)後的結論。
> 兩個獨立來源交叉一致,標註 VERIFIED 的項目皆可信。

## TL;DR

1. **Figma MCP 分 Desktop / Remote 兩種 variant,library 能力不同**——Desktop 完全沒有
   library 工具;Remote 有 `get_libraries` + `search_design_system`,但只能 **query(按名
   字搜尋)**,不能 **enumerate(倒出完整目錄)**。
2. **完整枚舉 library 元件/style 目錄只有 REST 能做**,需要另一套 PAT/OAuth token 與
   對應 scope。
3. **Variables(design tokens)REST API 是 Enterprise 方案限定**(還需 Full Design seat)
   ——非 Enterprise 團隊沒有任何「完整 token dump」的路徑,只能靠 MCP query 逐個查。
4. **Instance 反查來源 library 必須走 REST**:`remote: true` 的 instance,file JSON 不含
   來源 file_key,只能用 team-level components endpoint 以 component key 反查。

## 1. MCP 兩種 variant 的能力矩陣(VERIFIED)

| Variant | 工具 | Library 能力 |
|---------|------|-------------|
| **Desktop MCP server** | `get_design_context` / `get_variable_defs` / `get_metadata` / `get_screenshot` | **無任何 library 工具** |
| **Remote MCP server**(claude.ai 連接器 / plugin) | 上述之外加 **`get_libraries`** + **`search_design_system`** | 可 query、不可 full dump |

- `get_libraries(fileKey)`:列出 file 已訂閱的 libraries 與可加入的 libraries(含
  library key,org libraries 部分有分頁)。
- `search_design_system(query, fileKey, ...)`:以**文字查詢**跨 library 搜尋 components /
  variables / styles,可用 `includeLibraryKeys` 縮小範圍。**是搜尋,不是枚舉**——
  你必須知道要找什麼名字,無法「給我這個 library 的全部元件」。

**正確的邊界描述**:MCP 可以「按名字解析」library 元件,不能「一次倒出」整個目錄。

## 2. 其他 MCP 工具的既知缺陷(PR #180 mob review 驗證)

這些是 mob review 對照實際 tool schema 驗出、已在 PR #181 修掉 runbook 層的問題,
記在這裡供未來寫 Figma 相關 skill 的人避坑:

| 工具 | 缺陷 / 陷阱 |
|------|-------------|
| `get_metadata` | **不回傳 file 級 `version` / `lastModified`**(schema:「only includes node IDs, layer types, names, positions and sizes」)。任何「靠 file version 判斷設計是否變更」的設計都不可實作,只能做結構指紋比對。副作用:**純文案/顏色/樣式/token 變更對 metadata 完全不可見**(結構性盲點)。 |
| `get_variable_defs` | **node-scoped、`nodeId` 必填**(「requires a concrete node target」)。回傳的是該節點子樹用到的變數,不是 file 全量 token dump。 |
| `get_screenshot` | **不寫檔**——回傳短效 URL + curl 指令(或 `enableBase64Response: true` 附 base64),呼叫端必須自己下載落地。 |
| 工具 namespace | **前綴依連接器註冊名而變**(`mcp__figma__` / `mcp__plugin_figma_figma__` / …),skill 偵測「Figma 是否連接」必須比對工具 base name,不能寫死前綴。 |
| `get_metadata` 大檔 | 複雜 file 無 depth 限制/節點過濾時可能超過 payload 上限或 timeout;且**截斷的回應與「node 被刪除」不可區分**——增量 sync 若無完整性 gate 會把截斷誤判成大量刪除。 |

## 3. REST API:完整枚舉的路徑(VERIFIED)

以下 endpoint 兩個來源皆確認存在:

- **File 級**:`GET /v1/files/{key}/components`、`/component_sets`、`/styles`
- **Team 級**:`GET /v1/teams/{team_id}/components`、`/component_sets`、`/styles`
- **單一資產(by key)**:`GET /v1/components/{key}`、`/component_sets/{key}`、`/styles/{key}`

**Scope(已對照 OpenAPI spec)**:

| Scope | 用途 |
|-------|------|
| `library_content:read` | 讀 file 的 published components/styles |
| `team_library_content:read` | 讀 team 的 published components/styles |
| `library_assets:read` | 讀單一 published component/style 資料 |
| `file_content:read` | 讀 file 節點(instance 的 componentId 在這) |
| `file_variables:read` | 讀 variables——**Enterprise 限定** |
| `files:read` | **已於 2025-11 強制棄用**,新整合一律用細分 scope |

## 4. Variables(design tokens)的 Enterprise 閘門(VERIFIED)

- Endpoint:`GET /v1/files/{key}/variables/local` 與 `/variables/published`
  (寫入:`POST /v1/files/{key}/variables`)。
- **嚴格 Enterprise 方案限定,且需 Full Design seat**(agy 引官方 Variables REST API 文件;
  OpenAPI spec 的 scope 說明同樣標注「only available to members in Enterprise organizations」)。
- 實務結論:**非 Enterprise 團隊沒有「完整 published token 集」的取得路徑**。
  可用的替代:(a) Remote MCP `search_design_system` 按名字逐個查;
  (b) `get_variable_defs` 對掃描節點取「引用足跡」(figma-design-sync 目前的做法)。

## 5. Instance 反查來源 library 的機制(VERIFIED,agy 查證)

1. 讀 file(`GET /v1/files/{key}`,scope `file_content:read`),instance 節點帶 `componentId`。
2. `componentId` → file 頂層 `components` map → 取得該元件的 `key` + `remote` flag。
3. **`remote: true` 時,file JSON 不含來源 library 的 file_key**——
   必須用 `GET /v1/teams/{team_id}/components`(scope `team_library_content:read`)
   以 component key 反查來源。
4. 也就是說:「這顆按鈕是哪個 library 的」這個問題,**MCP 與單一 file 的 REST 都答不了,
   要 team-level REST 才能解**。

## 6. 對本 repo skill 的落地結論

| 需求 | 路徑 | 狀態 |
|------|------|------|
| 解析「被引用但未落地」的元件/token(常見情境) | Remote MCP:`get_libraries` + `search_design_system`(同連接器 OAuth,零 token 管理) | 今天可做;figma-design-sync 的元件完整性 gate 可升級為自動解析(PR #181 後續) |
| 完整枚舉 library 元件/style 目錄 | REST + `library_content:read` / `team_library_content:read` | 獨立 `figma-library-sync` skill 的範疇(要管 PAT,Fernet 加密進 `.env`) |
| 完整 published variables dump | REST + `file_variables:read` | **Enterprise 限定**,非 Enterprise 無解 |
| instance → 來源 library 歸屬 | REST team-level components 反查 | 同上,獨立 skill 範疇 |

figma-design-sync(PR #180/#181)的定位維持:**只讀當前 file 的引用足跡**,
用 manifest `componentRef` + Step 6 元件完整性 gate 把「漏了什麼」變成可見的 `[WARN]` 清單,
不假裝能枚舉外部 library。

## 7. 時間線與近期變更(VERIFIED)

- **2025-06**:官方 Figma MCP server 公開 beta。
- **2025-11**:`files:read` 廣域 scope 強制棄用(改用 `file_content:read` 等細分 scope);
  同期調整 rate limits 與 OAuth app scope 說明規則。
- Variables API 新增 "extended collections"(覆寫 collection modes)。

## 教訓(與 mob review 同源)

**API/MCP 能力必須對著官方 schema 或文件查證,不能憑記憶斷言。**
本次研究修正了兩個「憑記憶」的錯誤:(1)「MCP 未提供任何 library 工具」——Remote variant
其實有 query 工具;(2) 初版 skill 假設 `get_metadata` 回傳 file version——schema 明言沒有。
兩個方向相反的錯(低估與高估能力)都來自同一個根因:沒有先讀 schema。

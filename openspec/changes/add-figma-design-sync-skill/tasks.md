<!--
每個 task 必須陳述 behavior + verification target；「Edit file X」不是合法 task。
[P] = 可平行；[USn] = 對應 User Story。
-->

# add-figma-design-sync-skill — Tasks

## 1. Setup

- [ ] 1.1 `.gitignore` 加 `openspec/changes/*/design/assets/`，使截圖本地保留但不進 git [US1]
      驗證：`git check-ignore openspec/changes/add-figma-design-sync-skill/design/assets/x.png` exit 0（FDS-VL-001）

## 2. Skill 檔案（figma-design-sync）

- [ ] 2.1 撰寫 `plugins/sdd/skills/figma-design-sync/SKILL.md`：frontmatter（type: tool, scope: project,
      effort: medium）、模式決策表（含 MCP 不可用 guard 列與壞損 manifest 列）、extract Step 0-6、
      sync S1-S4（含 assets restore 與指紋盲點 `[WARN]` 三選項）、反模式表、FAQ 表 [US1][US2]
      驗證：spec.md 全部 20 個 scenario 在 SKILL.md 中有對應決策表列或步驟；
      `uv run pre-commit run markdownlint-cli2 --files plugins/sdd/skills/figma-design-sync/SKILL.md`
- [ ] 2.2 [P] 撰寫 `design-context-template.md`：頂部來源與同步資訊區塊 + 7 章節骨架（畫面清單、
      互動流程、元件與狀態、design tokens、文案表、edge cases 與設計缺口、四元素提示），
      頂部含「截圖不入 git」固定註記與 `{{placeholder}}` [US1][US3]
      驗證：章節 1/3/6/7 可直接對應 amplifier Step 1a 四元素；markdownlint 通過
- [ ] 2.3 [P] 撰寫 `manifest-schema.md`：figma-manifest.json schema 完整範例、
      兩層比對機制（file 級 version 早退 / node 級指紋逐欄比對）、已知盲點誠實記載 [US2]
      驗證：schema 欄位與 SKILL.md sync S2 決策表引用的欄位一致；markdownlint 通過

## 3. spectra-amplifier 掛接

- [ ] 3.1 Step 0 決策表加 2 列（figma URL 偵測 → extract；manifest 存在 → sync），
      MCP 不可用時 `[WARN]` 略過不阻斷 [US3]
      驗證：新列語意與 spec.md `amplifier-step0-*` 兩個 scenario 一致（FDS-DT-007/011）
- [ ] 3.2 Step 1a 加設計輸入段（design-context.md 存在時必讀；`[DESIGN GAP]` →
      `[NEEDS CLARIFICATION]` 或 W）[US3]
      驗證：與 spec.md `amplifier-step1a-reads-design-context` 一致（FDS-ST-003）
- [ ] 3.3 Step 3 加「UI 對應」小節（design.md 相對路徑引用 `../design/`，不複製內容）[US3]
      驗證：明確標注 single source 歸屬（design/ 由 figma-design-sync 擁有）
- [ ] 3.4 頂部「輸出結構」與尾部 Quick Reference 兩處目錄樹各加 `design/` 一行 [US3]
      驗證：兩處樹狀圖與 figma-design-sync SKILL.md 的輸出結構一致

## 4. 版本與索引

- [ ] 4.1 sdd plugin 版本 1.5.0 → 1.6.0：`plugins/sdd/package.json` 與
      `plugins/sdd/.claude-plugin/plugin.json` 手動 lockstep（不可用 sync_plugin_versions.py）；
      description/keywords 加 figma 相關字
      驗證：兩檔 `"version"` 欄位均為 `1.6.0`
- [ ] 4.2 [P] `plugins/sdd/README.md` 內容表加 figma-design-sync 一列
      驗證：列格式與既有列一致；markdownlint 通過
- [ ] 4.3 [P] `skills/README.md`「Plugin-only Skill」表格加一列；sdd plugin install 註解補 figma-design-sync
      驗證：分類依 frontmatter `type: tool` 落在 Plugin-only 表；markdownlint 通過

## 5. 驗證與收尾

- [ ] 5.1 全量 lint：`python3 scripts/lint_skill_bash.py` + `python3 scripts/lint_skill_scope.py` + `make ci`
      驗證：全綠；scope lint 對 scope: project skill 直接通過
- [ ] 5.2 向後相容 walkthrough：無 design/ 且無 figma URL 時 amplifier 行為與掛接前相同（FDS-VL-002）
      驗證：amplifier SKILL.md 新增內容全部是條件式前置（design/ 不存在時不觸發）
- [ ] 5.3 E2E（有真 Figma file 時）：extract → 立即 sync（`[OK]` 早退）→ 刪 1 張 PNG 再 sync
      （assets restore）→ 改 frame 尺寸再 sync（增量 + delta markers）；測畢刪除臨時 change 不 commit
      驗證：FDS-ST-001、FDS-DT-004/005/006 全過

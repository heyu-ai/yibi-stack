---
globs: skills/**
---
# SKILL.md 撰寫規範

## Frontmatter（必填）

```yaml
---
name: <skill-name>        # kebab-case，與目錄名稱一致
type: exec                # exec | tool | know
scope: global             # global | project（必填，缺漏會讓 make install 失敗）
description: <一行中文說明，包含觸發關鍵字>
---
```

### scope 選擇標準

| scope | 判斷依據 |
|-------|---------|
| `global` | 純方法論，或執行步驟在任何 git repo 都能跑（知識型 skill、通用工具） |
| `project` | 步驟需要 `uv run python -m tasks.*`、`.runtime/*.json` profile、或本 repo 特定資源 |

**重要**：`make install` 預設只裝 `scope: global` 的 skill。缺少 `scope:` 欄位會讓 install 以 `exit 1` 失敗並顯示錯誤提示，必須補上。

若 skill 的實作住在此 repo 但語意上跨專案有用（如 session-memory、local-port-manager），在 SKILL.md 的執行步驟開頭加上 skill_repo 路徑解析後可設為 `global`：

```bash
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text()).get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi
cd "$SKILL_REPO"
```

**注意（錯誤處理形式）**：`cmd || { echo '[FAIL]' >&2; exit 1; }` 在 `{}` 內有 `'` quote 字元，觸發「brace with quote character」確認框。一律改 `if ! cmd; then echo '[FAIL]' >&2; exit 1; fi`（上面的 canonical form 已採用此寫法）。

**注意**：不要用 `$(jq -r '.skill_repo' …)`（單引號 filter）或 `$(jq -r .skill_repo …)`（unquoted filter）。
前者觸發 AP1 D 類 hook（filter token 內含 leading-dot）；後者通過本地 hook 但 Claude Code 內建 parser 把 leading-dot token 視為無法解析的 string 節點，執行時跳出確認框。

`python3 -c` 單行寫法是唯一兩邊都通過的形式，但 `-c` 後的表達式必須用**單引號**包（Python 內部字串改用雙引號）——雙引號版 `$(python3 -c "...")` 是「外層 `$()` → `"..."` 內層字串」的反向巢狀結構，違反 Rule 14 Quoting Rule 4，觸發 `Unhandled node type: string`。

## Frontmatter — `effort`（選填，2026-05 新增）

v2.1.133+ Claude Code 支援 skill / slash command 在 frontmatter 指定 effort，**覆寫呼叫端的 model effort**：

```yaml
---
name: <skill-name>
type: exec
scope: global
effort: medium     # 選填；low | medium | high
description: ...
---
```

### 何時用 effort frontmatter

| 情境 | 建議 |
|------|------|
| skill 為「重型批次」（大量下載、長批次掃描、規格深度展開） | 釘 `effort: medium` 或 `high`，避免使用者在 low session 誤觸發長批次 |
| skill 為「快速摘要型」 | 釘 `effort: low`，省 token |
| skill 在不同 effort 下行為差不多 | 不填，跟隨呼叫端 |

### 與 SKILL.md 內 `${CLAUDE_EFFORT}` 區塊的關係

frontmatter `effort` 是**覆寫**呼叫端 effort 的最終值；SKILL.md body 內的 `${CLAUDE_EFFORT}` 表格定義**該 effort 下的執行策略**。兩者搭配：

- 不填 frontmatter `effort` + body 有 `${CLAUDE_EFFORT}` 表格 → 跟隨呼叫端動態分流
- 填 frontmatter `effort: medium` + body 有 `${CLAUDE_EFFORT}` 表格 → 強制走 medium 那列

## Exec Skill 標準 4 步驟

```markdown
## 步驟

### Step 1 — 環境確認
cd 到 git repo 根目錄，確認工具可用：
- `uv --version` ✓
- 確認 `.env` 存在

### Step 2 — 設定確認
確認 .runtime/<config>.json 存在，向使用者確認關鍵參數：
- Profile：{{profile_name}}

### Step 3 — 執行
uv run python -m tasks.<module> <command> --profile {{profile_name}}

### Step 4 — 結果報告
回報執行結果：成功筆數、失敗項目、產出路徑。
```

## `{{value}}` Placeholder

需要向使用者確認的參數用雙大括號：`{{profile_name}}`、`{{date}}`。

## FAQ 表格

每個 exec skill 末尾附 FAQ：

```markdown
## 常見問題

| 問題 | 解法 |
|------|------|
| 找不到設定檔 | 執行 `setup` 子命令建立預設設定 |
| API 403 錯誤 | 確認 `.env` 的 token 是否過期 |
```

## Knowledge Skill（type: know）

- 只包含方法論指引，無 Python 執行步驟
- 可有多個 section（如 Core Loop、Anti-patterns）
- `description` 欄位放豐富的觸發關鍵字

## 更新索引

建立或修改 skill 後，必須更新 `skills/README.md` 的索引表格。

`skills/README.md` 在「全域 Skill」section 下有兩張表格：「可執行/工具型（exec/tool）」和「知識型（know）」。`scope: project` 的 exec skill 屬於第三張「本 Repo 限定」表格，不在此規則範圍。
**分類依據是 SKILL.md frontmatter 的 `type` 欄位，不是功能感覺**：

| frontmatter `type` | 應放的表格 |
|--------------------|-----------|
| `exec` 或 `tool` | 可執行/工具型 |
| `know` | 知識型（方法論）|

常見錯誤：`type: know` 的 skill 因「感覺可執行」而被放入工具型表格（如 `bump-version`）。
維護 README 時，先用下列指令確認 type 再決定位置（從 repo 根目錄執行）：

```bash
grep -m1 '^type:' skills/<name>/SKILL.md
```

## 參考模板

`skills/_template/SKILL.md.tpl` 是標準格式參考。

## 決策表與 Prose 的自洽性

決策表（mode table）必須自給自足：不能只靠表格外的 prose 描述例外行為。
agent 閱讀 SKILL.md 時按 table row 優先執行，表格外的說明段落容易被跳過。

正確做法：

- 在表格加 guard row（如「任一工具 BINARY_OK+NOT_AUTHED → 先執行停止流程，不進入 count 計算」）
- 或在對應 row 的動作欄明確標注適用條件（如「0（全部 NOT_FOUND，無 auth 失敗）」）

反模式：prose 說「偵測到 X 狀態時停止」，但 table 的 `count=0` row 說「redirect 終止」——agent 跟著 table 走，prose 的 intent 完全被覆蓋。

## FAQ 修復指令格式

FAQ 表格中的修復指令必須符合三個條件：

1. **使用實際變數名**：不用 literal `KEY` 這類 placeholder，直接寫 `CODEX_API_KEY` / `GEMINI_API_KEY` 等實際名稱
2. **shell-hygiene-safe 語法**：用 parameter expansion `"${VAR# }"` 去除前置空格，不用 `$(echo $VAR)` subshell（後者在 zsh 不 trim、且觸發 Rule 14 quoting hygiene hook）
3. **跨 shell 相容**：指令在 zsh（macOS 預設）與 bash 均能正確執行

## Table Description 欄單一職責

Markdown 表格的說明欄只應包含**功能描述**，不得重複其他欄位（如 Install 欄）的資訊。

常見錯誤：在說明欄附加安裝路徑（如 `— no package.json, installed as global skill`）。
Install 欄已攜帶安裝指令；說明欄重複此資訊會在安裝方法變更時造成雙重維護負擔，且與其他欄位的 pattern 不一致。

## Hook 說明必須對照實際腳本驗證（PR #303 教訓）

CLAUDE.md 或 SKILL.md 中描述 hook 行為時，**必須 Read hook 腳本本身**確認，不得憑記憶或舊文件撰寫。

常見錯誤：說明寫「runs ruff format on .py files after Write/Edit」——實際腳本只覆蓋 `backend/**/*.py`，
且還跑 `ruff check`（lint）、`tsc --noEmit`（前端）、`terraform fmt -check`（infra）。

正確做法：

1. 用 Read tool 讀取 `.claude/hooks/<hook-name>.sh`（或對應腳本路徑）
2. 對照 path guard（如 `*backend*`、`*frontend*`），確認哪些檔案類型真的受影響
3. 列出所有工具呼叫，依實際覆蓋範圍分行說明

```markdown
<!-- 違規：記憶/猜測 -->
**Hook side-effects** -- automatically runs `ruff format` on `.py` files

<!-- 正確：對照腳本，列出完整範圍 -->
**Hook side-effects** -- `post-edit-check.sh` runs automatically after Write/Edit/MultiEdit:
- `backend/**/*.py`: `ruff format` + `ruff check` (per-file)
- `frontend/**/*.{ts,tsx}`: `tsc --noEmit` (project-wide type check)
- `*.tf`: `terraform fmt -check`
```

mob review 的 Claude voice 對照 hook 腳本後發現不一致；Gemini R1 回報「accurate（低信心）」，
直到 R2 看到 Claude findings 才同意修正。說明準確性不能依賴 reviewer 交叉確認——撰寫時就要驗證。

## Cross-doc Cite 必須 paste 原文 quote，不靠記憶寫摘要（PR #415 教訓）

當 rule / docs / SKILL.md 引用「其他規範來源」（另一個 rule 檔、另一個 repo 的文件、
官方 API spec）時，**必須 paste 原文 quote 或精確 section reference，不能靠記憶寫摘要**。
靠記憶會在「方向 / 主被動 / 適用範圍」三個維度出現靜默錯誤，且第一輪 review 通常抓不到，
因為 reviewer 也只 verify「引用對象是否存在」而不 verify「引用內容是否支持論點」。

典型失誤模式（yibi-mvp PR #415 實況）：

- yibi-stack `13-bash-anti-patterns.md` 「exec wrapper 穿透 deny rule（2026-05）」段
  原文：「Claude Code deny rule 現在可穿透 `env` / `sudo` / `watch` ... 不要以為用
  wrapper 就能繞過 deny rule」——意義是 **deny rule 變強，看穿 wrapper 並攔截**
- yibi-mvp 新 rule 初版引用時寫成：「PATH= env-wrapper 模式**可穿透 deny rule**」——
  意義變成 **wrapper 變強，繞過 deny rule**，主動 / 被動寫反，**論點與來源相反**
- 第一輪 code-reviewer 確認「來源檔案存在 + 段落名稱對」就 pass，
  第二輪 comment-analyzer 對照原文 quote 才抓到方向反向

避免方式：

```markdown
<!-- 違規：靠記憶寫摘要，主動 / 被動容易錯 -->
依 yibi-stack 13-bash-anti-patterns.md 的「exec wrapper 穿透 deny rule」段，
PATH= 也可穿透 deny rule。

<!-- 正確：paste 原文 quote，方向自明 -->
yibi-stack `.claude/rules/13-bash-anti-patterns.md` 原文：
> Claude Code deny rule 現在可穿透 `env` / `sudo` / `watch` / `ionice` / `setsid`：
> ... 不要以為用 wrapper 就能繞過 deny rule。

由原文可知：**deny rule** 攔截 **wrapper**，wrapper 不能穿透 deny rule。
```

判斷準則（哪些引用必 paste，哪些可摘要）：

| 引用類型 | paste 還是摘要？ |
|---------|---------------|
| 方向（X 攻擊 Y / Y 攻擊 X、誰主動 / 誰被動）| **必 paste** 原文，自己讀出方向 |
| 條件 / 適用範圍（在 X 情況下做 Y）| **必 paste** 條件原文，避免落掉前提 |
| 結論（結果是 Z）| 可摘要，但結論前的「因為...」前提段落必 paste |
| 工具 / 概念簡介 | 可摘要 |

cross-doc cite 必須對「兩端」分別 verify：

1. **引用對象**：檔案 / section 真的存在（路徑正確、未漂移）
2. **引用內容**：原文真的支持你的論點（方向 / 條件 / 範圍對齊）

只 verify 第一端會放過 **dangling reference**（連結對但內容反向錯）。Reviewer agent
prompt 應明確要求「每個 cross-ref 兩端都 verify」，否則 single-source 驗證的 reviewer
會放過 inversion / mis-paraphrase 錯誤。

與「Hook 說明必須對照實際腳本驗證」的關係：兩者同屬 cross-doc / cross-artifact verification
精神——hook 規範要對照腳本，rule cite 要對照原文，rule 與 spec 的關係要對照 source spec。
撰寫時都要 verify，不能假設 reviewer 會抓。

## 跨 repo 引用：doc body 必須 self-contained，lineage 放 commit message

當把某 repo 的 lesson / incident codify 成另一 repo 的 doc / skill / rule 時，**doc body 不能塞
「來源：`<other-repo>` PR #`<N>` retro」這種 cross-repo 來源指標**。下游 reader 可能沒有來源 repo 的
存取權，pointer 等於空指針；即使有權，跨 repo 切換 + 翻 retro 也是 ~10 倍於閱讀原文的成本。

正確做法：

1. **doc body**：原 incident 的可重現摘要（self-contained，含足夠 context 讓讀者不出本 repo 就能
   理解 lesson）。
2. **commit message**：詳述 lineage（"derived from `<repo>` PR #`<N>` retro" + handover ID + 日期）。
3. **PR description**：同 commit message 詳述，加上「為何要把這條 lesson 跨 repo 帶過來」的動機。

實證：yibi-stack PR #36（pr-test-analyzer FAQ）第一版在 FAQ row 尾巴寫「來源：openab_workspace
PR #73 retro。」——code-reviewer NIT-1 + comment-analyzer Important #2 兩個 voice 都 flag，理由：
yibi-stack reader 沒 openab_workspace 存取權，pointer 等於空指針。Fix pass 把來源指標從 doc body
拿掉、移到 commit message + PR description；FAQ row 改成完全 self-contained，舉的例子改用泛型
helper 名稱（不再綁定 openab_workspace 特有的 `require_kubectl_context`）。

與「Cross-doc Cite」（上一段）的關係：兩者同屬 cross-doc 寫作衛生，但軸不同——
Cross-doc Cite 要求**引用時 paste 原文**避免方向錯；本節要求**引用後 doc body 仍要 self-contained**
避免 dead link。實務上兩條一起遵循：先 paste 原文 verify direction，然後把 verified 的內容自然
融入本 repo doc 的 narrative，不留 cross-repo pointer。

## Retro / lesson-routing skill 的「下一步」必須命名具體目的地

任何「從 retro / review 收尾結果產生後續動作」的 skill（`/pr-retro`、各種 `*-cycle`、`*-review`），
在「建議下一步」段落不能只寫「考慮一下」「或許可以」「之後再決定」這類**動詞模糊 + 目的地缺席**的措辭。

實證：yibi-stack PR #36 retro（handover `c88c0e9e`）結束後，agent 用 4-option AskUserQuestion
（A/B/C/D）把三個 testing-discipline lesson 路到具體目的地（每選項都對應實際 rule 檔 + section
名），使用者選 A 後一輪內完成落地（本 PR 即落地結果）。反例：若 follow-up 只寫「考慮把 lesson
寫進文件」，使用者選後還要再開一輪「寫哪？」對話，retro 落地率會跌一個量級。

正確做法（skill 設計時）：

```markdown
<!-- 違規：動詞模糊 + 目的地缺席 -->
- [ ] 考慮把 lesson 寫入文件

<!-- 正確：明確命名目的地 + 動詞 -->
- [ ] 寫入 `.claude/rules/15-irreversible-operations.md` 類別 3 Recovery section（git 工作流復原）
- [ ] 寫入 `~/.claude/CLAUDE.md` 跨專案個人偏好區
- [ ] 寫入 `<repo>/CLAUDE.md` Gotchas section（repo-specific）
- [ ] 不寫文件，僅保留在 session-memory（一次性/無重現性 lesson）
```

每個選項對應的「目的地檔案 + section」應該已經被 skill 自身計算過（class 對應 routing table），
讓使用者在 AskUserQuestion 時看到的就是 actionable 路徑，不是抽象建議。

來源實踐：`/pr-retro` Step 5 Lesson Classifier（pr-retrospective SKILL.md）已用此 pattern。

## Blockquote 之間插入新 blockquote 必須移除空行（MD028）

在現有 blockquote 區塊之後插入新的 blockquote 時，若兩者之間有空行，markdownlint 會觸發
**MD028/no-blanks-blockquote**（空行被視為「在同一 blockquote 內出現空行」）。

```markdown
<!-- 違規：兩個 blockquote 之間有空行 -->
> 既有說明文字。

> **新增執行說明**：...

<!-- 正確：移除空行，合為一個連續 blockquote -->
> 既有說明文字。
> **新增執行說明**：...
```

常見踩坑情境：在安全性警告 blockquote 後面插入「執行說明」blockquote，
原本 `blockquote → 空行 → code block` 合法，但改成 `blockquote → 空行 → blockquote`
後就違規。此 pattern 在本 repo 曾多次重複（PR #5、#24、#70）。

**快速驗證**（commit 前先跑，省去 CI 來回）：

```bash
uv run pre-commit run markdownlint-cli2 --files skills/<name>/SKILL.md
```

## 自帶 stderr log 的 script 需加 no-capture blockquote hint

Background session harness 設計上會自動把 `> $CLAUDE_JOB_DIR/<name>.log 2>&1` 附加到
Bash 指令後面，用於輸出隔離與跨 compaction 持久。對**已自帶內部 stderr log**的 script
而言，此外加 capture 是冗餘的，還會觸發 `~/.claude/` sensitive file 權限對話框
（`$CLAUDE_JOB_DIR` 含 per-session UUID，allow-list 無法永久放行）。

**修法**：在 bash code block 之前加 blockquote 執行說明，明確告訴 agent 不要外加 capture：

```markdown
> **執行說明**：腳本已將 stderr 寫到 `$REVIEW_DIR/<name>.log`，stdout 僅輸出
> "<完成訊息>"。**直接執行即可，不要外加 `> $CLAUDE_JOB_DIR/foo.log 2>&1` 捕捉**——
> 失敗時 Read `$REVIEW_DIR/<name>.log` 即可看完整錯誤。

\`\`\`bash
bash ~/.agents/skills/<skill>/scripts/<name>.sh
\`\`\`
```

**適用條件**：script 同時滿足以下三點時才需要此 hint：

1. stderr 已重導向到固定路徑的 log 檔（非 stdout）
2. stdout 只輸出一行「完成」訊息（沒有 agent 需要讀取的診斷輸出）
3. 在 background session 流程中執行（harness 會自動附加 log capture）

## Spec and SKILL.md behavioral guards must stay in sync

Any guard or exception in SKILL.md — a zero-score condition, a threshold constraint,
a tie-breaking rule — must be reflected in the corresponding spec.md decision table.

If the guard exists only in SKILL.md, the spec cannot be used to cross-check agent
behavior during review; if it exists only in spec.md, the agent never sees it.

**Pattern**: whenever you add a guard to SKILL.md, immediately update spec.md's decision
table (and vice versa). The two documents describe the same contract from different angles:
SKILL.md is the agent's execution interface; spec.md is the verifiable source of truth.

Example from harness-eval D5 (PR #83): in one commit the EG-* sub-item in SKILL.md was
tightened to require "at least 2 distinct EG categories" but spec.md's decision table was
not updated to match. Mob review round 4 caught the divergence and synced spec.md to reflect
the constraint.

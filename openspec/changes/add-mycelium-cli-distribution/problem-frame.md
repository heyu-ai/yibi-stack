# Problem Frame: add-mycelium-cli-distribution

## Frame Type

主導 frame 為 **Simple Workpieces**，組合的次要 frame 為 **Required Behaviour**。

| 子問題 | 方法論決策表判斷 | 分類與理由 |
|--------|------------------|------------|
| package metadata、README、六份 SKILL.md、hook 設定與 symlink/resolver lane 的修訂 | 使用者透過工具建立或編輯工件，且每次編輯後都必須維持結構與相容性不變式 | **Simple Workpieces**：主要交付是可版本化工件的受控修改，核心 concern 是單一 distribution、package root、七檔一致的 recorded-tag 安裝字串與 verify-before-unlink 順序不能被破壞 |
| skill preflight、hook registration、checkout wrapper 與 cleanup gate | 機器需在 hook 或 skill 執行時自動維持安全狀態，不靠操作者逐步下命令 | **Required Behaviour**：PATH 解析成功時必須使用 installed binary；解析或驗證失敗時必須 fail-loud 並維持 rollback lane |

主導分類選 Simple Workpieces，因 Phase A 的主要變更面是 packaging、文件、skill runbook、settings command 與 migration artifacts；Required Behaviour 則補足 hook/runtime gate 的因果論證。兩個 frame 的 shared phenomena 是 recorded Git tag、PATH 解析出的 required console scripts、shell-quoted `mycelium` hook 路徑、explicit project target，以及六個 symlink/resolver lane 的存在狀態，語意一致且沒有互相矛盾。

Domain discovery judgment：**infrastructure change, domain evidence from issue #222 field data, Event Storming not required**。本 change 沒有新的業務 aggregate 或跨 bounded-context domain event；issue #222 已提供 plugin-only 使用者與野外 symlink 已移除的直接證據，足以支撐 framing。

## R - Requirements (World State)

- **R1**：沒有 yibi-stack checkout 的 plugin-only 使用者，可以從一個已記錄的 release tag 取得三個 CLI，並完成六個 skill 的既有工作流程。
- **R2**：從任意 cwd 啟動 project-sensitive 工作時，實際受影響的 project 或 checkout 必須是使用者指定的目標，不會誤用 CLI process cwd。
- **R3**：auto-handover hook 在先決條件成立時持續可執行；先決條件不成立時，使用者會在任何工作或設定污染發生前看到明確失敗。
- **R4**：Phase A 遷移期間始終至少保有一條已驗證可用的 skill execution lane；未完成或失敗的驗證不會讓既有相容路徑提早消失。
- **R5**：English 與繁體中文使用者都能分辨 plugin 與 CLI 兩條互補安裝軌，且不會被導向尚未交付的 PyPI 路徑。

## S - Specification (Observable Machine Behaviour)

- **S1**：Phase A apply/verification MUST 選定並記錄單一具體 immutable release tag，且 MUST 只支援由該 recorded tag 形成的 exact tag-pinned Git command；既有 `yibi-stack` distribution MUST expose `mycelium`、`pr-orchestrator` 與 `portman`，wheel MUST 保留 `tasks`、排除 `tasks/**/tests/**`，且 MUST NOT 建立第二個 distribution。
- **S2**：六個 skill MUST 在第一個 tasks-backed operation 前以 `command -v` preflight selected path 實際會呼叫的每個 console script：`pr-cycle-fast` 檢查 `pr-orchestrator`（若 path 也使用 `mycelium` 則兩者都檢查）、四個 mycelium-backed skills 檢查 `mycelium`、`local-port-manager` 檢查 `portman`；任一解析失敗時 MUST 指出缺少者、輸出 `[FAIL]` 與 S1 的 exact recorded-tag command、非零退出，且 MUST NOT fallback 到 checkout、`uv run`、`uvx` 或 `python -m tasks.*`。
- **S3**：所有 project-sensitive `mycelium` 呼叫 MUST 傳 `--project <slug>`；`pr-orchestrator` repo 操作 MUST 傳 `--repo-root <absolute-path>`；`portman` MUST 依既有介面傳明確 project option 或 operand，且 global commands MUST NOT 收到虛構 scope flag。
- **S4**：install-hooks MUST 從當下 PATH 解析 `mycelium` 的絕對路徑，以 `shlex.quote` 或等價方式 shell-quote 後固定寫入 `~/.claude/settings.json`，且 shell parsing 後第一個 argv MUST 等於該 resolved path；checkout wrappers MUST 在每次執行時以 `command -v mycelium` 解析。任一解析失敗 MUST fail-loud，且 hook commands MUST NOT 使用 checkout import 或 `uvx`。
- **S5**：六個 real-checkout symlink 與 consumer resolver lane MUST 保留到 recorded tag 的 clean-environment verification 全部通過；任一失敗或未執行項目 MUST 阻擋 cleanup。通過後 MUST 只移除六個指定 symlink 與已無用途的 resolver logic，並 MUST 保持 `tasks/mycelium` root 與 26 個既有 test import path。
- **S6**：README English／繁體中文 install sections 與六個 failure gates MUST 只呈現 S1 由 recorded release tag 形成的同一條 exact CLI command，並 MUST 將 plugin install 與 CLI install 說明為不同目的的互補軌；Phase A MUST NOT 出現 PyPI install command。

## W - Domain Assumptions

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| W1 | `uv` 已存在於目標機器，且可執行 `uv tool install`。 | Phase A 的唯一安裝入口無法啟動；必須先新增 uv bootstrap 前置步驟或重新定義支援矩陣。 |
| W2 | PATH 在 interactive shells **以及執行 hooks 的 contexts** 都會暴露 uv tool bin directory。 | skill preflight 會找不到 selected path 需要的 `mycelium`、`pr-orchestrator` 或 `portman`，checkout wrapper 會找不到 `mycelium`；install-hooks 也可能無法解析可固定寫入的絕對路徑，R1/R3 不成立。 |
| W3 | 目標機器可透過 `git+https` 存取 `github.com/heyu-ai/yibi-stack`。 | Git-tag installation 無法取得 source；clean-environment acceptance 與 SMK-001 無法執行，且不得進入 cleanup。 |
| W4 | 用於安裝與驗證的 release tags 已存在且不可變，驗證證據會記錄實際 tag。 | 安裝結果不可重現，verify-before-unlink 證據不能綁定確定版本；cleanup 必須被阻擋。 |
| W5 | 這六個 skills 由 Claude Code plugin cache 消費，不需要 repo-root `skills/` symlink 才能被發現。 | 移除 real-checkout symlink 後 plugin discovery 會失敗；必須保留相容 lane 或修正 plugin packaging 後再驗證。 |
| W6 | issue #222 field data 顯示 real-checkout symlinks 已在野外被移除，因此目前狀態對 plugin-only 使用者確實是 broken。 | 若此證據不成立，變更的緊急度與遷移風險模型需重新評估；不得以未驗證的 field claim 作為 cleanup 正當性。 |

## Correctness Argument (S together with W implies R)

由 W1、W3 與 W4，S1 由 recorded release tag 形成的 exact Git-tag command 在目標機器上有可執行、可取得且可重現的 source；S1 再保證同一 `yibi-stack` distribution 提供三個 console scripts。由 W5，六個 skill 可從 plugin cache 被發現，S2 逐一 preflight 並將它們導向實際需要的 installed CLI，因此推出 R1。

由 S3，每一個 project-sensitive shared phenomenon 都攜帶明確 project slug 或 absolute checkout path；因此即使 cwd 不相關，受影響目標仍由 invocation contract 決定，推出 R2。

由 W2，install-hooks 與 hook contexts 可以看見 uv tool bin directory。S4 在 registration 時以 shell-safe 形式固定可執行的絕對路徑，並在 wrapper runtime 重新解析；S2/S4 對缺少 binary 的情況都在副作用前 fail-loud，故 hook 可用性或明確失敗兩者必居其一，推出 R3。

由 W6，野外已有失去 symlink lane 的 broken state，不能把「先 unlink 再驗證」當作安全假設。S5 把 recorded-tag clean-environment evidence 設為 cleanup 的必要前置，W4 讓此證據可重現；失敗時保留相容 lane，成功後只清除已被 installed CLI 取代的六個位置，因此推出 R4。

最後，S6 同時約束兩個 README 語系與六個 failure gates，只允許 S1 的 exact command 並排除 PyPI；因此使用者看到的是 plugin 與 CLI 的互補責任，而非尚未交付的替代路徑，推出 R5。故在 W1-W6 成立時，S1-S6 足以推出 R1-R5。

## Frame Concern Checklist

- [x] 通用：R 只描述使用者與目標環境應成立的世界狀態，未指定機器內部實作。
- [x] 通用：S 只描述 install command、CLI argv、PATH resolution、settings command、文件字串與 cleanup gate 等可觀察 shared phenomena。
- [x] 通用：W 已列出所有非機器保證的外部前提，且每條都標明不成立的後果。
- [x] 通用：Correctness Argument 已逐條說明 S 與 W 如何推出 R1-R5。
- [x] Simple Workpieces：工件 invariants 已明列為單一 distribution、`tasks/mycelium` root 與 test imports 不變、唯一 install string，以及 verify-before-unlink ordering。
- [x] Simple Workpieces：會破壞 invariant 的非法編輯序列已由 S5 拒絕；verification 失敗或未執行時不得進入 unlink/cleanup。
- [x] Required Behaviour：W2-W5 的因果前提足以讓 PATH resolution、plugin discovery、recorded tag 與 cleanup evidence 傳播為 R1、R3、R4，而不把「機器發出命令」誤當作「世界必然完成」。
- [x] Frame composition：兩個 frame 對 recorded tag、resolved binary path、explicit target 與 compatibility lane 的 shared phenomena 定義一致。

所有適用 concern 均已檢查；effort=medium 無未完成項目，因此不需 `[WARN]` block。

## DBC Mapping (Documentation Only)

| 合約 | 來源 | 對應 validator / test |
|------|------|-----------------------|
| require | W1-W5 與各 Scenario 的 GIVEN | 本 change 沒有新的 Pydantic input model；由 clean-environment preflight、fake PATH fixtures、MYCLI-ST-001..006、MYCLI-DT-001..004 與 SMK-001..003 驗證。 |
| ensure | R1-R5 與各 Scenario 的 THEN | packaging、skill argv、hook settings、documentation assertions，以及 `make ci` 的後置結果。 |
| invariant | Simple Workpieces concern、S1、S5 | MYCLI-ST-003、MYCLI-CV-001、MYCLI-ORD-001/002 驗證 distribution/package boundary 與 cleanup ordering；不新增 Pydantic `@model_validator`。 |

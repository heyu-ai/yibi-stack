## 1. Distribution entry points

- [ ] 1.1 落實「D1 — Reuse the existing yibi-stack package」與「D2 — Expose every shipped Click CLI through console scripts」：在 `pyproject.toml` 保持 `yibi-stack`、`packages = ["tasks"]`、test exclusion 與現有 dependencies 不變，新增 `mycelium = "tasks.mycelium.cli:cli"`、`pr-orchestrator = "tasks.pr_orchestrator.cli:cli"` 並保留 `portman`，交付「Installable yibi-stack CLI distribution」。驗證：讀取 build metadata 確認沒有第二個 distribution，且 `uv run pytest scripts/tests/test_packaging.py` 通過。
- [ ] 1.2 強化 `scripts/tests/test_packaging.py` 的 distribution contract，明確斷言 `mycelium`、`pr-orchestrator`、`portman` 三個名稱及 target，並讓每個 target 都解析為 Click command；驗證：錯置任一 module/attribute 的負向 fixture 會失敗，正確設定下 `uv run pytest scripts/tests/test_packaging.py` exit 0。

## 2. Checkout-independent skill consumers

- [ ] 2.1 落實「D4 — Make six skill consumers checkout-independent」於 `plugins/pr-flow/skills/pr-cycle-fast/SKILL.md`：以 installed `pr-orchestrator` 取代 `python -m tasks.pr_orchestrator`，共同 preflight 缺 `mycelium` 時輸出 `[FAIL]` 與唯一 Git-tag install command；repo-sensitive command 保持 `--repo-root "$REPO_ROOT"` 與明確 `--pr`，交付「Checkout-independent skill execution」及 pr-orchestrator 面的「Explicit project targeting」。驗證：content test 不含 tasks module invocation，並以 fake `pr-orchestrator` capture argv 斷言 detect/auto-fix 收到正確 `--repo-root`。
- [ ] 2.2 遷移 `plugins/pr-flow/skills/pr-control-log/SKILL.md` 到 installed `mycelium control-log`，加入共同 preflight，project-sensitive `add` / `stats` / `advice` 全部顯式傳 `--project "$ORIG_PROJECT"`；暫時保留 bootstrap resolver lane 到第 4.3。驗證：fake mycelium capture argv 證明目標 project 正確，且缺 binary 時 `[FAIL]` 先於任何工作發生。
- [ ] 2.3 遷移 `plugins/pr-flow/skills/pr-retrospective/SKILL.md` 到 installed `mycelium`，加入共同 preflight，`retro` / `lessons` / `token-usage` 的 project-sensitive path 都傳 `--project "$ORIG_PROJECT"`，filesystem scope 另傳 `--workdir "$REAL_WORKDIR"`；暫時保留 resolver lane 到第 4.3。驗證：fake mycelium capture argv 覆蓋 search/write/read/add/report，且不存在無 project 的 fallback。
- [ ] 2.4 遷移 `plugins/growth/skills/mycelium/SKILL.md` 到 installed `mycelium` 並加入共同 preflight；global `init` / `migrate` 維持原介面，project-sensitive read/write 顯式傳 project，不再以 `uv run --directory "$SKILL_REPO"` import source tree。驗證：SKILL content check 與 fake CLI smoke 同時證明 global command 未收到虛構旗標、project command 收到正確 `--project`。
- [ ] 2.5 遷移 `plugins/growth/skills/learn/SKILL.md` 到 installed `mycelium lessons` / `mycelium insight`，加入共同 preflight，所有 query 都傳 `--project "$PROJECT"` 並移除無 project filter 的 cwd fallback。驗證：show/search/list 的 argv assertions 全含 intended project，missing-binary case 精確匹配 `[FAIL]` 與唯一安裝指令。
- [ ] 2.6 遷移 `plugins/util/skills/local-port-manager/SKILL.md` 到已安裝的 `portman` contract，仍先以 `command -v mycelium` 驗證同一 distribution，並把舊 Git/HEAD 安裝文案統一為唯一 tag-pinned command；`list` 顯式用 `--project`，其餘 project-scoped commands 顯式帶 positional project。驗證：content test 覆蓋 preflight、唯一 install string、`list --project` 與 get/suggest/reserve/release project operand。

## 3. Resolved hook boundary

- [ ] 3.1 落實「D5 — Resolve the settings hook binary at registration time」與「Stable installed hook binary」：在 `tasks/mycelium/cli.py` 提供 `hooks pre-compact` / `hooks session-start` installed command，並讓 `tasks/mycelium/auto_handover_hooks.py` 在 install-hooks 時以 `shutil.which("mycelium")` 或等價方式從 PATH 解析絕對路徑，將解析結果固定寫入 settings commands；找不到 binary 時以 `[FAIL]` 停止。保持 matcher、stdin JSON、systemMessage、exit status、冪等 install/uninstall 與 best-effort metrics 行為。驗證：`tasks/mycelium/tests/test_cli.py` 與 `test_auto_handover_hooks.py` 以 temp dir 中 PATH 上的 fake `mycelium` 覆蓋兩個 payload path、resolved absolute path equality、missing-binary `[FAIL]`、重複安裝、保留其他 hooks，且 command 字串不含 checkout/uvx/tasks import。
- [ ] 3.2 將 `.claude/hooks/pre-compact-handover.sh` 與 `.claude/hooks/post-compact-handover-back.sh` 改為以 `command -v mycelium` 尋找 binary 的相容 wrapper；找不到時以 `[FAIL]` 停止，並移除 inline `tasks.mycelium.metrics_service` / models imports，且保持原 exit behavior。驗證：既有 hook tests 將 fake `mycelium` 放在 temp dir 並加入 PATH，斷言 wrapper 呼叫解析到的路徑及 missing-binary `[FAIL]`，並以 `rg 'tasks\.mycelium|uvx|uv run'` 對兩檔取得零命中。

## 4. Verify-before-unlink migration

- [ ] 4.1 先鎖定 compatibility invariant：issue #222 所列 26 個 `tasks/mycelium/tests` 仍以 `tasks.mycelium` import，`tasks/mycelium` package root 未移動，交付「Verify-before-unlink migration」的 import-path 面。驗證：source inventory/content assertion 通過，且既有 mycelium test suite 在 distribution edits 後仍全綠。
- [ ] 4.2 落實「D6 — Verify first, unlink second」：在沒有 yibi-stack checkout 的 clean HOME/PATH 以實際 tag 執行唯一 Git install command，記錄 tag，驗證三個 console-script `--help`、六個 skill invocation smoke、project/`--repo-root` argv 與 dynamically resolved hook command；任一檢查失敗即停止且不得執行 4.3。驗證：testplan 的 MYCLI-ST-001..006、MYCLI-DT-001..003 全部 PASS 且保存輸出。
- [ ] 4.3 僅在 4.2 證據全綠後，移除 `skills/pr-cycle-fast`、`skills/pr-control-log`、`skills/pr-retrospective`、`skills/mycelium`、`skills/learn`、`skills/local-port-manager` 六個 real-checkout symlink，並刪除這六個 consumer 及兩個 bootstrap 內已無用途的 `SKILL_REPO` / `resolve-skill-repo` logic；不得刪除其他 consumer 仍使用的 repo-wide resolver。驗證：六個 symlink 均不存在、目標 consumer 的 resolver rg check 為零、plugin 仍可發現六個 SKILL.md，且 MYCLI-ORD-002 通過。

## 5. Documentation and final verification

- [ ] 5.1 落實「D3 — Publish Phase A as a tag-pinned Git install」與「Two-track installation documentation」：更新 `README.md` English / 繁體中文 install 章節，清楚區分 plugin 與 CLI 兩軌，CLI 只列 `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"`，不出現 PyPI 指令。驗證：MYCLI-DOC-001/002 content assertions 通過，六個 SKILL.md `[FAIL]` gate 與 README 的 install string 完全相同。
- [ ] 5.2 執行完整回歸並完成交付證據：`make ci` 必須 exit 0，clean-install acceptance suite 在 cleanup 後重跑仍全綠，README two-track 與六個 skill path 維持可用。驗證：MYCLI-CI-001、所有 spec scenario trace 與 testplan TC 均記錄 PASS；若失敗，恢復 cleanup lane 並回到對應 task 修正，不宣告完成。

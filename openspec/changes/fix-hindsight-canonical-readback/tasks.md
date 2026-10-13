## 1. 先寫失敗的測試（red first）

- [x] 1.1 在 tasks/mycelium/tests/test_lessons_rows.py 建立 WAL 重現 fixture：建一個 WAL 模式的拋棄式 DB（含 lessons table 與測試列），checkpoint 後移除 -shm 與 -wal；fixture 本身斷言檔頭為 WAL（第 18／19 位元組為 2／2）且 -shm 不存在。再寫對照測試 LROWS-EG-001：以 mode=ro 的檔案 URI 開啟，若丟出 sqlite3.OperationalError（unable to open database file）即通過；若此 SQLite 版本能開啟（如 3.47.1），以 pytest.skip 標示版本號與「此 SQLite 不重現」，不得靜默通過。驗證：系統 python3（SQLite 3.51.0）下以探針確認會失敗；uv 環境（SQLite 3.47.1）下 EG-001 顯示為 skipped 並附版本號。
- [x] 1.2 寫 Complete canonical row listing 的失敗測試：LROWS-DT-001 同 key 一列 active、一列 retired 且帶 superseded_by，兩列都要回傳；LROWS-DT-002 parked 與 retired 列都要回傳且 tags 是 JSON 陣列；LROWS-DT-003 要了但不存在的 key／id 列入 missing_keys／missing_ids 且 exit 0；LROWS-DT-004 另一 project 的同 id 不回傳並列入 missing_ids；LROWS-CV-001 rows 依 key、ts、id 排序，requested 去重排序。驗證：在尚未實作前執行 uv run pytest tasks/mycelium/tests/test_lessons_rows.py，這些測試失敗（rows 子指令不存在）。
- [x] 1.3 寫 Read-only open without creating the database 與 Exit status distinguishes failure from an empty result 的失敗測試：LROWS-EG-002 在 1.1 的 WAL 無 -shm fixture 上指令 exit 0 並回傳列；LROWS-EG-003 不存在的 DB 路徑 exit 3、stdout 空、stderr 以 [FAIL] 開頭，且路徑在執行後仍不存在；LROWS-EG-004 唯讀開啟函式回傳的連線執行 INSERT 被拒、列數不變；LROWS-EG-005 沒有 lessons table 的 DB exit 3 且不會建表；LROWS-VL-001 未給 --key／--id、給 201 個識別碼、key 含空白、project 為空字串，皆 exit 2；LROWS-DT-005 全部未命中時 exit 0、rows 為空陣列。DB 路徑一律以 MYCELIUM_DB_OVERRIDE 注入。驗證：實作前這些測試失敗。
- [x] 1.4 寫 Effective confidence parity 的失敗測試 LROWS-ST-001：同一 DB、同一列，rows 子指令輸出的 effective_confidence 與 show_lessons_typed 回傳的值相同（固定 ts 讓衰減結果可預期）。驗證：實作前失敗。

## 2. 實作唯讀讀回

- [x] 2.1 依決策「以 mode=rw 加 query_only 開 DB 取代 mode=ro」，在 tasks/mycelium/db.py 新增唯讀開啟函式：以 mode=rw 的檔案 URI 連線（不建立不存在的檔案）、連上後執行 PRAGMA query_only = ON、不執行 journal_mode PRAGMA、不呼叫 init_db；DB 檔不存在、無法開啟或缺 lessons table 時拋出 RuntimeError（raise from 原例外）。同檔新增依 project 加 keys／ids 的查詢函式：單一參數化 SELECT（project = ? AND (key IN ... OR id IN ...)），以既有的 lesson row 解碼邏輯把 tags／files 轉成 list，依 key、ts、id 排序。驗證：LROWS-EG-002、EG-004、EG-005 通過。
- [x] 2.2 依決策「effective_confidence 沿用 show 的衰減計算」與「輸出單一 JSON 物件並列出 missing keys 與 missing ids」，在 tasks/mycelium/lessons_service.py 新增 service 函式：呼叫 2.1 的函式、為每列加上以 _apply_decay 計算的 effective_confidence、組出含 schema_version、project、requested（去重排序）、rows、missing_keys、missing_ids 的 dict。驗證：LROWS-DT-001～004、CV-001、ST-001 通過。
- [x] 2.3 依決策「新增 lessons rows 子指令而非擴充 lessons show」與「DB 不可用以 exit 3 回報」，在 tasks/mycelium/cli.py 的 lessons group 註冊 rows 子指令：--project 必填、--key 與 --id 可重複、合計 1～200 個、key 格式 ^[A-Za-z0-9_-]+$，違反者以 click.UsageError 結束（exit 2）；DB 路徑沿用 _ctl_db_path()（MYCELIUM_DB_OVERRIDE），未設定時用預設 handover.db；service 拋出 RuntimeError 時 stderr 輸出 [FAIL] 加原因並 raise SystemExit(3)，stdout 不輸出；成功時 click.echo 輸出 JSON（ensure_ascii=False）。lessons show／search 不改。驗證：LROWS-EG-003、VL-001、DT-005 通過，且 uv run python -m tasks.mycelium lessons --help 列出 rows。
- [x] 2.4 讓 lessons wrapper（scripts/lessons）把 rows 歸為「不注入 --project」：呼叫端漏帶 --project 時，wrapper 不得以 cwd 的 project 補上（否則讀回被靜默窄化成錯的 repo），改由 CLI 以 exit 2 失敗；同步更新 drift guard 測試 LSW-VL-001 的分類集合，並新增 LSW-DT-007 斷言 rows 經 wrapper 轉發時不帶 --project。驗證：uv run pytest scripts/tests/test_lessons_wrapper.py 全綠；暫時從 wrapper 的豁免清單拿掉 rows 時 LSW-DT-007 轉紅，還原後轉綠。

## 3. 協議文件

- [x] 3.1 依決策「HINDSIGHT.md 讀回步驟改呼叫 lessons rows」，落實 Hindsight protocol readback uses the rows subcommand：改寫 plugins/growth/skills/pr-retrospective/HINDSIGHT.md「Canonical projection and lifecycle reconciliation」的第 2、3 步，合併為一次 mycelium lessons rows 呼叫（傳入本次所有候選 key 與所有先前 accepted receipt 的 key 和 lesson_id）；移除 SQLite 連線形式與 bound query 的描述；寫明 exit 0 才可繼續，exit 2 判 degraded 並提示 installed CLI 可能過舊需以新 release tag 重裝，exit 3 判 degraded；missing_ids 含 receipt owner、owner 歧義、同 key 多個 active rows 時維持原本的 degraded／拒絕規則，且讀回不得與寫入交錯。驗證：rg 'sqlite3.connect|SELECT \* FROM lessons' plugins/growth/skills/pr-retrospective/HINDSIGHT.md 無命中（不再提供連線字串與 bound query）；rg -n 'mode=ro' 的命中只出現在「不要自行開 SQLite」的警告句中；並人工核對新段落涵蓋 spec 的 protocol-single-call、protocol-nonzero-degrades、protocol-missing-owner-degrades 三個 scenario。

## 4. 收尾驗證

- [x] 4.1 以 scripts/sync-plugin-versions.sh 做 lockstep patch 版本升級（plugins/** 有改動），確認各 plugin 的 package.json 與 .claude-plugin/plugin.json 版本一致。驗證：git diff 顯示所有 plugin 版本檔同步變動到同一版本號。
- [x] 4.2 git add 所有新檔後執行 make ci，全部通過（pre-commit --all-files、pytest、lint、typecheck）。驗證：make ci exit 0，且 make ci 之後 git diff --name-only 為空（formatter 未改檔）。
- [x] 4.3 （執行紀錄：mode=ro 與去重兩個突變照原計畫在原始碼上做，分別讓 EG-002〔SQLite 3.51.0〕與 DT-001 轉紅並已還原；拿掉 query_only 的原始碼突變被 auto mode 判為削弱安全控制而拒絕，改以不動原始碼的對照取代：在拋棄式 DB 上證明 mode=rw 連線未開 query_only 時 INSERT 成功、開啟後被拒，即 EG-004 斷言的「寫入被拒」唯一依賴 query_only。）對 rows 子指令做突變驗證：分別把 query_only PRAGMA 拿掉、把 mode=rw 改回 mode=ro、在查詢後加上依 key 去重，每次只改一處，確認對應測試（EG-004、EG-002、DT-001）轉紅，再以反向套用同一替換還原。mode=ro 那個突變必須在會重現問題的 SQLite 3.51.0 直譯器上跑（uv run --isolated --python 指向 asdf 的 Python 3.13.3），因為 uv 預設的 SQLite 3.47.1 本來就能以 mode=ro 開啟，該突變在那裡必然存活、驗不出東西。驗證：三個突變各自讓指定測試失敗，還原後全綠。
- [x] 4.4 在實際的 ~/.agents/handover/handover.db 上以 checkout 版本跑一次 uv run python -m tasks.mycelium lessons rows --project yibi-stack --key precommit-files-regex-follow-renamed-file，確認 exit 0、回傳 id 為 e46f5b6a 開頭的一列，且執行前後 handover.db 主檔的 sha256 相同（沒有寫入資料）。驗證：貼出指令輸出與前後兩次 shasum -a 256 的結果。

## 5. Review 修正（PR #564 Round 1）

- [x] 5.1 （A）query_lesson_rows 改用嚴格解碼 _decode_lesson_row_strict：tags／files 不是合法 JSON 陣列即拋 RuntimeError，CLI exit 3；show／search 用的 _decode_lesson_row 維持寬鬆不動。驗證：LROWS-EG-011（parked 列 tags 為截斷 JSON → exit 3、stdout 空、stderr 以 [FAIL] 開頭）；把查詢改回 _decode_lesson_row 時轉紅。
- [x] 5.2 （B）補同 project 的 --id 正向查詢。驗證：LROWS-DT-006（只給 --id 回傳該列、missing_ids 為空）、LROWS-DT-007（--key 與 --id 命中同列只回一次）；拿掉 id 條件時 DT-006 轉紅，found_ids 改為空集合時兩者皆紅。
- [x] 5.3 （C）父目錄存在但 DB 檔不存在時不建檔。驗證：LROWS-EG-007（db_path 為 tmp_path/handover.db → exit 3、stdout 空、[FAIL]、檔案仍不存在）；mode=rw 改為 mode=rwc 時轉紅。
- [x] 5.4 （D）補 exit 3 的 schema 讀取與查詢錯誤路徑，EG-005 加 [FAIL] 斷言。驗證：LROWS-EG-008（MYCELIUM_DB_OVERRIDE 指向內容為 not a db 的檔案）、LROWS-EG-009（lessons table 缺 ts 欄位使 ORDER BY 失敗），皆 exit 3、stdout 空、[FAIL]；把對應的 except sqlite3.Error 縮窄時分別轉紅。
- [x] 5.5 （E）list_lesson_rows 把組列時的 KeyError／TypeError／ValueError 轉成 RuntimeError（raise from），CLI exit 3 而非 exit 1 加 traceback。驗證：LROWS-EG-010（lessons table 缺 confidence 欄位 → exit 3、[FAIL]）；拿掉轉換時轉紅。
- [x] 5.6 （F）design.md 否決「維持 mode=ro」的理由改為依版本而定（實測 3.51.0 失敗、取決於呼叫端直譯器），與同檔實測表一致。驗證：人工核對 design.md 第 9 列表格與否決理由不再矛盾。
- [x] 5.7 （G）HINDSIGHT.md 第 2 步允許識別碼超過 200 時拆成多次 lessons rows 呼叫，前提是全部在本次 invocation 任何寫入之前完成、不讀寫交錯，rows 合併、missing 取聯集，任一次非 0 即 degraded；design.md 對應決策同步。驗證：人工核對 HINDSIGHT.md 第 2 步。
- [x] 5.8 （H）HINDSIGHT.md 的 exit 2 處理：只有 stderr 含 No such command 才提示以新 release tag 重裝，其餘回報為參數錯誤（超過 200、key 格式不合、project 為空），一律 degraded；design.md 對應決策同步。驗證：人工核對 HINDSIGHT.md exit 2 條目。
- [x] 5.9 （I）open_lessons_readonly docstring 與 design.md Risks 寫明：關閉最後一條連線可能把 -wal 中已 commit 的 frame checkpoint 回主檔，會改寫頁面但不寫入新的 lesson 資料，「主檔 sha256 不變」只在 -wal 為空時成立。驗證：人工核對兩處敘述一致（無程式碼變更）。
- [x] 5.10 （J）LROWS-ST-001 以 monkeypatch 替換 tasks.mycelium.lessons_service 的 datetime（now() 固定為 2026-04-15），show_lessons_typed 與 rows CLI 共用同一時鐘，並斷言衰減值為 confidence - 3；保留「observed 列確實衰減」的守衛。驗證：拿掉時鐘釘選時 ST-001 轉紅（實際日期下衰減值不同）。
- [x] 5.11 （NIT）rows 子指令拒絕前後帶空白的 --project（exit 2），VL-001 補空白 project、前後空白 project、空 --id 三個參數；新增 LROWS-CV-002 斷言同 key 同 ts 依 id 排序；design.md 把 lessons --help 改列為人工確認；proposal.md Impact 的 Modified 補 commands/lessons.md。驗證：拿掉空白檢查時 VL-001 的 surrounding-whitespace-project 轉紅；ORDER BY 的 id 改為遞減時 CV-002 轉紅。

# Oracle 轉錄發現清單

轉錄 pr-cycle-deep SKILL.md 的 Evidence gate 到 `oracle.json` 時，下列格子無法在不做詮釋的
情況下轉錄。依 tasks.md 2.1 的要求，記於此處而非自行補值。這份清單本身就是這個 eval 的第一項
產出：它證明矩陣「every cell defined, no gaps, no ambiguity」的宣稱至少有一處不成立。

## D1（disputed）：missing / invalid 的 contract mapping 落在 deferred 還是 outside-contract

- **Contract mapping gate（SKILL.md「#### Contract mapping gate」段）**：
  「Missing or invalid mapping is moved to **deferred** with its original text and reason preserved.」
- **final.md 格式（同檔「## Outside contract」段）**：
  「`<finding>` — `<Non-goal / accepted boundary / Follow-up / **invalid mapping**>`」

同一種輸入（invalid mapping）被兩段指向不同 section：一段說 deferred，一段把它列在
outside-contract。兩者都是非阻擋，但落點不同，會影響後續讀者對「為何非阻擋」的理解。

**處置**：`oracle.json` 目前只轉錄 `contract_mapping = valid` 的 12 格核心 evidence-gate 矩陣，
未替 missing / invalid 補值。若日後要納入這些格，須先由 human 裁定 SKILL.md 的意圖（改哪一段
使兩者一致），而非由本 eval 自行選一邊。屆時對應的 oracle 條目應以 `disposition: "disputed"`
標記直到裁定完成——`config.check_fixture_oracle_consistency` 會對指向 disputed 格的 fixture
中止並指名，避免在未定義的答案上評分。

## D2（scope）：precondition 層的因子不在目前四因子空間內

目前 oracle 的四因子（severity / evidence / round / contract_mapping）只完整涵蓋
`contract_mapping = valid` 時的 severity×evidence×round 矩陣（12 格）。下列 precondition 規則
需要額外因子，尚未納入：

- **out_of_scope mapping → outside-contract**：Non-goal / accepted boundary / Follow-up 的工作
  落在 outside-contract，與 evidence / round 無關。（可轉錄，但為使「每個 oracle 條目至少被一個
  fixture 引用」成立而暫緩，待有對應 fixture 時再加。）
- **NIT 不受 contract mapping gate 管轄**：gate 明文只約束 Critical / Important，故 NIT 在任何
  mapping 下皆 non-blocking。
- **security / data-integrity baseline 不可豁免（SKILL.md §「Repo security…cannot be waived」）**：
  需要一個布林因子 `is_security_baseline`，其為真時即使 mapping = out_of_scope 仍 blocking。
- **accepted risk 需 `Accepted by:`（SKILL.md §「An accepted risk needs all five fields…」）**：
  需要一個因子表示五欄位是否齊備；缺 `Accepted by:` 時 voice / lead 不得代為接受。

**處置**：記為後續擴充。納入前需擴充因子空間並各自加正向 fixture，不在本 change 範圍。

## D3（artifact 內部不一致，已於本 change 修正）：rerun 觸發條件

design.md「穩定度以三值判定」節的判定表寫「至少 4 次同 disposition 即 CONFORMANT」（即 4:1
為終局，不重跑），但同節末段散文一度寫「落在 3 比 2 或 4 比 1 邊界…加跑至 15」，把 4:1 也納入
重跑。兩者矛盾。spec（review-gate-conformance-eval「Boundary verdicts are re-run at higher n」）
的規範文字是「reaches neither a five-run nor a four-run majority」，即只有無多數（3:2）才重跑。

**處置**：以 spec + design 判定表為準——**只有首輪無多數（UNSTABLE）才加跑至 n=15**；4:1 為
終局 CONFORMANT。已同步修正 design.md 該段散文。實作見 `service.needs_rerun`。

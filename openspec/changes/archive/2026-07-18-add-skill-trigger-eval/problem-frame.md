# Problem Frame：skill-trigger-eval

## Frame 型別

主導：**Transformation**（把「fixture 的 prompt 集合 + 每個 prompt 的觸發判斷」這組輸入資料，
依計分規則轉成「逐類 pass rate + 相對 baseline 的回歸清單」這組輸出資料）。
（組合：次要 **Commanded Behaviour**——skill 作者下 `eval` / `baseline` 命令觸發轉換。）

## R — 需求（世界狀態）

- R1：對每個 fixture 的每一類（direct / indirect / negative），回報的 pass rate 恰等於
  「該類 prompt 中，judge 判斷結果與作者期望一致的比例」——negative 的「一致」意指
  正確地「不觸發」。
- R2：當且僅當某 skill 某類的 pass rate 低於其 baseline 減容忍門檻時，該類被回報為回歸；
  無基準（baseline 無此 skill／類別）時不回報回歸（不多報）；真回歸不漏報（不少報）。
- R3：評測涵蓋 fixture 中所有 prompt——不遺漏任一 prompt，也不憑空產生 fixture 未列的判斷。

## S — 規格（機器在介面的可觀察行為）

- S1：`eval` MUST 對每類計 `passed/total`；direct/indirect 的 passed 條件為「judge 判觸發」，
  negative 的 passed 條件為「judge 判未觸發」。
- S2：`eval` MUST 在任一類 `pass_rate < baseline − tolerance` 時，列出該 skill 與類別並以非零
  狀態結束；所有類皆在容忍門檻內時 MUST 以零狀態結束並回報無回歸。
- S3：`eval` 針對缺 `trigger_eval.json` 的目標 skill MUST 輸出 `[FAIL]` 至 stderr 並以非零結束，
  MUST NOT 視為通過。
- S4：當回饋的 judgments 數與 manifest 數不符時，MUST 抛錯中止，MUST NOT 補零或截斷。
- S5：`build_tasks` 對同一 fixture 集合 MUST 產出穩定順序（direct→indirect→negative，index 連續），
  使 emit-manifest 與 score 兩次呼叫的對位一致。

## W — 領域假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| W1 | 回饋的 judgments 由外部 agent 依「prompt × 目標 skill 的 SKILL.md description」誠實判斷「是否觸發」，且依 manifest index 對齊 | pass rate 反映的是錯位或亂填的判斷，評測結果無意義；需在 S 增加 judgments 來源可信度驗證，改變整體流程 |
| W2 | fixture 的 `expect_trigger` 標註正確反映作者真實意圖（direct/indirect=true、negative=false，且已由 model_validator 強制形狀） | pass 的定義被扭曲，回歸訊號失真；需回頭校正 fixture |
| W3 | baseline 檔中的 pass rate 是先前一次「作者已接受」的評測快照 | 回歸比對的基準無效，回歸判定不可信 |
| W4 | 同一 fixture 的 prompt 集合在 emit-manifest 與 score 兩次呼叫之間不變 | judgments 依 index 對位錯誤（W1 對位前提失效）|

## 正確性論證（S ∧ W ⟹ R）

- 由 S1，逐類 pass rate = 該類中「judge 判斷 == 期望」的比例；由 W1（judgments 誠實且對齊）
  與 W2（期望標註正確），該比例即 R1 所述「判斷正確的比例」。故 **S1 ∧ W1 ∧ W2 ⟹ R1**。
- 由 S2，回歸恰在 `pass_rate < baseline − tolerance` 時回報，無基準時（baseline 無此鍵）不回報；
  由 W3（baseline 為有效快照），此比對基準真實反映「先前可接受水準」。故 **S2 ∧ W3 ⟹ R2**。
- 由 S5（穩定順序）與 W4（prompt 集合不變），manifest 涵蓋且只涵蓋 fixture 所有 prompt，
  逐一計入且不重複；由 S4（數量不符即中止）排除「多餘或遺漏 judgment 被靜默接受」。
  故 **S4 ∧ S5 ∧ W4 ⟹ R3**。

論證成立。

## Frame Concern 檢查表

### 通用（所有 frame）

- [x] R 只描述世界狀態（pass rate / 回歸的語意），不含機器內部怎麼算
- [x] S 只描述機器在「CLI ↔ 作者／檔案」介面上的可觀察行為（exit code、stderr、輸出數字）
- [x] W 列出所有非機器保證的前提（judgments 誠實與對齊、期望標註、baseline 有效、prompt 集合穩定），每條標後果
- [x] S ∧ W ⟹ R 逐條成立（見上）

### Transformation 額外

- [x] 輸入完整性：fixture 中每個合法 prompt 都有對應輸出並計入其類 pass rate（S5 穩定展平 + S4 數量守恆）
- [x] 無多餘：不產生 fixture 未列的判斷；judgments 多於 manifest 時 S4 中止而非新增輸出

## DBC 對應（文件化）

| 合約 | 來源 | 對應 Pydantic validator / 測試 |
|------|------|------------------------------|
| require | fixture 形狀（W2）| `TriggerEvalFixture.check_expect_trigger`（`@model_validator(mode="after")`，rule 05）；`test_models` SEVAL-VL-003/004 |
| require | judgments 為布林陣列 | CLI `_read_judgments` 型別檢查；`test_cli` |
| ensure | pass_rate = passed/total（R1）| `service.score_verdicts` + `test_service` SEVAL-DT-001 |
| ensure | 回歸時非零退出（R2）| `cli.eval` exit 1 + `test_cli` SEVAL-CLI-005 |
| invariant | verdict 數 == manifest 數（R3）| `judges.base.verdicts_from_judgments` RuntimeError + `test_service` SEVAL-EG-002 |

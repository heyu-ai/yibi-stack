# /pr-retro-hard -- 加了跨家 mob review 的 PR Retrospective

與 `/pr-retro` 同一個流程引擎，但在**兩個位置**插入跨家挑戰：Q1–Q5 草稿交給你判斷之前、
以及規則草稿被建議寫檔之前。三個 voice——codex 與 agy 各自條件式（透過既有
`/codex-consult`、`/agy-consult`），加上一個**無條件**的 Claude 對抗式 subagent，任務是
「Make the strongest case that this is wrong」。

草稿逐字保留、異議以旁註呈現、裁決權在你。彙整由可執行的 policy kernel 決定而非散文，
且**一致永不抬升評分**——三個 voice 讀同一份草稿、同一套 prompt，依建構相關而非獨立，
故其一致不構成 cross-model 證據；只有異議能降。

## 用法

- `/pr-retro-hard` -- 自動偵測 current branch 對應的 PR
- `/pr-retro-hard --pr 123` -- 指定 PR 號

不需要跨家挑戰時用 `/pr-retro` 即可（少三次外部呼叫，快得多）。

## 執行

呼叫 `Skill(skill="pr-retro-hard", args="$ARGUMENTS")`，由 SKILL.md 主控完整流程。

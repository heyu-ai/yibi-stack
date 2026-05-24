# pr-review-cycle-mob Multi-Tier Subagent A/B 實驗設計（Pre-Registered Protocol）

**日期**：2026-05-24
**Branch**：`claude/pr-review-subagent-split-19G6n`
**狀態**：Pre-registered Protocol（執行前）
**作者**：本協定在執行任何測量之前敲定，所有假設、變數、決策準則 freeze 於本文件
**Related Plan**：`/root/.claude/plans/pr-review-cycle-subagent-haiku-cached-kitten.md`

---

## 摘要（Abstract）

把 `pr-review-cycle-mob` 中 6 個低決策密度 step（commit/push、PR creation、JSON→markdown 渲染、
CI 輪詢、merge、Jira/spectra 同步）下放到 sonnet / haiku subagent，主決策步驟（review、aggregate、
fix、re-review、人工確認）保留在 lead（opus）。事前 token 分佈估算預測 cost 下降 **5-7%**、
wall-clock **±5 秒**、品質持平。本實驗以 pre-registered A/B 對照測試這三項預測，並以「
fallback 觸發率」「使用者 redo 次數」「missed CI failure 數」三項守門指標驗證機制可靠度。
通過後才會進入 Phase 2（fix loop / re-review 下放）。

---

## 1. 背景與動機（Background & Motivation）

### 1.1 現況

`plugins/pr-flow/skills/pr-review-cycle-mob/SKILL.md`（v1.x）目前所有 step 都由
caller 的 model（典型為 opus 4.7）執行：

- Step 0 detection / Step 1 PR creation / Step 2-3 review orchestration / Step 4-5
  aggregation / Step 6 fix / Step 7 re-review / Step 8 human pass / Step 9 CI watch /
  Step 10 merge / Step 11 spectra/jira

Step 3 已使用「同訊息平行送 4 個 Claude voice subagent」，但這是**邏輯平行**——所有
subagent 仍 inherit caller 的 opus 配置，並非 model tier 分離。

### 1.2 預測的 cost 結構

基於對歷史 mob 跑動的 token 觀察（取樣 N=5，中型 PR ~200-400 LOC diff），單次跑動
token 分佈估算如下：

| Step group | 占總 token | 屬性 |
|------------|----------|------|
| 純機械（commit/PR/CI/merge/sync） | ~5% | candidate for downgrade |
| Review/aggregate/fix/re-review | ~85% | requires lead opus |
| Detection/orchestration/human | ~10% | hybrid |

機械性 step token 量小，**下放對 cost saving 直接貢獻上限約 5-7%**。

### 1.3 為何仍值得做

直接 saving 雖低，但本實驗的真正價值在驗證 4 項可移植機制：

1. Claude Code plugin 路徑下 `plugins/<name>/agents/*.md` 是否正確被
   loader 識別並 honor frontmatter `model:` 欄位
2. Subagent 回傳值（free-form text）能否穩定 parse 為結構化結果
3. Fallback 路徑（subagent 失敗時 lead 接手）能否避免級聯失敗
4. 下放後 user-perceived 品質是否維持不變

這 4 項通過後才能在 Phase 2 安全地下放 fix loop / re-review（占 22% token，預期 saving 14%）。

---

## 2. 研究問題與假設（Research Questions & Hypotheses）

### 2.1 主要研究問題（Primary RQs）

- **RQ1**：把 6 個機械性 step 下放至 sonnet / haiku，cost 變化為何？
- **RQ2**：拆解為 subagent 後，wall-clock 變化為何？
- **RQ3**：下放後輸出品質（PR body、Jira comment、merge 行為）是否與 baseline 等效？

### 2.2 守門研究問題（Gating RQs）

- **RQ4**：plugin agent 安裝路徑是否 work（subagent 是否真的以宣告 model 執行）？
- **RQ5**：fallback 觸發率是否在可接受範圍？
- **RQ6**：是否會放過 baseline 不會放過的錯誤（false negative）？

### 2.3 假設（Pre-registered Hypotheses）

預測使用單尾方向性假設（pre-registered，事後不得改為雙尾）：

| ID | H0（虛無） | H1（對立） | 預測方向 |
|----|-----------|-----------|---------|
| H1 (cost) | Δcost = 0 | Δcost < 0 | multitier 較便宜 |
| H2 (speed) | abs(Δwall_clock) ≥ 30s | abs(Δwall_clock) < 30s | 兩者實質持平（equivalence test） |
| H3 (quality) | quality_multitier < quality_baseline - 0.5（5-pt scale） | quality_multitier ≥ quality_baseline - 0.5 | 非劣性（non-inferiority） |
| H4 (mechanism) | plugin agent loader 不 honor `model:` frontmatter | plugin agent loader 正確 honor | 機制可用 |
| H5 (fallback) | fallback_rate ≥ 0.30 | fallback_rate < 0.30 | 機制穩定 |
| H6 (false neg) | missed_failure_rate ≥ 0.20 | missed_failure_rate < 0.20 | 不會放過更多錯誤 |

注意 H2 / H3 是**非劣性 / 等效性檢定**，不是「越大越好」——這是正確的統計框架，
因為我們要證明的是「下放沒讓事情變差」，不是「下放讓事情變好」。

### 2.4 全通過條件

H1 ∧ H2 ∧ H3 ∧ H4 ∧ H5 ∧ H6 全部 reject H0 → pilot 通過，進 Phase 2 規劃。
任一條件 fail to reject → 進入 §10 分支決策表。

---

## 3. 變數定義（Variables）

### 3.1 自變數（Independent Variable）

- **Condition**：`baseline`（all-opus，現行 SKILL.md）vs `multitier`（pilot 版 SKILL.md
  + 6 個新 subagent）
- 二元 categorical；隨機派至每個 trial

### 3.2 依變數（Dependent Variables）

| 變數 | 型態 | 量測單位 | 來源 |
|------|------|--------|------|
| `total_cost_usd` | continuous | USD | metric harness（token × pricing table） |
| `total_tokens_in` / `total_tokens_out` | continuous | tokens | metric harness |
| `wall_clock_total_ms` | continuous | milliseconds | metric harness |
| `wall_clock_per_step_ms` | continuous | ms | metric harness per step |
| `subagent_invocation_count` | discrete | count | grep transcript |
| `fallback_count` | discrete | count | `$REVIEW_DIR/fallback.log` |
| `quality_pr_body` | ordinal | 1-5 Likert | post-run survey |
| `quality_jira_comment` | ordinal | 1-5 Likert | post-run survey |
| `quality_merge_behavior` | ordinal | 1-5 Likert | post-run survey |
| `redo_count` | discrete | count | post-run survey |
| `missed_failure_count` | discrete | count | injected-failure verification |

### 3.3 控制變數（Control Variables，需在 design 中 hold constant）

- **PR diff size**：用 fixture branch（`experiments/fixtures/`）確保兩 condition 跑同樣 diff
- **Branch state**：每次 trial 從同 base SHA 開始
- **Time of day**：避開 Anthropic API peak hour（UTC 14:00-22:00）以降低 latency 變異
- **Reviewer voices count**：固定 3-voice（Claude + Codex + agy 各 1）
- **CLAUDE_EFFORT**：固定 `medium`
- **Caller model**：固定 opus 4.7

### 3.4 混淆變數（Confounding Variables，需在分析中報告）

- **LLM 非確定性**：相同 prompt 重跑差異可達 ±20-30% on token, ±50% on wording
- **Codex / agy CLI 響應時間**：external，無法控制；可能隨時段變動
- **CI runtime**：GitHub Actions queue 時間隨機；以 Step 9 wall-clock 分離計算

---

## 4. 實驗設計（Experimental Design）

### 4.1 設計類型

**Within-subject crossover（受試者內交叉設計）+ between-subject replication**。

- **Within-subject**：同一 PR fixture 兩種 condition 各跑 N 次，每次完全清除 state
  （fresh worktree）。控制 PR 內容變異。
- **Between-subject**：再以不同 PR fixture 重複，控制 PR 特性變異。

### 4.2 PR Fixture 設計

建立 3 個 controlled fixture branch，固定 diff 內容：

| Fixture ID | LOC | 性質 | 預期難度 |
|-----------|-----|------|---------|
| F-S（small） | ~50 | 單檔 docstring + lint fix | low |
| F-M（medium） | ~250 | 跨 3 檔 refactor + 新增 1 test | medium |
| F-L（large） | ~600 | 跨 8 檔含 schema migration | high |

Fixture branch 位於 `experiments/fixtures/` 下，每個 fixture 有預先 commit 好的 diff，
可隨時 reset 重跑（無狀態）。Fixture diff 內容**事先 freeze**，實驗期間不得修改。

### 4.3 Trial Sequence

| Phase | Fixture | Condition | N trials | 累計 |
|-------|---------|-----------|---------|------|
| P1（mechanism） | F-S | baseline | 3 | 3 |
| P1（mechanism） | F-S | multitier | 3 | 6 |
| P2（quality） | F-M | baseline | 3 | 9 |
| P2（quality） | F-M | multitier | 3 | 12 |
| P3（stress） | F-L | baseline | 2 | 14 |
| P3（stress） | F-L | multitier | 2 | 16 |
| **Total** | | | **16** | |

**Trial order randomization**：在每 fixture 內，6 個 trial 的執行順序用 `python -c
"import random; random.seed(42); print(random.sample(['B','B','B','M','M','M'], 6))"`
（seed=42 freeze）決定，控制時間段效應。

### 4.4 為何 N=3 per cell

正式 power analysis 受限於 LLM 非確定性 effect size 不明、且每 trial cost（~$10-30）
高，N=3 是「能偵測 large effect（Cohen's d > 2.0）但無法偵測 medium effect」的最小值。
本 protocol 接受此 limitation，並在 §11 明列為「statistical power 弱」。

替代方案討論見 §11.3。

### 4.5 環境隔離

每個 trial 在獨立 git worktree 執行：

```bash
git worktree add /tmp/abx-{trial_id} {fixture_branch}
cd /tmp/abx-{trial_id}
# run mob review here
git worktree remove /tmp/abx-{trial_id} --force
```

確保：

- 無 stale state（前一 trial 的 review comment / artifacts）
- 無交叉污染（Codex / agy cache）→ trial 間清空 `~/.codex/cache`、`~/.gemini/cache`
- 同一 base commit SHA

### 4.6 Blinding（盲性）

**Quality rating 盲性化**：post-run quality survey 由獨立 collator 從 16 個 trial 蒐集
PR body / Jira comment / merge message，**移除 condition 標籤後**呈給 rater
（人類使用者）打分。Rater 在打完所有分數前不知道哪份來自 baseline / multitier。

實作：collator 把 outputs 重新命名為 `output_{rng_id}.md`，維護 `condition_map.json`
留在 collator 處，rater 看到的只有 rng_id。

---

## 5. 樣本與統計檢力（Sample Size & Power Justification）

### 5.1 受限於 cost 的樣本上限

| 項目 | 預估 |
|------|------|
| 平均 mob 跑動 cost（baseline） | ~$20 |
| 平均 mob 跑動 cost（multitier） | ~$19 |
| 16 trial 總 cost | ~$310 |
| 人工 rating 時間（16 outputs × 3 dimensions） | ~2 hours |

實務上 N=16 是 cost 與 statistical power 的折衷點。

### 5.2 Detectable Effect Size

以 N=8 per condition、α=0.05（單尾）、power=0.80 計算可偵測的 minimum effect size：

| 假設 | 可偵測 effect | 預測 effect | 結論 |
|------|-------------|-----------|------|
| H1 cost | Cohen's d ≈ 1.2 → ~$5 difference | 預期 $1-2 difference | **嚴重 underpowered** |
| H2 speed | margin ≈ 60s | 預期 ±5s | margin 寬，equivalence test 較易達標 |
| H3 quality | 0.7 Likert point | 預期 0 difference | margin 0.5 嚴格但可達 |

H1 underpowered 是已知 limitation。Mitigation：

- 報告 raw token counts（非統計顯著的 descriptive statistic）
- 用 Bayesian credible interval 取代 frequentist hypothesis test（H1 only）
- 若 pilot 失敗無法判斷是「true null」或「underpowered」，記錄為 inconclusive 而非 false negative

### 5.3 多重檢定校正

6 個假設並行檢定，套用 **Bonferroni correction**：α_per_test = 0.05 / 6 ≈ 0.0083。

只有調整後仍顯著的結果才視為「reject H0」。報告兩種 p-value（raw + Bonferroni）。

---

## 6. 量測方法（Measurement Methodology）

### 6.1 Metric Harness

自動量測由 `plugins/pr-flow/scripts/metrics-record.sh` 負責，**兩 condition 共用**：

```bash
# step 開始
bash scripts/metrics-record.sh begin <step_id> <model> <trial_id>

# step 結束（lead 從 transcript / subagent return 抓 tokens）
bash scripts/metrics-record.sh end <step_id> <tokens_in> <tokens_out> <trial_id>
```

輸出統一 schema 到 `$REVIEW_DIR/metrics.jsonl`：

```json
{"trial_id": "t01", "condition": "multitier", "fixture": "F-M",
 "step_id": "step-1-build-pr", "model": "sonnet",
 "tokens_in": 4231, "tokens_out": 2104,
 "begin_ms": 1748102400123, "end_ms": 1748102447892, "duration_ms": 47769,
 "fallback_triggered": false}
```

完整 schema 見附錄 A。

### 6.2 Token Counting Source

- Lead step tokens：從 Claude Code session transcript 抓取（`/cost` 指令 output 或
  transcript JSON）
- Subagent step tokens：subagent 在 prompt 結尾強制輸出
  `METRICS: {"tokens_in": N, "tokens_out": M, "duration_ms": K}`，lead parse 後寫入

### 6.3 Cost Calculation

使用固定 pricing table（以實驗開始日 2026-05-24 的官方 Anthropic pricing freeze）：

```python
PRICING_2026_05_24 = {
    "opus":   {"input_usd_per_mtok": 15.00, "output_usd_per_mtok": 75.00},
    "sonnet": {"input_usd_per_mtok":  3.00, "output_usd_per_mtok": 15.00},
    "haiku":  {"input_usd_per_mtok":  1.00, "output_usd_per_mtok":  5.00},
}
```

實驗期間若 pricing 變動，**仍使用 freeze 版本**計算，並在報告中註明。
這避免 pricing 變動成為混淆變數。

### 6.4 Wall-Clock 量測

`begin_ms` / `end_ms` 用 `date +%s%3N`（GNU date）或 `python3 -c "import
time; print(int(time.time()*1000))"`（macOS 相容）。不用 `date +%s` 因為秒級
resolution 對 Step 9-11 不夠細。

### 6.5 Quality Survey（人工量測）

每個 output 由 rater 在 5-point Likert scale 評分（移除 condition 標籤後）：

```
PR Body Quality
1 = 必須完全重寫（漏掉關鍵 context、誤導性敘述）
2 = 大幅修改（多處需重寫）
3 = 可接受（小幅 polish 即可使用）
4 = 良好（直接 ship）
5 = 優秀（與 opus baseline 同等或更好）

Jira Comment Quality  (same scale)
Merge Behavior  (same scale, with criteria)
```

完整 rubric 見附錄 B。

### 6.6 False Negative 量測（H6）

在 P1 階段額外注入 4 個 controlled bug，驗證 multitier 是否會 miss：

| Injection ID | 注入點 | 預期被偵測 |
|-------------|-------|-----------|
| INJ-1 | Step 9 CI watch：在 push 前先 commit 一個會 CI fail 的 lint error | ci-watcher 必須 report failure |
| INJ-2 | Step 10 merge：在 bump=true 條件下 spectra-jira-syncer 收到 bump=false | pr-merger 必須 reject |
| INJ-3 | Step 11 Jira：給定無效 Jira issue key（不存在的 PROJ-99999） | spectra-jira-syncer 必須 report 錯誤而非靜默通過 |
| INJ-4 | Step 1 PR creation：caller 給定不存在的 base branch | pr-builder 必須 abort 而非建立壞 PR |

每個 INJ 在 baseline / multitier 各跑 1 次，比較 detection rate。
任何 multitier 漏掉 baseline 抓到的 → H6 fail。

---

## 7. 操作性定義（Operational Definitions）

學術等級嚴謹度的關鍵：以下術語必須在實驗開始前 freeze 定義，不得在實驗中改動。

### 7.1 "Fallback Triggered"

定義：subagent 呼叫滿足以下任一條件：

- subagent return 為空字串或 timeout（>10 min）
- subagent return 不含預期的 `RESULT:` 區塊
- subagent return 含 `RESULT: error`
- lead 解析後判斷需要自己重做（依 SKILL.md 內 fallback 路徑）

不算 fallback：lead 對 subagent 結果做小幅編輯後採納。

### 7.2 "Redo Count"（使用者重做）

定義：人工 rater 在 quality survey 中標註「我會自己重寫這個 output」的次數。

不算 redo：「我會做小幅修改」（rating ≥ 3）。

### 7.3 "Missed Failure"

定義：注入的 controlled bug（INJ-1~INJ-4）在 baseline 被偵測到、在 multitier 未被偵測。

不算 missed：兩 condition 都未偵測（baseline 也漏 → 是 baseline 缺陷，不算 multitier 退化）。

### 7.4 "PR Body Quality"

依附錄 B rubric 評分。3 個 rater 獨立評分後取 median。
若 3 個 rater 評分極差 >2 分，視為高變異樣本，分析時報告但不納入 H3 主檢定。

### 7.5 "Wall-Clock Equivalent"

H2 的 equivalence margin 設 ±30 秒。基於使用者感知門檻：
mob 一次 wall-clock 10-30 分鐘，±30 秒 < 5%，使用者不易感知差異。

---

## 8. 預先註冊分析計畫（Pre-Registered Analysis Plan）

**重要**：以下分析方法在實驗開始前 freeze，事後不得修改、不得新增分析。
新增 exploratory analysis 必須明確標註「post-hoc」並打折報告。

### 8.1 主要檢定

| 假設 | 統計方法 | α |
|------|---------|---|
| H1 cost | Welch's t-test（單尾，multitier < baseline） | 0.0083（Bonferroni） |
| H2 speed | TOST equivalence test，margin ±30s | 0.0083 |
| H3 quality | Wilcoxon non-inferiority test（ordinal data），margin 0.5 | 0.0083 |
| H4 mechanism | binary：所有 multitier trial 是否成功觸發宣告 model | n/a（要求 100%） |
| H5 fallback | binomial test，one-sided H1: p < 0.30 | 0.0083 |
| H6 false neg | Fisher's exact test on injection detection table | 0.0083 |

### 8.2 描述性統計（必報告）

- 每 cell 的 mean, median, SD, IQR
- Box plot：cost / wall-clock per condition × fixture
- Quality rating distribution（stacked bar）
- Step-by-step token decomposition

### 8.3 Post-hoc 分析（事先列出，但結果僅作探索）

- Fixture size × condition interaction（two-way ANOVA）
- Step-level cost saving 拆解
- Subagent invocation count vs wall-clock 相關

任何上述列表外的事後分析必須標註「exploratory, not pre-registered」並打折報告。

---

## 9. 決策準則（Decision Criteria）

實驗結束後依以下決策表處理。決策表事前 freeze，不得事後修改。

| 結果 | 行動 |
|------|------|
| 6 假設全 reject H0（H1-H6 均通過） | Pilot 通過，啟動 Phase 2 規劃 |
| H4 fail（plugin agent 不 work） | Pilot **失敗，無條件回滾**。檢討是否改用其他機制（如 launch script wrap） |
| H6 fail（multitier miss bug） | Pilot 失敗，回滾。重新檢視 subagent prompt / fallback 設計 |
| H5 fail（fallback > 30%） | Pilot 失敗，subagent prompt / context 設計需重做 |
| H3 fail（quality 退化 > 0.5 點） | 部分回滾：把退化的 subagent demote 回 lead，其餘保留 |
| H1 fail（cost 不顯著下降） | 中性：保留 multitier 但**不宣稱 cost benefit**；視 H2/H3 表現決定是否進 Phase 2 |
| H2 fail（速度退化 > 30s） | 接受退化（pilot 本來就接受 ±5s 預測有誤）；若退化 > 60s 視為實質問題 |
| Inconclusive（underpowered） | 不下結論。延長 trial 數至 N=8 per cell 後重跑 |

### 9.1 「部分回滾」決策矩陣

若 H3 fail 但只在特定 subagent，逐一檢視：

| Subagent | Quality fail 時的行動 |
|----------|--------------------|
| pr-builder | Demote 回 lead，保留其他 5 個 subagent |
| ci-watcher | Demote 回 lead 或從 haiku 升 sonnet 再測一輪 |
| pr-merger | Demote 回 lead（高風險操作，品質失誤不可接受） |
| spectra-jira-syncer | 升 sonnet 再測；若仍 fail 則 demote |
| codex/agy renderer | 升 sonnet 再測；若仍 fail 則 demote |

---

## 10. 效度威脅（Threats to Validity）

### 10.1 Internal Validity（內部效度）

| Threat | 強度 | Mitigation |
|--------|------|-----------|
| 時段效應（API latency / load 隨時間變動） | 中 | randomize trial order（§4.3） |
| LLM 非確定性 | 高 | 每 cell N=3，報告中位數而非單次 |
| Codex/agy CLI 版本變動 | 低 | 實驗期間 freeze CLI 版本（pin version） |
| Rater bias | 高 | Blind rating（§4.6）；3 rater 取 median |
| 順序學習效應（rater 看了多個 output 後標準變動） | 中 | Rater 評分順序也 randomize |

### 10.2 External Validity（外部效度）

| Threat | 影響 |
|--------|------|
| Fixture 只代表 3 種 PR size，真實 PR 分佈可能不同 | 結論限於 fixture 涵蓋範圍 |
| 實驗在 single dev machine 跑，多人協作場景未測 | 結論不外推到團隊使用 |
| 只測 mob 變體，不測 `pr-review-cycle` Claude-only 版 | Phase 2 需另設實驗 |
| Anthropic pricing 變動 | 用 freeze pricing 計算（§6.3） |

### 10.3 Construct Validity（建構效度）

| Threat | Mitigation |
|--------|-----------|
| 「Quality」是主觀建構，rubric 可能未涵蓋所有面向 | 3 rater + median + 公布 rubric（附錄 B） |
| 「Cost」只計 Claude API，未計人工 redo 時間 | Redo time 額外量測為 secondary outcome |
| 「Fallback」定義可能未捕捉所有失敗模式 | 操作性定義 §7.1 明列 |

### 10.4 Statistical Validity（統計效度）

| Threat | 嚴重度 |
|--------|--------|
| N=3 per cell underpowered for medium effect | **高** —— H1 cost 預期 effect size 小，可能 inconclusive |
| Multiple comparisons | 已用 Bonferroni 校正 |
| Likert data 非常態分佈 | 用 non-parametric（Wilcoxon） |
| Crossover design 內存自相關 | 用 paired analysis where applicable |

---

## 11. 限制（Limitations）

### 11.1 已知限制

1. **N=16 是 cost-bound 折衷，非 power-bound 最適**：H1 cost 檢定 underpowered，結論
   只能說「未偵測到 large effect」，不能說「無 effect」。
2. **Rater pool 是同一個人（實驗發起人）**：理想應該是 3 個獨立 rater，實務上難實現。
   Mitigation：blind rating + 評分間隔 ≥24 小時降低短期 bias。
3. **Fixture 是人造，非自然 PR**：可能無法完全捕捉真實使用情境的 edge case。
   Phase 2 應補做「in-production A/B」（隨機派真實 PR）。
4. **CI / Jira 環境變數**：CI runtime、Jira API latency 是 noise source，無法控制。
5. **單一 caller model**：只測 opus 4.7。其他 caller（sonnet self-call）未測。

### 11.2 不做的延伸實驗

以下擴展明確排除於本實驗範圍：

- 不測 Phase 2 的 fix-applier / spot-check-reviewer（待 Phase 1 通過後另設 protocol）
- 不測 `pr-review-cycle` Claude-only 變體
- 不測 model auto-router 替代 explicit tier
- 不測 caching 對 multitier cost 的影響

### 11.3 改進建議（給未來重做者）

- 提升 N 至 8/cell（cost ~$600）以達 medium effect detection
- 增加 2 名獨立 rater
- 加入 1 個「人造異常 PR」fixture（含 typo、broken test、license 衝突）測 edge case
- 用 within-PR diff swap 方式控制 LLM 變異（更高 power）

---

## 12. 倫理與透明度（Ethics & Transparency）

### 12.1 Cost Disclosure

實驗總預估 cost ~$310（Claude API only）。實驗發起者自付。
報告中將公開實際花費（per cell + total），供後續實驗者 budget 參考。

### 12.2 Pre-registration

本 protocol 是 pre-registration 文件，commit 至 git repo 時間早於任何 trial 執行時間。
任何後續修改記錄在 git log，且不得改動 §2 假設、§8 分析計畫、§9 決策準則。
若必須修改（例如發現 fixture bug），新增「Amendment」段落並標註日期，原文不刪。

### 12.3 結果報告承諾

無論結果是 positive / negative / inconclusive，都會以同一 `docs/research/` 路徑
報告，命名 `<date>-pr-review-mob-multitier-ab-results.md`。
不做選擇性報告（publication bias mitigation）。

### 12.4 Raw Data Sharing

完整 `metrics.jsonl`、quality rating CSV、fallback log 一併 commit 至 repo
（`experiments/results/` 目錄），供後續驗證 / 重分析。
敏感資訊（如 Jira issue 內容、私 PR diff）在 commit 前 redact。

---

## 13. 重現性（Reproducibility）

### 13.1 Pinned Versions

實驗開始前 freeze 以下版本至 `experiments/pinned-versions.txt`：

- Anthropic API model alias（opus / sonnet / haiku 對應的實際 model ID）
- Codex CLI version
- agy / Antigravity CLI version
- yibi-stack git SHA
- pricing table snapshot

### 13.2 Fixture Branches

`experiments/fixtures/` 下 3 個 fixture branch 是 pre-committed，重跑時 reset 到該
SHA 即可。Fixture 不會在實驗期間修改。

### 13.3 Reproduction Steps

完整重現步驟記錄於 `experiments/REPRODUCE.md`（待建立）：

1. Clone repo 到指定 commit SHA
2. 安裝 pinned versions
3. 執行 `bash experiments/run-all.sh`（待寫）
4. 比對輸出與 `experiments/results/expected/`

### 13.4 Analysis Notebook

統計分析以 Jupyter notebook（`experiments/analysis.ipynb`）執行，
notebook 與 raw data 一同 commit。
任何 plot / table 都可從 notebook 重現。

---

## 14. 時程（Timeline）

| 階段 | 預估工時 | 預估日期 |
|------|---------|---------|
| Protocol freeze（本文件 commit） | -- | 2026-05-24 |
| Metric harness 實作（`metrics-record.sh` + schema） | 4h | 2026-05-25 |
| 3 個 fixture branch 建立 | 3h | 2026-05-26 |
| 6 個 subagent 定義檔撰寫 | 5h | 2026-05-27 |
| multitier SKILL.md 改寫 | 4h | 2026-05-28 |
| Mechanism smoke test（不入正式 trial） | 2h | 2026-05-28 |
| **Trial execution** | 16 × ~30min = 8h | 2026-05-29 ~ 06-02 |
| Quality rating（blind） | 2h | 2026-06-03 |
| Statistical analysis + notebook | 3h | 2026-06-04 |
| Results 文件撰寫 | 3h | 2026-06-05 |
| **總計** | ~34h | ~2 週 |

---

## 15. 結論（在此 freeze）

本 protocol 是執行 pr-review-cycle-mob multi-tier subagent pilot 的 pre-registration
文件。所有假設、變數、分析、決策準則在 commit 此文件時 freeze。實驗結果與本 protocol
的對照報告將另文發表。

預測結果（事前公告，可被反證）：
- H1 cost：方向正確（multitier 較便宜）但效應太小，可能 inconclusive
- H2 speed：通過（在 ±30s 內）
- H3 quality：通過（在 0.5 Likert 點內）
- H4 mechanism：通過（plugin agent loader work）
- H5 fallback：通過（< 30%）
- H6 false neg：通過（無 missed injection）

如果預測錯，本實驗仍有價值——錯誤的預測比沒預測更有資訊。

---

## 附錄 A：Metric Schema（v1, frozen 2026-05-24）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["trial_id", "condition", "fixture", "step_id", "model",
               "tokens_in", "tokens_out", "begin_ms", "end_ms",
               "duration_ms", "fallback_triggered"],
  "properties": {
    "trial_id":  { "type": "string", "pattern": "^t\\d{2}$" },
    "condition": { "enum": ["baseline", "multitier"] },
    "fixture":   { "enum": ["F-S", "F-M", "F-L"] },
    "step_id":   { "type": "string" },
    "model":     { "enum": ["opus", "sonnet", "haiku"] },
    "tokens_in":  { "type": "integer", "minimum": 0 },
    "tokens_out": { "type": "integer", "minimum": 0 },
    "begin_ms":   { "type": "integer" },
    "end_ms":     { "type": "integer" },
    "duration_ms": { "type": "integer", "minimum": 0 },
    "fallback_triggered": { "type": "boolean" },
    "subagent_name": { "type": ["string", "null"] },
    "notes": { "type": ["string", "null"] }
  }
}
```

## 附錄 B：Quality Rating Rubric（frozen 2026-05-24）

### B.1 PR Body Quality

| Score | 標準 | 範例 |
|-------|------|------|
| 1 | 必須完全重寫 | 漏掉所有 changed files；誤導性 summary；無 test plan |
| 2 | 大幅修改（>50% rewrite） | summary 太抽象；漏掉關鍵 design decision；test plan 不可執行 |
| 3 | 可接受（小幅 polish） | 內容正確但缺少 1-2 個次要 detail；wording 可改但不影響意思 |
| 4 | 良好（直接 ship） | 完整、清晰、follow repo convention；無修改需求 |
| 5 | 優秀（同等或超越 opus baseline） | 額外提供有用 context；catch 到非明顯的 trade-off |

### B.2 Jira Comment Quality

| Score | 標準 |
|-------|------|
| 1 | 完全脫離 PR 內容；引用錯誤 |
| 2 | 部分正確但漏掉 PR 主要 contribution |
| 3 | 正確摘要但缺乏細節 |
| 4 | 良好摘要 + 正確 link + 適當 detail |
| 5 | 摘要 + 影響評估 + clear next step |

### B.3 Merge Behavior

| Score | 標準 |
|-------|------|
| 1 | 在不應 merge 時 merge（bypass CI、忽略 review） |
| 2 | Merge 但 squash message 嚴重錯誤 |
| 3 | Merge 成功 + squash message 可接受 |
| 4 | Merge + 正確 squash + 清理 branch |
| 5 | Merge + 完美 squash message + 主動報告下游影響 |

### B.4 Rater Instructions

1. 看到的是 `output_{rng_id}.md`，不知道 condition
2. 三個 dimension 獨立打分，不互相影響
3. 不確定時打 3，避免極端值偏誤
4. 完成所有 output 後才看 `condition_map.json`

---

## Amendment Log

（任何 protocol 修改在此記錄；空白表示尚未修改）

- *(none yet)*

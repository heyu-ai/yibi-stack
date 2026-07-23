# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.12.0] - 2026-07-23

### Added

- Add Dependabot config for uv and github-actions (#290)

### Changed

- Wheel 範圍守衛 + smoke test 落地 (#262) (#272)
- Task 4.3 unlink -- remove six real-checkout symlinks and resolver lanes after 4.2 tag verification (15/15 tasks) (#292)
- 專案架構改指向 ARCHITECTURE.md，移除重複的目錄樹與 Skill 執行步驟 (#251)
- Archive add-mycelium-cli-distribution -- promote mycelium-cli spec baseline (issue #222 Gap A closed)
- Bump 6 vulnerable deps to clear 17 Dependabot alerts (#299)
- Lessons delete + retire 退場機制（#242） (#284)
- Pipe masks upstream exit code (rule 13, PR #299 retro) (#306)
- Bump the python-minor-patch group across 1 directory with 11 updates (#304)
- Bump urllib3 (#301)
- Bump idna in /plugins/3rd-tools/skills/verify-gemini-models (#302)
- Bump cryptography (#303)
- Bump astral-sh/setup-uv from 4 to 7 (#294)
- Bump actions/checkout from 4 to 7 (#295)
- Bump actions/cache from 4 to 6 (#296)
- Lint_rule_frontmatter 機械 guard，防 globs: 類靜默失效 (#252) (#274)
- Bump mypy from 1.19.1 to 2.3.0 (#298)
- Pre-push-ruff-format-guard - block pushing unformatted .py (#272 retro) (#300)
- 安全更新也 group 成單一 PR (#309)
- 起草 ADR-0005 相容性閘門用能力探測不用 semver 版本字串 (#256) (#278)
- Correct AP3-C and retry-cap gotchas against 2.1.199/2.1.207 changelog (#310)
- Lessons add 寫入前查重，不再靜默 insert 重複 (#267 Part A) (#277)
- 用 openspectra archive 6 個完成 change，清空積壓 (#227) (#280)
- Rule 09 記錄 snapshot fixture 漂移（PR #280 CI 教訓） (#313)
- 統整 60 條 nightly-agent 孤兒分支，收斂為 8 條已驗證規則 (#312)
- Consolidate 3 residual 07-20 nightly-agent lessons (#314)
- Revert "fix(pr-flow): sync mob-code-review-only final.md rewrite table with engine" (#320)
- 加 Step 1.6 fact-assertion sweep，把 review surface 撐出 diff 之外 (#321)
- Gate mob review with a PR review contract (extracted from #305) (#316)
- Propose add-retro-evidence-gate (retro rule/hook write-time evidence gate) (#322)
- Amplify add-retro-evidence-gate to 5-layer spec (problem-frame, US+AC, Gherkin slugs, testplan)

### Fixed

- Drift-guard 把 git -C 路徑傳進 subprocess cwd，杜絕假陰性放行 (#258) (#273)
- State 檔加 repo 隔離維度，杜絕跨 repo 同號 PR fail-open (#246) (#271)
- Post-edit-mypy 收緊 grep pattern 相容 mypy 2.x (#308)
- 補 negative-trigger redirect 修正 over-trigger + 修 lint 雙計 bug (#307)
- 治理 pipeline (generated test/去重/slug/失敗訊號) (#259, #225) (#279)
- Wrapper 的 basename(pwd) fallback 加 [WARN]，不再靜默記錯 project (#276)
- Tree-drift-guard no longer false-blocks git commands with a pipe in a quoted arg (#315)
- Sync mob-code-review-only final.md rewrite table with engine

## [1.11.0] - 2026-07-18

### Changed

- Phase 1 打包骨架 - tasks/ 可安裝化，portman 白老鼠 (#222) (#249)
- Audit log 只記 block + 30 天每日輪替（PR #262） (#263)
- 用證據閘門與兩輪上限收斂 mob review (#266)
- Split codex skill into codex-review + codex-consult (#264)
- Vendor investigate skill from gstack (+ /lessons recall) (#268)
- Mycelium CLI distribution change proposal (issue #222 Gap A Phase A) (#269)
- Enforce the subshell-exit fail-open mechanically (#234 follow-up) (#241)
- Phase A install-from-git -- entry points, six-skill migration, stable hook binary (#281)
- V1.11.0

### Fixed

- LaunchAgent PATH 找不到 uv，nightly-agent 連壞 4 晚無人知 (#261)
- Agy review model 由 Gemini 3.1 Pro (High) 降為 (Low) (#265)
- Fix recurrence-check CLI (lessons search, not find) (#275)
- Repair silently-broken stdin form and the stale probes that caused it (#231)

## [1.10.0] - 2026-07-16

### Changed

- Route PR #224/#233 self-locate lessons into rule 13 (#235)
- Rm -rf must check both halves; never &&-gate a restore (#214 retro) (#236)
- 整併 clean-gone + clean-merged 成 /clean-wt（證據導向，預設只報告） (#239)
- Push 前擋下「已驗證的樹 != 要 push 的樹」 (#255)
- V1.10.0

### Fixed

- Self-locate skill repo via shared resolver, retire config.json lookup (#221 follow-up) (#224)
- Ignore inherited GIT_DIR/GIT_WORK_TREE when self-locating (#233)
- Amplifier TC parser sees 3 of 101 TCs and reports success (#223)
- Block make install from a worktree, fail loud (#232) (#234)
- 把 worktree 守門下推到 Python 層，覆蓋全部 5 個 sink (#240)
- Step 4b 補 --project，修 retro lesson 誤記 project scope (#244)
- Repair spectra-amplifier resource locator + plan plugin-primary delivery (#222) (#230)
- 讀取指令不再注入 --project，還原 CLI 宣稱的「預設全部 project」 (#248)
- 用 paths: 取代 globs: 讓條件式 rules 真正延遲載入 (#250)

## [1.9.0] - 2026-07-14

### Changed

- Pin frontier models for codex and agy review voices (#229)
- V1.9.0

## [1.8.0] - 2026-07-14

### Added

- Address post-merge review findings (#211 follow-up) (#214)

### Changed

- Skip PyPI hint when pyproject has no [build-system]; fix CHANGELOG MD033 (<name> -> backtick) (#216)
- Exclude generated CHANGELOG.md from markdownlint (#217)
- Route PR #210 retro lessons into rule files (#218)
- V1.8.0

### Fixed

- Bootstrap 自我定位 SKILL_REPO，不再信任共享 config key (#215)
- 套用 #215 的 self-locate 修法（同一 root cause） (#221)

## [1.7.0] - 2026-07-13

### Added

- Add verify-before-authoring member -- probe generalizations + reader-run commands (#200 retro) (#201)

### Changed

- Token/cost tracking + dedicated retrospectives table for /pr-retro (#205)
- PR #205 retro follow-ups (stale-symlink gotcha, cross-call bash vars) (#209)
- Skill-trigger-eval module (issue #186 B2 Phase 1) (#211)
- Run spectra-amplifier QA test design at high effort (#212)
- Pin effort medium for clean-merged and clean-gone commands (#213)
- V1.7.0

### Fixed

- Make agy review REVIEW-ONLY with guard + edit detection (#203)
- Write .pr-review exclude via --git-path so it works in worktrees (#204)
- Stop amplifier-verify misdetecting <name> placeholder as a spectra change (#207)
- Lessons 已與 handover 分家，修正 session_id 溯源 (#210)

## [1.6.0] - 2026-07-09

### Added

- Add issue-triage skill for periodic GitHub issue governance (#202)

### Changed

- V1.6.0

## [1.5.2] - 2026-07-08

### Added

- Add EFC paper reference notes for design and experiments (#134)
- Add Quoting Rule 7 -- bare $VAR + non-ASCII folds into name (#198 retro) (#200)

### Changed

- V1.5.2

### Fixed

- Resolve review base from upstream remote for fork PRs (#196) (#198)
- Per-repo skill_repos map to end skill_repo drift (#197) (#199)

## [1.5.1] - 2026-07-08

### Added

- Add figma-design-sync skill for Figma-to-OpenSpec design handoff (#180)
- Add symlink preflight to rule 11 Dual-Source Document Ownership (#189)
- Add lint_skill_overlap.py over-trigger detector (B1 MVP) (#190)

### Changed

- Define LGTM-with-trickle-NITs convergence judgment (#184)
- Internalize SkillOps framing into rule 11 + pr-retro (#188)
- Figma MCP/REST library limitations (context7 + agy verified) (#182)
- Prune CLAUDE.md duplicates + record PR #190 retro lessons (#191)
- Recheck PR status in Step 6 before group re-review (#193)
- V1.5.1

### Fixed

- Correct figma-design-sync Figma MCP contract (follow-up to #180) (#181)
- Repo-wide skill audit fixes (3 Critical / 12 Important / NITs) (#183)
- Correct two inaccurate simple_expansion claims in rules-context (#192)
- Drive Codex R1 through codex exec so the skill-hijack guard works (#195)

## [1.5.0] - 2026-07-02

### Added

- Add mob-code-review-only skill (review others' PRs, suggestions only) (#171)
- Add CI/release/python/license badges and Apache-2.0 LICENSE (#165)
- Add distill subcommand + harden pr-retro capture quality (#173)
- Add problem-frames methodology skill for R/S/W framing (#174)

### Changed

- Draft via Claude Code CLI (subscription) instead of API key (#169)
- 因應 Claude Code 2026-W25 更新調整 rules/CLAUDE.md/settings (#167)
- Adopt Claude Code 2.1.186-2.1.195 release changes into doc-layer defenses (#176)
- Pin mechanical toil commands to sonnet model (#178)
- V1.5.0

### Fixed

- Gate is_due on last attempt, not last success (stop retry-storm) (#170)
- Amplifier-verify reads worktree testplan + accepts 2-part TC-IDs (#172)
- Use git fetch + FETCH_HEAD for setup-review-dir.sh base branch (#175)
- Thread --repo-root so branch detection targets the right repo (#177)

## [1.3.3] - 2026-06-23

### Changed

- V1.3.3

### Fixed

- Stop agy_validate false-rejecting narrated reviews (#168)

## [1.3.2] - 2026-06-20

### Added

- Add CSV import for einvoice blank upload
- Add command
- Add Gmail scan task module
- Add Python dev quality toolchain (ruff, mypy, pre-commit, CI)
- Add .worktrees/ to .gitignore
- Add QA test suite covering all 3 task modules
- Add Gmail billing PDF pipeline with parsers and skill runbooks
- Add markdownlint-cli2 linter for markdown files
- Add parse_git_dir.py + fix Rule2 false positive + Protection 3 (#116)
- Add pr-review-cycle-mob skill for multi-model group PR review (#117)
- Add CLAUDE_EFFORT effort-level branching to all exec skills (#118) (#127)
- Add pre-merge bump-version reminder checkpoint (#131)
- Add exec wrapper deny-rule penetration section (#128)
- Add claude ultrareview as alternative cross-model review option (#129)
- Add CLAUDE_CODE_SESSION_ID and PostToolUse hook docs (#130)
- Add release pipeline with test gates and GitHub CI integration (#132)
- Add list_non_gstack_skills.sh to replace AP1 for-loop (#136)
- Add codex skill + install-force-one to reclaim gstack-overwritten skills (#139)
- Add effort level strategy with high as default (#142)
- Add SaaS invoice PDF amount extractor (#144)
- Add spectra plugin v0.1 -- openspec workflow packaging (#146)
- Add bilingual EN/ZH description of stack benefits and architecture (#1)
- Add GitHub Actions CI and release workflows (#5)
- Add PR #8 retro gotchas -- CI merge commit and --orphan (#10)
- Add Codex/Gemini extract pipeline to reduce token cost (#9)
- Add mob-detection cache to pr-review-cycle-mob
- Add make release target with plugin lockstep versioning (#11)
- Add trap ERR rollback pattern to bash-anti-patterns rule 13 (#15)
- Add process substitution multi-line read pattern to rule 13 (#16)
- Add Vertex AI auth detection for Gemini in mob review
- Add PR #13 lessons -- hook registration, scanner gate design
- Add deny list for destructive git/shell operations
- Add harness plugin (#17)
- Add lessons from PR #18 retro (#21)
- Add gemini allow-list patch script + mob review env check (#25)
- Add $? simple_expansion case + Gemini workspace sandbox note (#28)
- Add stderr routing and sentinel anti-pattern lessons from PR #31
- Add retro lessons from PR #25 (#26)
- Add fire-and-forget event logging to AP1/AP2 hooks (#35)
- Add audit log to AP1/AP2/smart-fix hooks + analysis CLI (#32)
- Add cross-doc cite verification rule (PR #415 retro) (#37)
- Add allow-list hygiene rule + extract PR review setup script (#39)
- Add D9 Subagents & D10 Navigation scanners; enhance D1/D2/D4 with v2 features (#30)
- Add upstream tracking check before git push (rule 15) (#33)
- Add revert PR pre-merge rebase checklist to rule 15 (#59)
- Add tasks.md for rules-english-recall-audit (#63)
- Add repeat-block analysis + transcript backfill (#68)
- Add no-capture hint to agy Stage 1 and Stage 2 (#70)
- Add code-reviewer agent fallback for CC < 2.1.146 (#75)
- Add MD028 blockquote + no-capture hint patterns to rule 11 (#71)
- Add .spectra.yaml
- Add /agy standalone Gemini review skill (#90)
- Add change spec
- Add /pr-review-cycle commands, drop /pr and codex skill (#97)
- Add writing plugin; move detect-ai-slop from 3rd-tools (#98)
- Add PATH= prefix, multi-line commit, output filter to rules-context.md (#107)
- Add retro lessons from PR #107 (#108)
- Add wrapper script to eliminate bash anti-pattern prompts (#109)
- Add gherkin-scenario-writer subagent + Step 1c parallel dispatch (#110)
- Add qa-test-designer subagent + methodology.md dual-track (Phase B) (#112)
- Add pull conflict resolver to avoid process substitution (#113)
- Add verify-done skill (#115)
- Add parallel pre-review check step (#116)
- Add writing plugin + agy/detect-ai-slop/claude-md-prune to README; fix Makefile status label (#120)
- Add /pr-cycle autonomous PR lifecycle orchestrator (#119)
- Add linter suppression tracking rule to 09-test-conventions (#122)
- Add markdownlint auto-fix hook and plugin version lockstep warn rule (#121)
- Add Codebase Research SOP to bash anti-patterns (#123)
- Add effectiveness review — structural eval works, token balance gap (#127)
- Add RFC 2119 severity standard to PR review cycle (#126)
- Add D11 Context / Token Economy dimension (#129)
- Add pr-control-log skill for AI behavior auditing (#135)

### Changed

- Initial commit
- Merge pull request #1 from howie/feat/csv-import-einvoice
- Merge pull request #2 from howie/feat/gmail-scan
- Merge pull request #3 from howie/feat/gmail-scan
- Merge pull request #4 from howie/feat/qa-tests
- Merge pull request #5 from howie/feat/gmail-billing
- Update gitignore
- Merge pull request #6 from howie/fix/billing-parsers
- Global CSV Schema 10 欄 + service enrichment + dbs_bank bug fix
- Merge pull request #7 from howie/feat/add-parser
- 合併 gmail-billing-monthly 並改善 gmail-scan/billing skills
- Merge pull request #9 from howie/feat/improve-gmail-skills
- 移除已完成的 docs/ 計畫文件
- 統一 runtime 檔案至 .runtime/ 目錄
- Merge pull request #10 from howie/feat/improve-gmail-skills
- 整合 my-skills 知識型 skill 至 monorepo
- Merge pull request #11 from howie/claude/ecstatic-lamarr
- Merge pull request #13 from howie/claude/build-agent-architecture-6Ze8p
- 移除硬編碼路徑、修復 mypy 143 errors、強化 CI 檢查
- Merge pull request #12 from howie/refactor/fix-paths-and-enforce-checks
- Update .gitignore
- 新增 icf-global-news-digest 知識型 skill
- 新增 protect-push skill — 防止 worktree branch 直推 origin/main
- Merge pull request #15 from howie/worktree-billing-handling
- 統一 output/ 目錄結構 + SKILL.md 加入 type 分類
- Merge pull request #16 from howie/refactor/output-dir-and-skill-type
- 新增 gmail-newsletter skill 與 scheduler 排程基礎設施
- 實作 CTBC/HNCB 信用卡 parser，修正 HSBC OCR 描述偏移，修復 format CSV 去重
- Merge pull request #17 from howie/feat/billing-parsers-dedup
- Merge pull request #18 from howie/feat/billing-parsers-dedup
- 新增 2024~2025 信用卡帳單交叉驗證與 HSBC 補匯入腳本
- Merge pull request #19 from howie/feat/billing-parsers-dedup
- Update gitignore
- Merge remote-tracking branch 'origin/main' into worktree-feat-import-newsletter-gmail
- Merge pull request #20 from howie/worktree-feat-import-newsletter-gmail
- 新增 .claude/rules/ 專案慣例指引
- Merge pull request #21 from howie/feat/claude-rules
- 安裝 steve-jobs-perspective skill (#26)
- 安裝 handover skill — 跨對話工作交班系統 (#27)
- 掃描富邦/國泰/永豐金證券月對帳單，彙整庫存股票總現值 (#25)
- 新增完整安裝指南與 Syncthing 同步支援 (#29)
- 安裝 flutter-tdd skill — Flutter TDD 專家知識型指引 (#30)
- Gwscli Go binary 取代 gws CLI，支援多帳號 OAuth (#31)
- 安裝 insight-collector skill — Stop hook 自動收集 ★ Insight 至 JSONL (#32)
- 新增 SaaS 發票追蹤 skill，使用 gwscli (#33)
- Rename agents→session-memory，建立 4 個 sub-agent 定義 (#35)
- 新增 spectra-amplifier 知識型 skill (#36)
- 新增 messages send 指令，icf-global-news-digest 改用 gwscli (#37)
- Newjob 改用 worktree-first 工作流，新增 learn skill (#38)
- 帳號自動偵測（Adapter Pattern，四層 fallback） (#39)
- Make install 自動 build Go binaries (#40)
- 將 Claude commands 移至 commands/ 並透過 make install 安裝至 user-level (#43)
- User-level commands、handover 跨機器路徑、PR review 修正
- 新增 AgentShield 安全掃描至 CI 流程 (#45)
- 建立 LedgerOne 帳單匯入 task module 與 skill (#48)
- 新增 auto-handover 三層防護，context 接近上限自動建議交班 (#49)
- 整合 session-memory 教訓，建立三源統一查詢入口 (#51)
- Merge pull request #51 from howie/feat/learn-session-memory-integration
- Auto-handover 成功率評估機制 Phase 1 (#53)
- 新增每日 AI 數位足跡聚合 skill (#52)
- 新增 SaaS 代墊請款 skill (#58)
- 新增 make ci 本地 CI fallback 指令 (#61)
- Merge pull request #65 from howie/fix/verify-ai-models-review
- Simplify hook scripts
- Merge pull request #64 from howie/worktree-debug-auto-handover
- 新增 Gemini 模型可用性驗證 skill (#62)
- 重構 verify-ai-models → verify-gemini-models，加入 Gemini 3.x global 端點支援 (#66)
- 加入 recap hook 收集 Claude Code away_summary (#68)
- 新增 ci-triage、new-task-module skill 與 PostToolUse mypy hook (#69)
- 新增 /debug_report skill — 除錯報告與清理儀式 (#70)
- 機器層 Port 分配登錄系統 (#71)
- Claude Code 為主要安裝目標，支援 npx skills (#75)
- 引入 scope frontmatter，區分全域與本 repo 限定 skill (#77)
- 用 heptabase CLI 自動推入 note (#76)
- 新增 pr-review-cycle-codex skill (#79)
- 新增 bash-anti-patterns skill、rule 與可選裝 PreToolUse hook (#81)
- 補充 bash-anti-patterns 5 秒自我檢查清單
- Revert "feat(rules): 補充 bash-anti-patterns 5 秒自我檢查清單"
- 補充 bash-anti-patterns 5 秒自我檢查清單 (#83)
- 補充 bash-anti-pattern-violations v2 規則素材 (#85)
- AP2 PreToolUse hook + Rule 14 shell quoting hygiene (#86)
- AP1 高頻違規速查 + PreToolUse hook + Cases 16-18 (#87)
- Simplify step before Review (#88)
- Bump-version -- cross-project version bump + CHANGELOG + commit-msg hook (#90)
- Copy .claude/settings.local.json into worktree (Step 2b) (#91)
- D class bash anti-pattern three-layer defense (Cases 25/26 + bash-to-script agent) (#92)
- 新增 anthropics/claude-code bash hook issues 追蹤 (#93)
- Bash anti-patterns v2 -- AP3 stateful cd + rule 14/15 + hook scope (#94)
- Heptabase-daily-journal -- nightly Heptabase journal update skill (#95)
- Patch-pr-review-agents -- auto-apply git -C rule to plugin agents (#96)
- Gbrain vs session-memory 優缺點分析 (#97)
- Flutter 專案同步 VERSION 純文字檔 (#101)
- SKILL.md bash anti-pattern lint + AP1 Detection-5 (#103)
- Pr-review-cycle 加入 Spectra Archive + Jira Sync 收尾步驟 (#106)
- Pr-retrospective skill + handover --exclude-tags discriminator (#108)
- Rule 13 新增「優先使用 Claude 內建工具搜尋程式碼」 (#109)
- Apply release note features (worktree.baseRef + CLAUDE_EFFORT) (#111)
- Bash-hygiene plugin + marketplace (#112)
- Smart-fix hook with auto-corrected command output (#115)
- Migrate gws to gwscli across SKILL.md / agents / tasks docs (#133)
- Simplify mob review threshold + add scope drift step (#135)
- Lesson routing classifier + /claude-md-prune skill (#145)
- Init yibi-stack public repo from ainization-skill
- Update skills/README.md to yibi-stack actual skills + spectra plan ADR
- Reorganize skills into 7 plugin packs for selective marketplace install (#3)
- Block worktree checkout of main/master (#8)
- Apply Claude Code 2026-W20 release notes (#12)
- Claude Code harness 就緒度評量 skill (#13)
- Enhance scanners + add harness-eval-focus sub-skill (#20)
- Rule 5 加入 multi-var 腳本拆解指引
- Step 3g -- Spectra version drift check (Layer 3A)
- Detection 6 -- block rg BRE backslash-pipe in ERE context (#22)
- Merge remote-tracking branch 'origin/main'
- Append PR #23 lessons to rules 13 and 14
- PR #303 retro -- hook doc verification + Gemini @file agentic mode warning (#34)
- FAQ for pr-test-analyzer test-design anti-patterns (#36)
- Land 3 retro lessons (rule 11 + rule 15) (#38)
- Migrate Gemini CLI → Antigravity CLI (agy) (#41)
- Append agy lessons from PR #41 retro (#45)
- Simplify comments and parser in PreCompact hook (#46)
- D9/D10/D4 improvements + mob-review Step 7 bug fix (#42)
- Audit log v2 + /recall command + pre-commit gate (#48)
- Promotion gate + rule consolidation (#50)
- Translate 01-language-and-tone to English
- Translate 03-security to English
- Translate 02-error-and-import to English
- Translate 15-irreversible-operations to English
- Translate 16-allowlist-hygiene to English
- Translate 13-bash-anti-patterns to English
- Replace --dangerously-skip-permissions with --sandbox
- Revert accidental direct push of 6 rules translations (#55)
- Add pre-registered protocol for pr-review-mob multi-tier A/B experiment (#51)
- Blank proposal.md gate for openspec changes (#54)
- Sunset gemini CLI scripts, sync --sandbox in docs (#57)
- Rules-english-recall-audit token optimization study (#53)
- Housekeeping -- commit weekly docs, spectra config, gitignore (#64)
- Integrate /less-permission-prompts guidance into rule 16 and bash-hygiene-audit (#66)
- Update harness-eval D2/D3/D4 rubric for Claude Code 2.1.133-2.1.150 (#67)
- Codify PR #68 lessons -- worktree gotcha + nosec conventions (#72)
- Skip mypy on CLAUDE_EFFORT=low + update CLAUDE.md gotchas (#69)
- Update harness-eval D2/D3/D4 rubric for CC 2.1.133-2.1.150 (#74)
- Translate 6 always-loaded rules to English (#77)
- Mark PR-C tasks done in rules-english-recall-audit
- Translate bash-anti-patterns SKILL.md body to English (#79)
- Record post-PR-C token actuals -- 35.9% reduction (#78)
- Translate pr-review-cycle and pr-review-cycle-mob SKILL.md body to English (#84)
- Enhance D5 scoring with three-sub-item semantic rubric (#83)
- Codify three lessons from PR #83 mob review (#87)
- Translate SKILL.md and .claude/rules/ body to English (pr-d batch2 + pr-e) (#86)
- Mark T-D1-D5 + T-E1-E9 done in tasks.md (#88)
- Translate protect-push SKILL.md body to English
- Typed lessons table with confidence scoring, decay, and /lessons command (#85)
- Translate spectra-amplifier and qa-test-design SKILL.md to English (Batch 4) (#89)
- Spectra upgrade settings + gitignore, remove archived changes
- Ignore spectra auto-generated AI tool files
- Ignore experiments/ directory
- Ignore spectra-generated slash commands and project config
- Mark T-D6-D10 done in tasks.md
- Rename session-memory → mycelium (#93)
- Append PR #92 retro lessons to rules/02, rules/13, CLAUDE.md (#94)
- Prune CLAUDE_EFFORT gotchas to rule 11, drop dup Search Strategy, add PR-91 lessons (#96)
- PR #97 lesson writebacks (#99)
- $CLAUDE_JOB_DIR Edit/Write permission 無法用 option 2 永久放行 (#100)
- Layered memory (#101)
- PR #101 lesson writebacks — module rename hook drift + idempotent schema migration (#106)
- Spectra-amplifier Wave D Phase 1 (#104)
- Append PR #112 retro lessons to rule 11 + CLAUDE.md (#114)
- Mark multitier A/B protocol HOLD — 0/16 trials (readout 2026-06-07)
- Append tool-output field verification + exit code lessons to rule 11 (#117)
- Nightly self-improvement agent (#118)
- Translate CLAUDE.md Known Gotchas to English; route 4 to rules (#124)
- SDD 三方比較研究 — Spec Kit / OpenSpec / Spectra × Teddy 五層約束 (#125)
- Prune CLAUDE.md and append PR #119 lessons (#128)
- Post-PR#130 cleanup -- lessons, ADR, remove weekly reports (#133)
- Align CLAUDE_JOB_DIR wording across rule 11 / 16 / pr-review-cycle-mob (#148)
- Rename lifecycle skills to fast/deep, upgrade amplifier-verifier (#150)
- Route PR #150 lessons to symlink gotcha and rule 11 sync section (#152)
- Retro lessons from PR #135 pr-control-log (#151)
- Post review summary to PR as a comment before fixes (#158)
- Codify PR #157 agy lessons into rule 13, pr-cycle-deep, CLAUDE.md (#159)
- V1.3.1 (#161)
- Default to silent cache reuse with auth re-verify (#164)
- V1.3.2

### Fixed

- Fix pytest testpaths and create test/docs directories
- Sync ruff version and add github_token to claude-code-action
- 修復 DBS CC parser 誤判亂碼 + 新增 card mapping 基礎
- 回應 code review — mypy hook 加 files filter、Dialog type annotation
- 修復 CI mypy/markdownlint 失敗
- 修正 icf-global-news-digest skill 分類與安全問題（PR review）
- 修復 protect-push hook 靜默失效與 SKILL.md 可攜性問題
- PR review 修復 — type 解析、目錄樹結構、docstring
- PR review 修復 — dedup、silent fallback、error handling
- 修正 sinopac_cc type annotations 與 hsbc_cc import-untyped
- 修正 PR review 發現的錯誤處理與靜默失敗問題
- 將 skill type 從 exec 更正為 tool (#28)
- 修復跨機器絕對路徑，支援多台機器共用 handover (#44)
- 修正 python3 -c 內嵌 try/except 語法錯誤 (#47)
- 擴充 protect-push 防護範圍至三個高風險操作 (#50)
- 修正 PR review 發現的五個問題
- 修正 working_dir 被 uv --directory 覆蓋為 skill_repo 路徑的問題 (#54)
- 修正 project 欄位永遠偵測為 ainization-skill 的問題 (#60)
- 修正 PR review 發現的所有問題
- 改善 PreCompact Hook 判斷邏輯
- 修正 markdownlint 與 ruff 錯誤
- 修正 GNU stat 造成第二次攔截 crash 的 bug
- 修正 FILE_MTIME=0 永遠過期 bug + 補 disown
- 修正 markdownlint MD032 list blank lines
- 明確捕捉 test_metrics_eg_001 的預期 UserWarning (#67)
- Detect_project() 在 worktree 下回傳主 repo 名稱 (#72)
- 新增 Makefile hook target，修補安裝路徑碎片化 (#73)
- 移除全域 docker compose，補齊 Step 3 bash guard (#78)
- Handover/handover-back 改用 jq，移除 inline Python (#80)
- Pr-review-cycle-codex 補 codex CLI flag 相容性 fallback (#84)
- 修正 Case 18/19 complexity score 及補 skills/.claude gitignore (#89)
- 修正 bash 指令字串內的 emoji 與 em dash（Anti-Pattern 2） (#82)
- 以 git rev-parse --show-toplevel 取代 CLAUDE_PROJECT_DIR (#98)
- 修正 newjob.md bash anti-pattern 違規（AP1/AP2/AP3） (#99)
- Handover/session-memory bash anti-patterns + AP2 hook tests (#102)
- Fix jq single-quoted filter in subshell triggers CC static analyzer (#104)
- Bump-version 消除 bash+SKILL_DIR 反模式 (#105)
- 遷移 jq skill_repo 至 python3 -c，消除 CC 確認框（Case 27） (#107)
- Pr-review-cycle-codex -- 前置需求 bash 去除 expansion/simple_expansion (#100)
- 修正 newjob.md bash anti-pattern 違規（Case 28） (#110)
- Pr-review-cycle-codex Step 7 fallback add -C flag (AP3 Sub-class A)
- Correct repository owner from ainization to howie (#114)
- Handle git -C worktree paths + block push on main (#113)
- Eliminate bash anti-patterns causing confirmation prompts (#134)
- V0.2.1 fix(skills): fix bash anti-patterns in pr-review-cycle skills (#138)
- Guard against worktree checking out main branch (#141)
- Fix Gemini auth detection for gemini-credentials.json (#4)
- Re-enable all markdownlint rules and fix violations
- Fix skill README classification rule, auth regex, and make target naming (#6)
- Namespace /tmp/pr-review by worktree to prevent parallel session clashes (#14)
- D4 scanner fallback to skills/ for source repos (#18)
- Use single quotes for python3 -c to fix Unhandled node type: string hook (#19)
- Extend git commit exemption to cover git -C /path commit form (#23)
- Prohibit echo exit pattern in Gemini Stage 1 (#24)
- Move REVIEW_DIR to worktree root + fix codex stdout capture (#29)
- Gracefully handle missing gitCommitSha field (#31)
- Extract 6 inline bash blocks to scripts (#40)
- 移除 PreCompact hook 的冗餘 matcher 雙重檢查 (#44)
- Apply Round 2 review fixes
- Replace brace+quote error pattern with if/fi form (#47)
- Eliminate all AP1/AP2 violations across plugins + Makefile (#43)
- Fix E501 in hook tests and align make lint scope with CI (#49)
- Resolve markdownlint violations from PR #59 + disable MD060 (#60)
- Switch BASE_BRANCH/GEMINI_MODEL from env var to positional param
- Replace /simplify with /code-review in PR cycle skills (2.1.147) (#62)
- Replace git rev-parse with CLAUDE_PROJECT_DIR in settings.json (#65)
- Extract Step 0 bash to scripts, eliminating confirm dialogs (#73)
- Rename /learn->recall + agy stage2 JSON extraction with dead guard removed (#76)
- Resolve stash-pop conflicts in enhance-d5-behavior-harness, keep upstream version
- Skip skills/openspec/ ghost dir in install loop (#91)
- Exempt python -m tasks.session_memory arg values from AP2 scan (#92)
- Replace heredoc-in-quotes antipattern with --body-file / -F (#95)
- Extract handover-read to script, fix Quoting Rule 5 violations (#103)
- Extract bash blocks to scripts — eliminate 4x Contains expansion dialogs (#111)
- D3 Grep tool first, ADR-0002 for CC parser bug, regression test (v1.3.0) (#130)
- Replace /recall with /lessons find (#155)
- Harden agy review against nested-worktree agentic failures (#153) (#156)
- Feed review prompt via stdin to avoid nested-worktree agentic failures (#157)
- Honor GH_REPO when resolving repo slug in detect (#160)
- Gate plugin-agent dispatch + align skill/plugin scope (#163)
- Release.sh unbound-var + changelog.sh MD012/duplicate (#162)

### Removed

- Remove bash anti-patterns triggering CC confirmation dialogs (#137)
- Remove unnecessary rm-f after git commit-F (#105)

[1.12.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.11.0..v1.12.0
[1.11.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.10.0..v1.11.0
[1.10.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.9.0..v1.10.0
[1.9.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.8.0..v1.9.0
[1.8.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.7.0..v1.8.0
[1.7.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.6.0..v1.7.0
[1.6.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.5.2..v1.6.0
[1.5.2]: https://github.com/heyu-ai/yibi-stack/compare/v1.5.1..v1.5.2
[1.5.1]: https://github.com/heyu-ai/yibi-stack/compare/v1.5.0..v1.5.1
[1.5.0]: https://github.com/heyu-ai/yibi-stack/compare/v1.3.3..v1.5.0
[1.3.3]: https://github.com/heyu-ai/yibi-stack/compare/v1.3.2..v1.3.3
[1.3.2]: https://github.com/heyu-ai/yibi-stack/compare/v1.3.1..v1.3.2

<!-- generated by git-cliff -->

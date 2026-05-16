# commit-convention.yaml — 專案 commit message 設定
# 由 bump-version skill 的 init-commit-hook 自動產生
# 請依專案需求調整

# 允許的 commit type（Conventional Commits 標準）
types:
  - feat
  - fix
  - docs
  - style
  - refactor
  - perf
  - test
  - build
  - ci
  - chore
  - revert

# 是否強制要求 scope（true = feat(scope): ... 的 scope 不能省略）
require_scope: false

# subject 最大字元數（含 type(scope): 前綴）
max_subject_length: 72

# Ticket 編號 pattern（空字串 = 不驗證）
# 範例（Jira）："(PROJ|MYTEAM)-[0-9]+"
# 範例（GitHub issue）："#[0-9]+"
ticket_pattern: ""

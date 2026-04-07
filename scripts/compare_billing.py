"""
2024~2025 信用卡帳單 vs 記帳 App 交叉驗證腳本
"""

from __future__ import annotations

import glob
import sys

import pandas as pd
from sqlalchemy import create_engine, text

# ─────────────────────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────────────────────

DB_URL = "postgresql+psycopg2://ledgerone:ledgerone@localhost:5435/ledgerone"
BILLING_DIR = "/Users/howie/Workspace/github/ainization-skill/billing_output/format"

LEDGER_2024 = "43870718-dab4-44d7-90c6-3be401c977d7"
LEDGER_2025 = "0831287f-ab9b-408e-917a-2d2295cf0c18"

# billing CSV 的 bank 欄位 → 記帳 App 的銀行群組名稱
BANK_MAP = {
    "中國信託": "中國信託信用卡",
    "匯豐銀行信用卡": "匯豐信用卡",
    "國泰世華": "國泰世華信用卡",
    "永豐銀行信用卡": "永豐信用卡",
    "華南銀行信用卡": "華南信用卡",
}

TARGET_BANKS = set(BANK_MAP.values())


# ─────────────────────────────────────────────────────────────────────────────
# 讀取 billing CSV
# ─────────────────────────────────────────────────────────────────────────────


def load_billing_data() -> pd.DataFrame:
    files = sorted(glob.glob(f"{BILLING_DIR}/202[45]*-credit_card.csv"))
    # Filter only 2024 and 2025
    files = [f for f in files if any(f"/{y}-" in f for y in ["2024", "2025"])]
    if not files:
        print("❌ 找不到 billing CSV 檔案", file=sys.stderr)
        sys.exit(1)

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
            dfs.append(df)
        except Exception as e:
            print(f"⚠️  讀取 {f} 失敗: {e}", file=sys.stderr)

    if not dfs:
        print("❌ 沒有可讀取的 CSV 檔案", file=sys.stderr)
        sys.exit(1)
    billing = pd.concat(dfs, ignore_index=True)
    billing["date"] = pd.to_datetime(billing["date"])
    billing["month"] = billing["date"].dt.to_period("M").astype(str)
    billing["amount"] = pd.to_numeric(billing["amount"], errors="coerce").fillna(0)
    # 只保留正數（消費），排除退款
    billing = billing[billing["amount"] > 0]
    # 對映 bank 名稱
    billing["bank_group"] = billing["bank"].map(BANK_MAP)
    billing = billing[billing["bank_group"].notna()]
    return billing


# ─────────────────────────────────────────────────────────────────────────────
# 讀取記帳 App 資料
# ─────────────────────────────────────────────────────────────────────────────

QUERY = """
SELECT
    TO_CHAR(t.date, 'YYYY-MM') AS month,
    p.name AS bank,
    fa.name AS card,
    t.description,
    t.amount
FROM transactions t
JOIN accounts fa ON t.from_account_id = fa.id
JOIN accounts p  ON fa.parent_id      = p.id
WHERE t.ledger_id = :ledger_id ::uuid
  AND fa.type     = 'LIABILITY'
  AND fa.depth    = 3
  AND p.name      = ANY(:banks)
ORDER BY month, bank, card
"""


def load_app_data() -> pd.DataFrame:
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        rows_2024 = pd.read_sql(
            text(QUERY),
            conn,
            params={"ledger_id": LEDGER_2024, "banks": list(TARGET_BANKS)},
        )
        rows_2025 = pd.read_sql(
            text(QUERY),
            conn,
            params={"ledger_id": LEDGER_2025, "banks": list(TARGET_BANKS)},
        )
    df = pd.concat([rows_2024, rows_2025], ignore_index=True)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 比對
# ─────────────────────────────────────────────────────────────────────────────


def build_pivot(df: pd.DataFrame, value_col: str, bank_col: str) -> pd.DataFrame:
    grouped = df.groupby(["month", bank_col])[value_col].sum().reset_index()
    pivot = grouped.pivot(index="month", columns=bank_col, values=value_col).fillna(0)
    pivot["月小計"] = pivot.sum(axis=1)
    return pivot


def print_comparison(billing: pd.DataFrame, app: pd.DataFrame) -> None:
    # ── 月份 × 銀行 加總 ───────────────────────────────────────────────────
    b_pivot = build_pivot(billing, "amount", "bank_group")
    a_pivot = build_pivot(app, "amount", "bank")

    # 對齊月份
    all_months = sorted(set(b_pivot.index) | set(a_pivot.index))
    all_banks = sorted(TARGET_BANKS)

    print("\n" + "═" * 100)
    print("📊  2024~2025 信用卡帳單 vs 記帳 App 月度比對（按銀行）")
    print("═" * 100)
    print(
        f"\n{'月份':<10}  {'銀行':<14}  {'帳單(TWD)':>12}  {'記帳App(TWD)':>13}  {'差異':>12}  狀態"
    )
    print("-" * 80)

    issues: list[tuple] = []
    for month in all_months:
        for bank in all_banks:
            b_amt = (
                float(b_pivot.loc[month, bank])
                if month in b_pivot.index and bank in b_pivot.columns
                else 0.0
            )
            a_amt = (
                float(a_pivot.loc[month, bank])
                if month in a_pivot.index and bank in a_pivot.columns
                else 0.0
            )
            diff = a_amt - b_amt
            pct = abs(diff) / b_amt * 100 if b_amt > 0 else 0
            if b_amt == 0 and a_amt == 0:
                continue
            status = "✅" if abs(diff) < 500 or pct < 5 else ("⚠️" if pct < 20 else "❌")
            print(
                f"{month:<10}  {bank:<14}  {b_amt:>12,.0f}  {a_amt:>13,.0f}  {diff:>+12,.0f}  {status}"
            )
            if status != "✅":
                issues.append((month, bank, b_amt, a_amt, diff, pct))

    # ── 年度加總比對 ────────────────────────────────────────────────────────
    print("\n" + "═" * 80)
    print("📈  年度加總比對")
    print("═" * 80)
    for year in ["2024", "2025"]:
        b_year = billing[billing["month"].str.startswith(year)]["amount"].sum()
        a_year = app[app["month"].str.startswith(year)]["amount"].sum()
        diff = a_year - b_year
        pct = abs(diff) / b_year * 100 if b_year > 0 else 0
        status = "✅" if pct < 5 else "⚠️"
        print(
            f"  {year} 年  帳單: {b_year:>10,.0f}  記帳App: {a_year:>10,.0f}  差異: {diff:>+10,.0f}  ({pct:.1f}%)  {status}"
        )

    # ── 記帳 App 科目分類統計 ──────────────────────────────────────────────
    print("\n" + "═" * 80)
    print("🏷️   記帳 App 信用卡科目分類統計（2024~2025）")
    print("═" * 80)
    query_cat = text("""
    SELECT
        ta.name AS category,
        COUNT(*) AS txn_count,
        SUM(t.amount) AS total
    FROM transactions t
    JOIN accounts fa ON t.from_account_id = fa.id
    JOIN accounts p  ON fa.parent_id      = p.id
    JOIN accounts ta ON t.to_account_id   = ta.id
    WHERE t.ledger_id = ANY(ARRAY[:l2024, :l2025]::uuid[])
      AND fa.type  = 'LIABILITY'
      AND fa.depth = 3
      AND p.name   = ANY(:banks)
      AND t.date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY ta.name
    ORDER BY total DESC
    LIMIT 20
    """)
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        cat_df = pd.read_sql(
            query_cat,
            conn,
            params={"l2024": LEDGER_2024, "l2025": LEDGER_2025, "banks": list(TARGET_BANKS)},
        )
    print(f"\n{'科目':<20}  {'筆數':>6}  {'金額(TWD)':>12}")
    print("-" * 44)
    for _, row in cat_df.iterrows():
        print(f"  {row['category']:<18}  {int(row['txn_count']):>6}  {float(row['total']):>12,.0f}")

    # ── 異常摘要 ────────────────────────────────────────────────────────────
    if issues:
        print(f"\n{'═' * 80}")
        print(f"⚠️   需注意的差異（{len(issues)} 筆）")
        print("═" * 80)
        for month, bank, b, a, d, pct in issues:
            print(
                f"  {month}  {bank:<14}  帳單:{b:>10,.0f}  記帳:{a:>10,.0f}  差{d:>+10,.0f}  ({pct:.1f}%)"
            )
    else:
        print("\n✅  所有月份差異均在合理範圍內")


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("⏳  載入 billing CSV...")
    billing = load_billing_data()
    print(f"   → {len(billing):,} 筆交易，{billing['month'].nunique()} 個月份")

    print("⏳  載入記帳 App 資料...")
    app = load_app_data()
    print(f"   → {len(app):,} 筆交易，{app['month'].nunique()} 個月份")

    print_comparison(billing, app)

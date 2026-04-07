"""
2024~2025 信用卡完整消費報表（含科目分類）
"""

from __future__ import annotations

import glob
import sys

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://ledgerone:ledgerone@localhost:5435/ledgerone"
BILLING_DIR = "/Users/howie/Workspace/github/ainization-skill/billing_output/format"
LEDGER_2024 = "43870718-dab4-44d7-90c6-3be401c977d7"
LEDGER_2025 = "0831287f-ab9b-408e-917a-2d2295cf0c18"

BANK_MAP = {
    "中國信託": "中國信託信用卡",
    "匯豐銀行信用卡": "匯豐信用卡",
    "國泰世華": "國泰世華信用卡",
    "永豐銀行信用卡": "永豐信用卡",
    "華南銀行信用卡": "華南信用卡",
}
TARGET_BANKS = set(BANK_MAP.values())

# ─── 讀取 billing CSV ────────────────────────────────────────────────────────


def load_billing() -> pd.DataFrame:
    files = sorted(glob.glob(f"{BILLING_DIR}/20[24-25]*-credit_card.csv"))
    files = [f for f in files if any(f"/{y}-" in f for y in ["2024", "2025"])]
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
            dfs.append(df)
        except Exception as e:
            print(f"⚠️  {f}: {e}", file=sys.stderr)
    df = pd.concat(dfs, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["year"] = df["date"].dt.year.astype(str)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df = df[df["amount"] > 0]
    df["bank_group"] = df["bank"].map(BANK_MAP)
    df = df[df["bank_group"].notna()]
    return df


# ─── 讀取記帳 App（含科目分類） ──────────────────────────────────────────────

QUERY_CAT = text("""
SELECT
    TO_CHAR(t.date, 'YYYY-MM') AS month,
    EXTRACT(YEAR FROM t.date)::int AS year,
    p.name AS bank,
    fa.name AS card,
    ta.name AS category,
    COUNT(*) AS cnt,
    SUM(t.amount) AS total
FROM transactions t
JOIN accounts fa ON t.from_account_id = fa.id
JOIN accounts p  ON fa.parent_id      = p.id
JOIN accounts ta ON t.to_account_id   = ta.id
WHERE t.ledger_id = :lid ::uuid
  AND fa.type  = 'LIABILITY'
  AND fa.depth = 3
  AND p.name   = ANY(:banks)
GROUP BY month, year, bank, card, category
ORDER BY month, bank, card
""")


def load_app() -> pd.DataFrame:
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        df24 = pd.read_sql(
            QUERY_CAT, conn, params={"lid": LEDGER_2024, "banks": list(TARGET_BANKS)}
        )
        df25 = pd.read_sql(
            QUERY_CAT, conn, params={"lid": LEDGER_2025, "banks": list(TARGET_BANKS)}
        )
    df = pd.concat([df24, df25], ignore_index=True)
    df["total"] = pd.to_numeric(df["total"], errors="coerce").fillna(0)
    df["year"] = df["year"].astype(str)
    return df


# ─── 報表輸出 ────────────────────────────────────────────────────────────────


def print_report(billing: pd.DataFrame, app: pd.DataFrame) -> None:

    # ── 1. 月度總消費（billing 來源） ─────────────────────────────────────
    print("═" * 70)
    print("📊  2024~2025 信用卡月度消費摘要（帳單 PDF 來源）")
    print("═" * 70)
    monthly = billing.groupby(["year", "month", "bank_group"])["amount"].sum().reset_index()
    for year in ["2024", "2025"]:
        ym = monthly[monthly["year"] == year]
        year_total = ym["amount"].sum()
        print(f"\n── {year} 年  合計：{year_total:,.0f} TWD ──────────────────")
        pivot = ym.pivot_table(
            index="month", columns="bank_group", values="amount", aggfunc="sum", fill_value=0
        )
        pivot["月小計"] = pivot.sum(axis=1)
        print(pivot.map(lambda x: f"{x:,.0f}").to_string())

    # ── 2. 年度科目分類（記帳 App 來源） ───────────────────────────────────
    print("\n\n" + "═" * 70)
    print("🏷️   2024~2025 信用卡消費科目分類（記帳 App 分類）")
    print("═" * 70)
    for year in ["2024", "2025"]:
        ay = app[app["year"] == year]
        cat_summary = ay.groupby("category")["total"].sum().sort_values(ascending=False)
        year_total = cat_summary.sum()
        print(f"\n── {year} 年  已記帳合計：{year_total:,.0f} TWD ──────────────────")
        print(f"  {'科目':<20}  {'金額':>12}  {'佔比':>7}")
        print("  " + "-" * 45)
        for cat, amt in cat_summary.items():
            pct = amt / year_total * 100 if year_total > 0 else 0
            print(f"  {cat:<20}  {amt:>12,.0f}  {pct:>6.1f}%")

    # ── 3. 各卡年度消費 ─────────────────────────────────────────────────
    print("\n\n" + "═" * 70)
    print("💳  各信用卡年度消費（帳單來源）")
    print("═" * 70)
    card_year = billing.groupby(["year", "bank_group", "card"])["amount"].sum().reset_index()
    for year in ["2024", "2025"]:
        cy = card_year[card_year["year"] == year].sort_values("amount", ascending=False)
        print(f"\n── {year} 年 ──────────────────────────────────")
        print(f"  {'銀行':<14}  {'卡片':<16}  {'金額':>12}")
        print("  " + "-" * 48)
        for _, r in cy.iterrows():
            print(f"  {r['bank_group']:<14}  {r['card']:<16}  {r['amount']:>12,.0f}")
        print(f"  {'合計':>32}  {cy['amount'].sum():>12,.0f}")

    # ── 4. 大額單筆消費（>= 10,000） ───────────────────────────────────
    print("\n\n" + "═" * 70)
    print("💰  大額單筆消費（帳單 >= 10,000 TWD）")
    print("═" * 70)
    big = billing[billing["amount"] >= 10000].sort_values("amount", ascending=False)
    print(f"\n  {'日期':<12}  {'銀行':<14}  {'卡片':<14}  {'金額':>10}  說明")
    print("  " + "-" * 80)
    for _, r in big.head(30).iterrows():
        desc = str(r["description"])[:30] if pd.notna(r["description"]) else ""
        print(
            f"  {str(r['date'].date()):<12}  {r['bank_group']:<14}  {r['card']:<14}  {r['amount']:>10,.0f}  {desc}"
        )
    if len(big) > 30:
        print(f"  ... 共 {len(big)} 筆大額消費")


if __name__ == "__main__":
    print("⏳  載入 billing CSV...")
    billing = load_billing()
    print(f"   → {len(billing):,} 筆，{billing['month'].nunique()} 個月份")

    print("⏳  載入記帳 App...")
    app = load_app()
    print(f"   → {len(app):,} 筆（含科目分類）")

    print_report(billing, app)

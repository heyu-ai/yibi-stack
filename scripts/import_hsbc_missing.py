"""
匯豐信用卡缺漏資料 import 腳本（2025-07 ~ 2025-12）
直接讀取 billing_output/format/ CSV，透過 API 建立交易。
"""

from __future__ import annotations

import sys

import pandas as pd
import requests
from sqlalchemy import create_engine, text

# ─────────────────────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8100/api/v1"
API_TOKEN = "ldo_3TUYUNeHTac6Yw8-qtPeWHSxWXVpkOD9Sqwy4Mns8_vGjzIm"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}

LEDGER_2025 = "0831287f-ab9b-408e-917a-2d2295cf0c18"
DB_URL = "postgresql+psycopg2://ledgerone:ledgerone@localhost:5435/ledgerone"

BILLING_DIR = "/Users/howie/Workspace/github/ainization-skill/billing_output/format"
TARGET_MONTHS = ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]

# billing CSV card 欄位 → 記帳 App account ID
CARD_ID_MAP = {
    "旅人無限卡": "10e77310-dd57-47cf-97ab-7de8a1541e17",  # 旅人正卡
    "匯豐現金回饋御璽卡": "9c2f60c2-c1ef-4858-93fb-091ad84f4e26",  # 匯鑽卡
    "匯豐LIVE+現金回饋卡": "68a7956d-dfad-4542-a94f-d987bf32f20b",  # Live+
    "3872": "940c145f-4d2a-4fde-a91a-c7fa92138c46",  # 匯鑽附卡
    "現金回饋": "a12309ca-d457-4d54-b58b-a56e1a9dc788",  # 現金回饋
}
DEFAULT_CARD_ID = "10e77310-dd57-47cf-97ab-7de8a1541e17"  # 旅人正卡 fallback
DEFAULT_EXPENSE_ID = "fff145dc-fa92-4e4f-b902-479e60a1199c"  # 其他支出


# ─────────────────────────────────────────────────────────────────────────────
# 讀取已有交易（用於 dedup）
# ─────────────────────────────────────────────────────────────────────────────


def load_existing_keys() -> set[tuple]:
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
            SELECT t.date, t.amount, t.description, t.from_account_id
            FROM transactions t
            JOIN accounts fa ON t.from_account_id = fa.id
            JOIN accounts p  ON fa.parent_id = p.id
            WHERE t.ledger_id = :lid ::uuid
              AND p.name = '匯豐信用卡'
              AND t.date BETWEEN '2025-07-01' AND '2025-12-31'
        """),
            {"lid": LEDGER_2025},
        ).fetchall()
    return {(str(r[0]), str(r[1]), r[2], str(r[3])) for r in rows}


# ─────────────────────────────────────────────────────────────────────────────
# 讀取 billing CSV
# ─────────────────────────────────────────────────────────────────────────────


def load_billing_hsbc() -> pd.DataFrame:
    dfs = []
    for month in TARGET_MONTHS:
        f = f"{BILLING_DIR}/{month}-credit_card.csv"
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
            dfs.append(df)
        except FileNotFoundError:
            print(f"⚠️  找不到 {f}", file=sys.stderr)
    if not dfs:
        print("❌ 找不到任何 CSV", file=sys.stderr)
        sys.exit(1)

    df = pd.concat(dfs, ignore_index=True)
    # 只保留匯豐信用卡
    df = df[df["bank"] == "匯豐銀行信用卡"].copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df[df["amount"] > 0]  # 排除退款
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 建立交易
# ─────────────────────────────────────────────────────────────────────────────


def create_transaction(
    date: str, amount: float, description: str, from_id: str, to_id: str, notes: str
) -> bool:
    payload = {
        "date": date,
        "amount": str(round(amount, 2)),
        "description": description[:255],
        "from_account_id": from_id,
        "to_account_id": to_id,
        "transaction_type": "EXPENSE",
        "notes": notes[:500] if notes else "",
    }
    r = requests.post(
        f"{API_BASE}/ledgers/{LEDGER_2025}/transactions",
        headers=HEADERS,
        json=payload,
        timeout=10,
    )
    if r.status_code in (200, 201):
        return True
    print(f"  ❌ {r.status_code}: {r.text[:200]}", file=sys.stderr)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────="────────
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("⏳  載入已有匯豐交易（dedup）...")
    existing = load_existing_keys()
    print(f"   → 已有 {len(existing)} 筆")

    print("⏳  載入 billing CSV...")
    df = load_billing_hsbc()
    print(f"   → {len(df)} 筆匯豐消費（{', '.join(TARGET_MONTHS)}）")

    imported = skipped = failed = 0
    month_stats: dict[str, dict] = {}

    for _, row in df.iterrows():
        month = row["date"][:7]
        card_name = str(row["card"]) if pd.notna(row["card"]) else ""
        from_id = CARD_ID_MAP.get(card_name, DEFAULT_CARD_ID)
        amount = float(row["amount"])
        desc = str(row["description"]) if pd.notna(row["description"]) else ""
        date = row["date"]
        notes = f"card:{card_name}" if card_name else ""

        dedup_key = (date, f"{amount:.2f}", desc, from_id)
        if dedup_key in existing:
            skipped += 1
            month_stats.setdefault(month, {"ok": 0, "skip": 0, "fail": 0})["skip"] += 1
            continue

        ok = create_transaction(date, amount, desc, from_id, DEFAULT_EXPENSE_ID, notes)
        month_stats.setdefault(month, {"ok": 0, "skip": 0, "fail": 0})
        if ok:
            imported += 1
            month_stats[month]["ok"] += 1
            existing.add(dedup_key)
        else:
            failed += 1
            month_stats[month]["fail"] += 1

    print("\n" + "═" * 60)
    print("📥  匯豐缺漏資料匯入報告")
    print("═" * 60)
    print(f"\n{'月份':<10}  {'匯入':>6}  {'跳過':>6}  {'失敗':>6}")
    print("-" * 35)
    for month in sorted(month_stats):
        s = month_stats[month]
        print(f"{month:<10}  {s['ok']:>6}  {s['skip']:>6}  {s['fail']:>6}")
    print("-" * 35)
    print(f"{'合計':<10}  {imported:>6}  {skipped:>6}  {failed:>6}")
    print(f"\n{'✅ 完成' if failed == 0 else '⚠️  有失敗'}")


if __name__ == "__main__":
    main()

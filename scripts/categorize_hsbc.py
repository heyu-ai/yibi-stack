"""
用 Claude API 批次分類 241 筆匯豐信用卡消費
"""

from __future__ import annotations

import sys
import time

import anthropic
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://ledgerone:ledgerone@localhost:5435/ledgerone"
API_BASE = "http://localhost:8100/api/v1"
API_TOKEN = "ldo_3TUYUNeHTac6Yw8-qtPeWHSxWXVpkOD9Sqwy4Mns8_vGjzIm"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}
LEDGER_2025 = "0831287f-ab9b-408e-917a-2d2295cf0c18"

# ── 科目清單（name → id） ────────────────────────────────────────────────────
EXPENSE_ACCOUNTS = {
    "國外旅遊": "32cf5523-823e-4652-8602-a620705c9441",
    "國內旅遊": "ee781d46-a894-4ecf-b6e3-23f027c8a281",
    "里程數成本": "e327afb8-3305-43ce-9025-e6d30fa1467c",
    "旅行裝備": "7959ac10-5958-48bb-85ad-afa606f18a06",
    "旅費": "2cdfc1c9-5c03-4bcd-9a46-ab76e20eb9a8",
    "手續費": "2f640d74-e9f1-4b58-ba3a-a44bbd414673",
    "醫療": "f35f771f-499e-4762-9adb-a2510e78a89e",
    "保健": "e75156a6-086b-4318-8322-b074d728aaec",
    "保險費": "46292bc1-7eb1-4928-b165-831583ac2ab1",
    "家庭三餐": "5a0e86b1-fd14-42ab-84e1-54df06be1a64",  # filled below if needed
    "餐飲": "5a0e86b1-fd14-42ab-84e1-54df06be1a64",
    "看電影": "de1824e9-d735-4ec0-ae83-60c1b734409e",
    "線上視頻": "c9a291b3-8199-48a0-b1db-38f57cb60dd6",
    "書籍": "5ac1fcb0-4801-4cc4-b82f-839563f31a82",
    "訂閱學習": "988c6df7-a7a6-4bce-8b6f-56ea6d2b2b21",
    "生產力工具": "af78c62e-8d88-41f8-9be1-8c2e1aa2cc0a",
    "系統維運": "356800e8-c368-4551-9972-7bacba7d2a00",
    "3C設備": "417bd185-0c4e-487b-984e-9da1e1902f20",
    "信用卡": "74991a46-96b1-4f85-93e6-ae0bb4b7c7a6",
    "捐獻": "3763b619-de6e-4203-95e5-cfe8c9e14317",
    "十一奉獻": "3763b619-de6e-4203-95e5-cfe8c9e14317",
    "教育支出": "bda2dba9-d44a-47ee-ae72-0219ac3a57d7",
    "稅": "6f92fdc4-bb84-44e3-af40-463a1f1b8f38",
    "公司款項": "51e65832-1981-4973-89e5-fc6a777324a5",
    "一般代刷": "da57d6a2-abe4-4350-942e-d4700ef473f4",
    "其他支出": "fff145dc-fa92-4e4f-b902-479e60a1199c",
}

SYSTEM_PROMPT = """你是一個記帳分類助手。根據信用卡交易描述，從以下科目清單選出最合適的一個科目名稱。

可用科目：
- 國外旅遊：在國外的餐廳、景點、住宿、交通（非里程換購）
- 里程數成本：用里程或點數換購機票、升等、飯店（POINTS/PTS/MILES/ATROO/PRIVILEGECLUB）
- 旅行裝備：行李、旅遊用品、旅遊保險
- 旅費：機票（現金購買）、高鐵、捷運、巴士（旅行相關）
- 手續費：國外交易手續費（描述包含「手續費」）
- 醫療：醫院、診所、藥局
- 保健：健身、保健食品、spa
- 保險費：保險
- 看電影：電影院
- 線上視頻：Netflix、Disney+等影音
- 書籍：書店、電子書
- 訂閱學習：Udemy、Coursera等學習平台
- 生產力工具：Notion、1Password等工作工具
- 系統維運：網域、主機、雲端服務（工作）
- 3C設備：電子產品
- 信用卡：年費、帳單手續費
- 捐獻：教會、慈善
- 稅：稅款
- 公司款項：公司相關報銷
- 一般代刷：幫別人代刷
- 其他支出：以上都不符合時使用

只回傳科目名稱，不加任何解釋或標點。"""

# ── 讀取待分類交易 ───────────────────────────────────────────────────────────


def load_txns() -> list[dict]:
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
            SELECT t.id, t.date, t.description, t.amount, fa.name as card
            FROM transactions t
            JOIN accounts fa ON t.from_account_id = fa.id
            JOIN accounts p  ON fa.parent_id = p.id
            JOIN accounts ta ON t.to_account_id = ta.id
            WHERE t.ledger_id = :lid ::uuid
              AND p.name = '匯豐信用卡'
              AND ta.name = '其他支出'
              AND t.date >= '2025-07-01'
            ORDER BY t.date
        """),
            {"lid": LEDGER_2025},
        ).fetchall()
    return [
        {"id": str(r[0]), "date": str(r[1]), "desc": r[2], "amount": float(r[3]), "card": r[4]}
        for r in rows
    ]


# ── Claude 分類（批次，每次最多 30 筆） ─────────────────────────────────────


def classify_batch(client: anthropic.Anthropic, txns: list[dict]) -> dict[str, str]:
    lines = "\n".join(
        f"{i + 1}. [{t['date']}] {t['desc']} (${t['amount']:.0f})" for i, t in enumerate(txns)
    )
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"請分類以下交易，每行只輸出科目名稱（共 {len(txns)} 行）：\n\n{lines}",
            }
        ],
    )
    cats = [line.strip() for line in resp.content[0].text.strip().split("\n") if line.strip()]
    return {txns[i]["id"]: cats[i] if i < len(cats) else "其他支出" for i in range(len(txns))}


# ── 批次更新 to_account_id（直接 SQL） ─────────────────────────────────────


def bulk_update(results: dict[str, str]) -> tuple[int, int]:
    engine = create_engine(DB_URL)
    ok = fail = 0
    with engine.begin() as conn:
        for txn_id, cat in results.items():
            account_id = EXPENSE_ACCOUNTS.get(cat, EXPENSE_ACCOUNTS["其他支出"])
            try:
                conn.execute(
                    text(
                        "UPDATE transactions SET to_account_id = :aid ::uuid WHERE id = :tid ::uuid"
                    ),
                    {"aid": account_id, "tid": txn_id},
                )
                ok += 1
            except Exception as e:
                print(f"  ❌ {txn_id}: {e}", file=sys.stderr)
                fail += 1
    return ok, fail


# ── 主流程 ───────────────────────────────────────────────────────────────────


def main() -> None:
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY from env

    print("⏳  載入待分類交易...")
    txns = load_txns()
    print(f"   → {len(txns)} 筆")

    BATCH = 30
    results: dict[str, str] = {}
    for i in range(0, len(txns), BATCH):
        batch = txns[i : i + BATCH]
        print(f"   分類 {i + 1}~{i + len(batch)}...", end="", flush=True)
        r = classify_batch(client, batch)
        results.update(r)
        print(" ✓")
        if i + BATCH < len(txns):
            time.sleep(0.5)

    # 統計分類結果
    cat_counts: dict[str, int] = {}
    for cat in results.values():
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print("\n分類統計：")
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        known = "✓" if cat in EXPENSE_ACCOUNTS else "?"
        print(f"  {known} {cat:<12}  {cnt} 筆")

    # 更新資料庫
    print("\n⏳  批次更新科目...")
    ok, fail = bulk_update(results)
    print(f"\n✅  完成：更新 {ok} 筆，失敗 {fail} 筆")


if __name__ == "__main__":
    main()

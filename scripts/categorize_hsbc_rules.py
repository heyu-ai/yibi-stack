"""
規則型分類：匯豐信用卡 2025-07~12 的 241 筆「其他支出」交易
"""

from __future__ import annotations

import re
import sys
from collections import Counter

from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://ledgerone:ledgerone@localhost:5435/ledgerone"
LEDGER_2025 = "0831287f-ab9b-408e-917a-2d2295cf0c18"

# ── 科目 name → uuid ────────────────────────────────────────────────────────
ACC = {
    "里程數成本": "e327afb8-3305-43ce-9025-e6d30fa1467c",
    "國外旅遊": "32cf5523-823e-4652-8602-a620705c9441",
    "旅費": "2cdfc1c9-5c03-4bcd-9a46-ab76e20eb9a8",
    "手續費": "2f640d74-e9f1-4b58-ba3a-a44bbd414673",
    "信用卡": "74991a46-96b1-4f85-93e6-ae0bb4b7c7a6",  # 年費/帳單費
    "醫療": "f35f771f-499e-4762-9adb-a2510e78a89e",
    "保健": "e75156a6-086b-4318-8322-b074d728aaec",
    "生產力工具": "af78c62e-8d88-41f8-9be1-8c2e1aa2cc0a",
    "系統維運": "356800e8-c368-4551-9972-7bacba7d2a00",
    "訂閱學習": "988c6df7-a7a6-4bce-8b6f-56ea6d2b2b21",
    "線上視頻": "c9a291b3-8199-48a0-b1db-38f57cb60dd6",
    "看漫畫": "bda930cb-f72b-4690-989c-ab7ef462f083",
    "線上遊戲": "e8021205-cac4-46da-9af6-e41d62a60e78",
    "國內旅遊": "ee781d46-a894-4ecf-b6e3-23f027c8a281",
    "書籍": "5ac1fcb0-4801-4cc4-b82f-839563f31a82",
    "汽車": "0c33eed3-c7d3-485c-aa89-4d40119a2334",
    "家電家具": "95acdcd8-4ad1-46c6-9bbc-25b9e1e8a409",
    "家庭三餐": "0fe73378-f77a-4b54-92be-3983353c8a3b",
    "家庭食材": "a9d24a5c-3d72-40d2-924b-e912831ae719",
    "公司款項": "51e65832-1981-4973-89e5-fc6a777324a5",
    "一般代刷": "da57d6a2-abe4-4350-942e-d4700ef473f4",
    "家庭生活用品": "565cb49e-b6de-49ba-9851-38e7aec73f67",
    "其他支出": "fff145dc-fa92-4e4f-b902-479e60a1199c",
}

# ── 分類規則（按優先順序） ───────────────────────────────────────────────────
# (正則或子字串, 科目名稱)
RULES: list[tuple[str, str]] = [
    # 手續費（最高優先）
    (r"手續費", "手續費"),
    # 里程換購（買點數/里程；現金換購機票稅費歸國外旅遊）
    (
        r"PRIVILEGECLUB|BYPOINTS|HAWATIANMILES|ALASKAMILES|ALLPLUSALL|ALLPLUS|MILESBY|HIPMUNK|POINTSBYPTS|THG.*BYPOINTS|IHG.*POINTS",
        "里程數成本",
    ),
    # 卡達/國泰機票（現金購票或稅費 → 國外旅遊）
    (r"QATARATR|CATHAYPAC", "國外旅遊"),
    # 年費
    (r"年費", "信用卡"),
    (r"^HSBC交易", "信用卡"),
    # 郵輪
    (r"MSCCRUISES|MSCCRUIS", "國外旅遊"),
    # 國外旅遊（餐廳、景點、住宿、交通 — 含外幣標記）
    (r"EXPO[Z0-9]|EXPO2025|EXPOZ025|EXPOZ0250", "國外旅遊"),
    (r"COCA-COLA.*JPN|BANPAKU|WEIXIN\*.*MA|WEIXIN\*.*HOTEL", "國外旅遊"),
    (r"tripla.*Tokyo|GRANDLISBOA|ACCOR(?!.*ALLPLUS)", "國外旅遊"),
    (
        r"\(JPN |JPN JPY|\(USA USD|\(THA THB|\(CHN CNY|\(MAC MOP|\(FRA EUR|\(AUS AUD|\(GBP|\(EUR ",
        "國外旅遊",
    ),
    # 醫療
    (r"榮民總醫院|醫院|診所|藥局", "醫療"),
    # 保健
    (r"IHERB|iHerb|VITACOST|SUPPLEMENT", "保健"),
    # 汽車交通
    (r"格上租車|HERTZ|AVIS|BUDGET|呼叫黃背心", "汽車"),
    # 家電家具
    (r"宜得利|NITORI|家樂福|IKEA", "家電家具"),
    # 家庭食材
    (r"COSTCO|好市多", "家庭食材"),
    # 餐廳
    (r"青花驕馬|鼎泰豐|欣葉|饗食天堂|牛角|王品|瓦城", "家庭三餐"),
    (r"RESTAURANT|DINING", "家庭三餐"),
    # 訂閱學習
    (r"READWISE|DUOLINGO|UDEMY|COURSERA|LINKEDIN.*LEARNING", "訂閱學習"),
    # 生產力工具
    (r"HEPTABASE|NOTION|1PASSWORD|OBSIDIAN|FIGMA|GRAMMARLY", "生產力工具"),
    # 系統維運（雲端）
    (r"GOOGLECLOUD|GOOGLE.*CLOUD|AWS|CLOUDFLARE|DIGITALOCEAN|HEROKU|VERCEL", "系統維運"),
    # 公司款項
    (r"ntlCoachFed|COACHFEDERATION|ICF|協會|公司|COMPANY", "公司款項"),
    # 網購（momo 等）
    (r"MOMO-EC|momo購物|SHOPEE|蝦皮", "家庭生活用品"),
    # 外送/餐廳
    (
        r"優食|UBEREATS|FOODPANDA|DELIVEROO|美食街|餐廳|涮涮鍋|火鍋|燒肉|牛肉麵|麥當勞|肯德基|摩斯|必勝客|MCDONALD|KFC|PIZZA|拉麵|壽司|居酒屋|茶飲|珍珠|STARBUCKS|CAFEAMAZON|AMAZON.*CAFE",
        "家庭三餐",
    ),
    (r"魚場|炸雞|製麵|德州美墨|百八", "家庭三餐"),
    # Uber（台灣計程車）
    (r"優步|UBER(?!EATS)", "汽車"),
    # 電子書
    (r"KOBO|KINDLE|BOOKWALKER|BOOK.*WALKER", "書籍"),
    # 影音串流
    (r"HAMIVIDEO|HAMI.*VIDEO|friDay影音|FRIDAY.*VIDEO|LINE.*TV|CATCHPLAY", "線上視頻"),
    (r"GOOGLE.*VIDEO|YOUTUBE.*PREMIUM", "線上視頻"),
    # 保健用品
    (r"杏一|藥妝|屈臣氏|康是美|Watson|MEDILIFE", "保健"),
    # 裝潢維修
    (r"B&Q|特力屋|HOME.*DEPOT|DIY", "家電家具"),
    # Paypal 預設其他
    (r"PAYPAL\*GOOGLE", "生產力工具"),
    # Google Play 相關
    (r"GOOGLE\*PLAYPASS|GOOGLE\*PLAY(?!.*CLOUD)", "線上遊戲"),
    (r"GOOGLE\*WEBTOON|WEBTOON|MANGA|ZHUJIAWEIG|漫畫人", "看漫畫"),
    # 咖啡廳
    (r"LOUISA|路易莎|STARBUCKS|星巴克|CAMA|COFFEE", "家庭三餐"),
    # 餐廳補充
    (
        r"SUKIYA|SUKITYA|すき家|六扇門|湯鍋|草山行館|微風南京|美食廣場|Q MAO|貢茶|GONGTEA",
        "家庭三餐",
    ),
    # 加油
    (r"中油|台塑石化|Shell|SHELL|加油|GAS STATION|PETRO", "汽車"),
    # 國內旅遊景點
    (r"陽明山|遊樂區|遊樂園|景區|風景區", "國內旅遊"),
    # 保健補充
    (r"Gandicrder|GARNIER|LOREAL|COSME", "保健"),
    # 家庭生活用品補充
    (r"安妮子|微風|百貨|購物中心|MALL", "家庭生活用品"),
    # 書店
    (r"墊腳石|誠品|金石堂|三民|博客來|BOOKSTORE|BOOKS", "書籍"),
    # 影音
    (r"DisneyPLUS|Disney\+|DISNEY.*PLUS", "線上視頻"),
    # 軟體訂閱（Cleverbridge 是軟體代售平台）
    (r"CLEVERBRIDG|CLEVERBRIDGE|LTPASSWORD|1PASSWORD|PADDLE\*", "生產力工具"),
    # 更多餐廳
    (r"餃子|喬園|烏菲茲|豆花|THE春|TAMEDFOX|神農市場|夜市", "家庭三餐"),
    # 卡達旅遊（HAYYA = Qatar fan ID）
    (r"HAYYA|DohaQAT|QAT QAR", "國外旅遊"),
]


def classify(desc: str) -> str:
    d = str(desc).upper().strip()
    for pattern, cat in RULES:
        if re.search(pattern.upper(), d):
            return cat
    return "其他支出"


# ── 讀取 + 分類 + 更新 ───────────────────────────────────────────────────────


def main() -> None:
    engine = create_engine(DB_URL)

    print("⏳  讀取待分類交易...")
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
            SELECT t.id, t.date, t.description, t.amount
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
    print(f"   → {len(rows)} 筆")

    # 分類
    classified: list[tuple] = []  # (id, cat)
    cat_counter: Counter = Counter()
    unknowns: list[tuple] = []

    for row in rows:
        tid, date, desc, amount = str(row[0]), str(row[1]), row[2], float(row[3])
        cat = classify(desc)
        classified.append((tid, cat))
        cat_counter[cat] += 1
        if cat == "其他支出":
            unknowns.append((date, desc, amount))

    # 預覽結果
    print("\n分類結果：")
    for cat, cnt in cat_counter.most_common():
        acc_id = ACC.get(cat, "❌ 找不到")
        print(f"  {cat:<12}  {cnt:>3} 筆   {acc_id[:8]}...")

    if unknowns:
        print(f"\n⚠️  仍為「其他支出」的 {len(unknowns)} 筆（供人工確認）：")
        for date, desc, amt in unknowns[:20]:
            print(f"  {date}  ${amt:>8,.0f}  {desc[:60]}")
        if len(unknowns) > 20:
            print(f"  ...（共 {len(unknowns)} 筆）")

    # 確認後更新
    confirm = input(f"\n確認要更新 {len(classified)} 筆科目嗎？[y/N] ").strip().lower()
    if confirm != "y":
        print("取消。")
        return

    print("\n⏳  更新中...")
    ok = fail = 0
    with engine.begin() as conn:
        for tid, cat in classified:
            acc_id = ACC.get(cat, ACC["其他支出"])
            try:
                conn.execute(
                    text(
                        "UPDATE transactions SET to_account_id = :aid ::uuid WHERE id = :tid ::uuid"
                    ),
                    {"aid": acc_id, "tid": tid},
                )
                ok += 1
            except Exception as e:
                print(f"  ❌ {tid}: {e}", file=sys.stderr)
                fail += 1

    print(f"✅  完成：更新 {ok} 筆，失敗 {fail} 筆")


if __name__ == "__main__":
    main()

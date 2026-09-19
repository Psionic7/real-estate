import random
from datetime import date, datetime, timedelta, timezone

from estate.db import connect, initialize, now_iso, raw_json, replace_trade_partition
from estate.listings import import_rows

# Every apartment and price below is synthetic; coordinates are illustrative anchors.
SITES = [
    ("11680", "서울특별시 강남구", "역삼동", "가상 역삼그린", "100-1", 37.5008, 127.0365, 180000),
    ("11680", "서울특별시 강남구", "대치동", "가상 대치파크", "100-2", 37.4960, 127.0610, 210000),
    ("11680", "서울특별시 강남구", "개포동", "가상 개포숲", "100-3", 37.4830, 127.0570, 195000),
    ("11710", "서울특별시 송파구", "잠실동", "가상 잠실리버", "100-4", 37.5115, 127.0830, 200000),
    ("11710", "서울특별시 송파구", "송파동", "가상 송파레이크", "100-5", 37.5020, 127.1090, 155000),
    ("11440", "서울특별시 마포구", "아현동", "가상 아현힐", "100-6", 37.5515, 126.9510, 135000),
    ("11440", "서울특별시 마포구", "상암동", "가상 상암가든", "100-7", 37.5780, 126.8890, 110000),
    ("41135", "경기도 성남시 분당구", "정자동", "가상 정자센트럴", "100-8", 37.3660, 127.1080, 130000),
    ("41135", "경기도 성남시 분당구", "백현동", "가상 백현포레", "100-9", 37.3910, 127.1110, 155000),
    ("26350", "부산광역시 해운대구", "우동", "가상 해운대오션", "100-10", 35.1630, 129.1510, 95000),
]


def seed(path, today=None):
    initialize(path)
    with connect(path) as conn:
        if conn.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone():
            return
    today = today or date.today()
    rng, partitions, listings = random.Random(20260919), {}, []
    for site_index, (region, name, dong, apt, lot, lat, lon, base) in enumerate(SITES):
        address = f"{name} {dong} {lot}"
        for index in range(72):
            day = today - timedelta(days=rng.randint(0, 365))
            area = rng.choice([59.9, 84.9, 84.9, 114.5])
            price = round(base * area / 84.9 * rng.uniform(.88, 1.1) / 100) * 100
            row = dict(region_code=region, deal_month=day.strftime("%Y%m"), apartment=apt,
                       address=address, dong=dong, deal_date=day.isoformat(), area_m2=area,
                       price_man=price, floor=rng.randint(1, 30), build_year=2015,
                       cancelled=int(index % 23 == 0), latitude=lat, longitude=lon,
                       source="demo", raw_json=raw_json({"synthetic": True}), collected_at=now_iso())
            if index == 71:
                row["latitude"], row["longitude"] = None, None
                row["address"] = ""
            partitions.setdefault((region, row["deal_month"]), []).append(row)
        for index in range(10):
            age = 20 if index == 9 else rng.randint(0, 6)
            stamp = datetime.combine(today - timedelta(days=age), datetime.min.time(),
                                     tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc)
            area = rng.choice([59.9, 84.9, 114.5])
            row = dict(source="demo", listing_id=f"D{site_index:02d}-{index:02d}", observed_at=stamp.isoformat(),
                       region_code=region, apartment=apt, address=address, dong=dong, area_m2=area,
                       price_man=round(base * area / 84.9 * rng.uniform(1.01, 1.18) / 100) * 100,
                       floor=rng.randint(1, 30), status="withdrawn" if index == 8 else "active",
                       latitude=lat, longitude=lon, source_url="")
            listings.append(row)
            older = dict(row, observed_at=(stamp - timedelta(days=15)).isoformat(), price_man=row["price_man"] + 3000,
                         status="active")
            listings.append(older)
    for (region, month), rows in partitions.items():
        replace_trade_partition(path, region, month, rows, "demo")
    import_rows(path, listings)
    with connect(path) as conn:
        conn.execute("INSERT OR REPLACE INTO metadata VALUES('demo_seeded',?)", (today.isoformat(),))

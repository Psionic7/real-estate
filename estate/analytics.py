from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from estate.db import connect


def load_data(path, region=None, start=None, end=None):
    trade_where, trade_params = ["1=1"], []
    listing_where, listing_params = ["1=1"], []
    if region and region != "전체":
        trade_where.append("t.region_code=?")
        listing_where.append("r.region_code=?")
        trade_params.append(region)
        listing_params.append(region)
    if start:
        trade_where.append("t.deal_date>=?")
        trade_params.append(start)
    if end:
        trade_where.append("t.deal_date<=?")
        trade_params.append(end)
    with connect(path) as conn:
        trades = pd.read_sql_query(f"""SELECT t.*,
            COALESCE(t.latitude,g.latitude) AS lat, COALESCE(t.longitude,g.longitude) AS lon
            FROM trades t LEFT JOIN geocodes g ON t.address=g.address
            WHERE {' AND '.join(trade_where)}""", conn, params=trade_params)
        listings = pd.read_sql_query(f"""WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY source,listing_id ORDER BY observed_at DESC,id DESC) AS rn
            FROM listing_snapshots)
            SELECT r.*, COALESCE(r.latitude,g.latitude) AS lat, COALESCE(r.longitude,g.longitude) AS lon
            FROM ranked r LEFT JOIN geocodes g ON r.address=g.address
            WHERE r.rn=1 AND {' AND '.join(listing_where)}""", conn, params=listing_params)
    for df in (trades, listings):
        df["price_eok"] = df["price_man"] / 10000
        df["price_per_m2"] = df["price_man"] / df["area_m2"]
        df["price_per_pyeong"] = df["price_per_m2"] * 3.305785
    return trades, listings


def latest_deal_date(path, region=None):
    where, params = "", []
    if region and region != "전체":
        where, params = "WHERE region_code=?", [region]
    with connect(path) as conn:
        row = conn.execute(f"SELECT MAX(deal_date) FROM trades {where}", params).fetchone()
    return row[0] if row and row[0] else None


def load_map_trades(path, region=None):
    """Load three latest calendar months plus each inactive apartment's latest month."""
    region_sql, params = "", []
    if region and region != "전체":
        region_sql, params = "AND t.region_code=?", [region]
    query = f"""
        WITH selected AS (
            SELECT t.*, COALESCE(t.latitude,g.latitude) lat, COALESCE(t.longitude,g.longitude) lon
            FROM trades t LEFT JOIN geocodes g ON t.address=g.address
            WHERE t.cancelled=0 {region_sql}
        ), anchors AS (
            SELECT region_code, MAX(deal_date) anchor_date FROM selected GROUP BY region_code
        ), recent AS (
            SELECT s.*, '최근 3개월' period_kind,
                   strftime('%Y-%m', date(a.anchor_date,'start of month','-2 months')) period_start,
                   strftime('%Y-%m', a.anchor_date) period_end
            FROM selected s JOIN anchors a USING(region_code)
            WHERE s.deal_date>=date(a.anchor_date,'start of month','-2 months')
              AND s.deal_date<=a.anchor_date
        ), active_apartments AS (
            SELECT DISTINCT region_code,dong,address,apartment FROM recent
        ), fallback_months AS (
            SELECT s.region_code,s.dong,s.address,s.apartment,MAX(s.deal_month) deal_month
            FROM selected s LEFT JOIN active_apartments a
              ON a.region_code=s.region_code AND a.dong=s.dong AND a.address=s.address AND a.apartment=s.apartment
            WHERE a.apartment IS NULL
            GROUP BY s.region_code,s.dong,s.address,s.apartment
        ), fallback AS (
            SELECT s.*, '최근 거래월' period_kind,
                   substr(s.deal_month,1,4)||'-'||substr(s.deal_month,5,2) period_start,
                   substr(s.deal_month,1,4)||'-'||substr(s.deal_month,5,2) period_end
            FROM selected s JOIN fallback_months f
              ON f.region_code=s.region_code AND f.dong=s.dong AND f.address=s.address
             AND f.apartment=s.apartment AND f.deal_month=s.deal_month
        )
        SELECT * FROM recent UNION ALL SELECT * FROM fallback
    """
    with connect(path) as conn:
        trades = pd.read_sql_query(query, conn, params=params)
    trades["price_eok"] = trades["price_man"] / 10000
    trades["price_per_pyeong"] = trades["price_man"] / trades["area_m2"] * 3.305785
    return trades


def active_listings(listings, freshness_days=7, now=None):
    now = now or datetime.now(timezone.utc)
    stamps = pd.to_datetime(listings["observed_at"], utc=True)
    return listings[(listings["status"] == "active") & (stamps >= now - timedelta(days=freshness_days))
                    & (stamps <= now)].copy()


def filter_common(df, region="전체", area=(0, 10000), price=(0, 1000), query=""):
    mask = df["area_m2"].between(*area) & df["price_eok"].between(*price)
    if region != "전체":
        mask &= df["region_code"] == region
    if query:
        mask &= (df["apartment"].str.contains(query, regex=False, na=False)
                 | df["address"].str.contains(query, regex=False, na=False))
    return df[mask].copy()


def within_radius(df, latitude, longitude, radius_km):
    lat = np.radians(pd.to_numeric(df["lat"], errors="coerce"))
    lon = np.radians(pd.to_numeric(df["lon"], errors="coerce"))
    lat0, lon0 = np.radians([latitude, longitude])
    a = np.sin((lat-lat0)/2)**2 + np.cos(lat0)*np.cos(lat)*np.sin((lon-lon0)/2)**2
    distance = 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return df[distance <= radius_km].copy()


def monthly_stats(trades):
    if trades.empty:
        return pd.DataFrame(columns=["계약월", "거래량", "중위가격(억원)", "평당중위가격(만원)"])
    df = trades.assign(계약월=trades["deal_date"].str[:7])
    return df.groupby("계약월").agg(**{"거래량": ("id", "size"), "중위가격(억원)": ("price_eok", "median"),
                                       "평당중위가격(만원)": ("price_per_pyeong", "median")}).reset_index()


APARTMENT_KEYS = ["region_code", "dong", "address", "apartment"]
APARTMENT_METRICS = ["count", "median_price", "min_price", "max_price", "total_price",
                     "median_per_pyeong", "min_area", "max_area", "latest_date",
                     "latest_price", "latest_count", "lat", "lon"]


def apartment_stats(trades):
    """Summarize the filtered sample; equal names at different addresses stay separate.

    Latest price is the median on the most recent contract day, not an arbitrary
    row when multiple transactions have the same date. Coordinates never affect
    the price/volume sample.
    """
    rows = []
    for keys, group in trades[trades["cancelled"] == 0].groupby(APARTMENT_KEYS, dropna=False):
        latest_date = group["deal_date"].max()
        latest = group[group["deal_date"] == latest_date]
        located = group.dropna(subset=["lat", "lon"])
        rows.append(dict(zip(APARTMENT_KEYS, keys), count=len(group),
            median_price=group["price_eok"].median(), min_price=group["price_eok"].min(),
            max_price=group["price_eok"].max(), total_price=group["price_eok"].sum(),
            median_per_pyeong=group["price_per_pyeong"].median(),
            min_area=group["area_m2"].min(), max_area=group["area_m2"].max(),
            latest_date=latest_date, latest_price=latest["price_eok"].median(), latest_count=len(latest),
            lat=located["lat"].median() if not located.empty else None,
            lon=located["lon"].median() if not located.empty else None))
    return pd.DataFrame(rows, columns=APARTMENT_KEYS + APARTMENT_METRICS).sort_values(
        ["count", "latest_date", "apartment", "address"], ascending=[False, False, True, True]).reset_index(drop=True)


def apartment_sample(trades, apartment):
    mask = pd.Series(True, index=trades.index)
    for key in APARTMENT_KEYS:
        mask &= trades[key] == apartment[key]
    return trades[mask].copy()


def map_price_points(trades, region_views):
    """Map overlays with apartment coordinates and a guaranteed regional summary."""
    points = []
    trades = trades[trades["cancelled"] == 0]
    if trades.empty:
        return points
    for keys, group in trades.groupby(APARTMENT_KEYS, dropna=False):
        located = group.dropna(subset=["lat", "lon"])
        if located.empty:
            continue
        region, dong, address, apartment = keys
        average, count = group["price_eok"].mean(), len(group)
        start, end, kind = group.iloc[0][["period_start", "period_end", "period_kind"]]
        period = start if start == end else f"{start}~{end}"
        points.append(dict(region_code=region, dong=dong, address=address, apartment=apartment,
            kind="아파트", lat=float(located["lat"].median()), lon=float(located["lon"].median()),
            count=count, average_price=average, period=period, period_kind=kind,
            color=[8, 127, 140, 225], radius=85 + min(count, 30) * 7,
            label=f"{average:.2f}",
            summary=f"{kind} 평균 {average:.2f}억원 · {count}건\n계산 기간 {period}"))
    regions_with_apartments = {p["region_code"] for p in points}
    for region_code, group in trades.groupby("region_code"):
        if region_code in regions_with_apartments or region_code not in region_views:
            continue
        recent = group[group["period_kind"] == "최근 3개월"]
        sample = recent if not recent.empty else group[group["deal_month"] == group["deal_month"].max()]
        if sample.empty:
            continue
        average, count = sample["price_eok"].mean(), len(sample)
        start, end, kind = sample.iloc[0][["period_start", "period_end", "period_kind"]]
        period = start if start == end else f"{start}~{end}"
        lat, lon, _ = region_views[region_code]
        points.append(dict(region_code=region_code, dong="", address="", apartment="지역 전체 요약",
            kind="지역 요약", lat=lat, lon=lon, count=count, average_price=average,
            period=period, period_kind=kind, color=[38, 72, 120, 235], radius=650,
            label=f"{average:.2f}",
            summary=f"{kind} 평균 {average:.2f}억원 · {count:,}건\n계산 기간 {period}"))
    return points


def map_points(trades, listings):
    """Backward-compatible point builder for listing comparisons."""
    points = []
    for frame, kind, color in [(listings, "매물 호가", [241, 153, 62, 210])]:
        located = frame.dropna(subset=["lat", "lon"])
        for (region, dong, address, apt), group in located.groupby(APARTMENT_KEYS):
            median = f"{group['price_eok'].median():.2f}"
            points.append(dict(region_code=region, dong=dong, address=address, apartment=apt, kind=kind,
                               lat=float(group["lat"].median()), lon=float(group["lon"].median()),
                               count=len(group), median_price=median, color=color,
                               summary=f"매물 호가 {len(group)}건 · 중위 {median}억원",
                               radius=65 + min(len(group), 40) * 5))
    return points


def comparable_gap(trades, listings):
    """Match exact address/apartment, then +/-5% area per listing; require 3 sales."""
    output = []
    for _, listing in listings.iterrows():
        if not listing["address"]:
            continue
        sample = trades[(trades["address"] == listing["address"]) &
                        (trades["apartment"] == listing["apartment"]) &
                        trades["area_m2"].between(listing["area_m2"] * .95, listing["area_m2"] * 1.05)]
        if len(sample) < 3:
            continue
        median = sample["price_eok"].median()
        output.append({"단지": listing["apartment"], "주소": listing["address"], "전용면적(㎡)": listing["area_m2"],
                       "호가(억원)": listing["price_eok"], "비교거래수": len(sample),
                       "실거래중위값(억원)": median, "호가차이(%)": (listing["price_eok"] / median - 1) * 100})
    return pd.DataFrame(output)


def export_csv(frame):
    safe = frame.copy()
    for col in safe.select_dtypes(include=["object", "string"]).columns:
        safe[col] = safe[col].map(lambda v: "'" + v if isinstance(v, str) and
                                 v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else v)
    return safe.to_csv(index=False).encode("utf-8-sig")

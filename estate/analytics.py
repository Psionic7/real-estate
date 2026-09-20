from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from estate.db import connect


def load_data(path):
    with connect(path) as conn:
        trades = pd.read_sql_query("""SELECT t.*,
            COALESCE(t.latitude,g.latitude) AS lat, COALESCE(t.longitude,g.longitude) AS lon
            FROM trades t LEFT JOIN geocodes g ON t.address=g.address""", conn)
        listings = pd.read_sql_query("""WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY source,listing_id ORDER BY observed_at DESC,id DESC) AS rn
            FROM listing_snapshots)
            SELECT r.*, COALESCE(r.latitude,g.latitude) AS lat, COALESCE(r.longitude,g.longitude) AS lon
            FROM ranked r LEFT JOIN geocodes g ON r.address=g.address WHERE r.rn=1""", conn)
    for df in (trades, listings):
        df["price_eok"] = df["price_man"] / 10000
        df["price_per_m2"] = df["price_man"] / df["area_m2"]
        df["price_per_pyeong"] = df["price_per_m2"] * 3.305785
    return trades, listings


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


def map_points(trades, listings):
    points = []
    for row in apartment_stats(trades).dropna(subset=["lat", "lon"]).to_dict("records"):
        median = f"{row['median_price']:.2f}"
        points.append(dict(row, kind="실거래", color=[8, 127, 140, 200],
            median_price=median, radius=65 + min(row["count"], 40) * 5,
            label=f"{row['apartment']}\n{median}억 · {row['count']}건",
            summary=(f"실거래 {row['count']}건 · 중위 {median}억원\n"
                     f"최저 {row['min_price']:.2f} / 최고 {row['max_price']:.2f}억원\n"
                     f"최근 계약일 {row['latest_date']} · {row['latest_count']}건\n"
                     f"최근일 중위 {row['latest_price']:.2f}억원")))
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

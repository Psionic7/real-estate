"""Persist an apartment catalogue derived from collected, auditable transactions."""
from __future__ import annotations

import pandas as pd

from estate.analytics import canonicalize_apartment_names
from estate.db import connect, now_iso


def sync_apartment_complexes(path, region=None):
    """Rebuild apartment metadata for one region or the complete local dataset."""
    where = "t.cancelled=0"
    params = []
    if region and region != "전체":
        where += " AND t.region_code=?"
        params.append(region)
    stamp = now_iso()
    with connect(path) as conn:
        if region and region != "전체":
            conn.execute("DELETE FROM apartment_complexes WHERE region_code=?", (region,))
        else:
            conn.execute("DELETE FROM apartment_complexes")
        conn.execute(f"""
            INSERT INTO apartment_complexes(
                region_code,dong,apartment,address,latitude,longitude,build_year,
                min_area_m2,max_area_m2,first_deal_date,last_deal_date,trade_count,source,updated_at)
            SELECT t.region_code,t.dong,t.apartment,t.address,
                CASE WHEN COUNT(t.latitude)>0 THEN AVG(t.latitude) ELSE MAX(g.latitude) END,
                CASE WHEN COUNT(t.longitude)>0 THEN AVG(t.longitude) ELSE MAX(g.longitude) END,
                MAX(t.build_year),MIN(t.area_m2),MAX(t.area_m2),MIN(t.deal_date),MAX(t.deal_date),
                COUNT(*),'molit-trades',?
            FROM trades t LEFT JOIN geocodes g ON t.address=g.address
            WHERE {where}
            GROUP BY t.region_code,t.dong,t.apartment,t.address
        """, [stamp, *params])
        regions = ([region] if region and region != "전체" else
                   [row[0] for row in conn.execute("SELECT DISTINCT region_code FROM trades")])
        if not region or region == "전체":
            regions.append("all")
        conn.executemany(
            "INSERT INTO metadata(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [(f"apartment_complexes_sync:{code}", stamp) for code in regions],
        )
        return conn.execute(
            "SELECT COUNT(*) FROM apartment_complexes" +
            (" WHERE region_code=?" if region and region != "전체" else ""),
            ([region] if region and region != "전체" else []),
        ).fetchone()[0]


def ensure_apartment_complexes(path, region=None):
    """Backfill legacy public snapshots once; collectors keep later data current."""
    if region and region != "전체":
        key = f"apartment_complexes_sync:{region}"
        params = (key,)
        query = "SELECT 1 FROM metadata WHERE key=?"
    else:
        params = ("apartment_complexes_sync:all",)
        query = "SELECT 1 FROM metadata WHERE key=?"
    with connect(path) as conn:
        ready = conn.execute(query, params).fetchone()
    if not ready:
        sync_apartment_complexes(path, region)


def load_apartment_complexes(path, region=None):
    where, params = "latitude IS NOT NULL AND longitude IS NOT NULL", []
    if region and region != "전체":
        where += " AND region_code=?"
        params.append(region)
    with connect(path) as conn:
        frame = pd.read_sql_query(
            f"""SELECT id,region_code,dong,apartment,address,
                latitude AS lat,longitude AS lon,build_year,min_area_m2 AS min_area,
                max_area_m2 AS max_area,first_deal_date,last_deal_date,trade_count,source
                FROM apartment_complexes WHERE {where}
                ORDER BY trade_count DESC,apartment,address""",
            conn, params=params,
        )
    return canonicalize_apartment_names(frame)

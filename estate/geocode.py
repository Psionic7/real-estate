import csv
from pathlib import Path

from estate.db import connect, now_iso
from estate.http import DataSourceError, get, session


DEFAULT_SEED = Path(__file__).resolve().parents[1] / "data" / "geocodes.csv"


def load_seed_geocodes(path, seed_path=DEFAULT_SEED):
    """Merge packaged apartment coordinates into an existing runtime database."""
    seed_path = Path(seed_path)
    if not seed_path.exists():
        return 0
    rows = []
    with seed_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if row.get("address") and 32 <= lat <= 39.5 and 124 <= lon <= 132:
                rows.append((row["address"], lat, lon, row.get("provider") or "seed",
                             row.get("updated_at") or now_iso()))
    with connect(path) as conn:
        before = conn.total_changes
        conn.executemany("""
            INSERT INTO geocodes(address,latitude,longitude,provider,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(address) DO NOTHING
        """, rows)
        return conn.total_changes - before


def geocode_pending(path, key, limit=100, region=None):
    if not key.strip():
        raise ValueError("KAKAO_REST_API_KEY를 설정하세요.")
    with connect(path) as conn:
        addresses = conn.execute("""
            SELECT DISTINCT a.address FROM (
                SELECT address,region_code FROM trades WHERE latitude IS NULL OR longitude IS NULL
                UNION SELECT address,region_code FROM listing_snapshots WHERE latitude IS NULL OR longitude IS NULL
            ) a LEFT JOIN geocodes g ON a.address=g.address
            WHERE g.address IS NULL AND a.address != '' AND (? IS NULL OR a.region_code=?)
            ORDER BY a.address LIMIT ?
        """, (region, region, limit)).fetchall()
    matched, unresolved = 0, 0
    with session() as client:
        for row in addresses:
            response = get(client, "https://dapi.kakao.com/v2/local/search/address.json",
                           headers={"Authorization": f"KakaoAK {key}"},
                           params={"query": row["address"], "analyze_type": "exact", "size": 2})
            try:
                documents = response.json()["documents"]
                # Ambiguous or missing matches remain absent, never fall back to a district centroid.
                if len(documents) != 1:
                    unresolved += 1
                    continue
                doc = documents[0]
                # A district/dong-only result cannot identify an apartment parcel.
                if not (doc.get("address") or {}).get("main_address_no"):
                    unresolved += 1
                    continue
                lat, lon = float(doc["y"]), float(doc["x"])
                if not (32 <= lat <= 39.5 and 124 <= lon <= 132):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise DataSourceError("주소 좌표 응답 검증에 실패했습니다.") from None
            with connect(path) as conn:
                conn.execute("INSERT INTO geocodes VALUES(?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET "
                             "latitude=excluded.latitude,longitude=excluded.longitude,updated_at=excluded.updated_at",
                             (row["address"], lat, lon, "kakao", now_iso()))
            matched += 1
    return matched, unresolved

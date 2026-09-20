import csv
import math
from pathlib import Path
from statistics import median

from estate.db import connect, now_iso
from estate.http import DataSourceError, get, session


DEFAULT_SEED = Path(__file__).resolve().parents[1] / "data" / "geocodes.csv"
ARCGIS_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
REGION_CENTERS = {"41465": (37.322, 127.097), "41135": (37.382, 127.119),
                  "41117": (37.294, 127.047)}


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


def pending_addresses(path, limit=100, region=None):
    with connect(path) as conn:
        return conn.execute("""
            SELECT DISTINCT a.address FROM (
                SELECT address,region_code FROM trades WHERE latitude IS NULL OR longitude IS NULL
                UNION SELECT address,region_code FROM listing_snapshots WHERE latitude IS NULL OR longitude IS NULL
            ) a LEFT JOIN geocodes g ON a.address=g.address
            WHERE g.address IS NULL AND a.address != '' AND (? IS NULL OR a.region_code=?)
            ORDER BY a.address LIMIT ?
        """, (region, region, limit)).fetchall()


def store_coordinate(path, address, lat, lon, provider):
    with connect(path) as conn:
        conn.execute("INSERT INTO geocodes VALUES(?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET "
                     "latitude=excluded.latitude,longitude=excluded.longitude,provider=excluded.provider,"
                     "updated_at=excluded.updated_at", (address, lat, lon, provider, now_iso()))


def distance_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


def geocode_pending(path, key, limit=100, region=None):
    if not key.strip():
        raise ValueError("KAKAO_REST_API_KEY를 설정하세요.")
    addresses = pending_addresses(path, limit, region)
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
            store_coordinate(path, row["address"], lat, lon, "kakao")
            matched += 1
    return matched, unresolved


def geocode_pending_arcgis(path, limit=100, region=None):
    """Automatically fill exact parcel results without using an area centroid."""
    addresses = pending_addresses(path, limit, region)
    matched, unresolved = 0, 0
    with session() as client:
        for row in addresses:
            address = row["address"]
            response = get(client, ARCGIS_URL, headers={"User-Agent": "KoreaApartmentTransactionMap/1.0"},
                           params={"f": "json", "maxLocations": 5, "SingleLine": address})
            try:
                parcel, dong = address.split()[-1], address.split()[-2]
                points = []
                for candidate in response.json().get("candidates", []):
                    label, location = candidate.get("address", ""), candidate.get("location", {})
                    if (candidate.get("score", 0) >= 95 and dong in label and parcel in label
                            and location.get("x") is not None and location.get("y") is not None):
                        points.append((float(location["y"]), float(location["x"])))
                center = REGION_CENTERS.get(region) if region else None
                if not points or (center and any(distance_km(point, center) > 18 for point in points)):
                    raise ValueError
                if any(distance_km(points[0], point) > 0.8 for point in points[1:]):
                    raise ValueError
                lat, lon = median(point[0] for point in points), median(point[1] for point in points)
                if not (32 <= lat <= 39.5 and 124 <= lon <= 132):
                    raise ValueError
            except (IndexError, KeyError, TypeError, ValueError):
                unresolved += 1
                continue
            store_coordinate(path, address, lat, lon, "arcgis")
            matched += 1
    return matched, unresolved

"""Fill missing apartment coordinates from exact Korean parcel-address results.

The importer accepts a coordinate only when every returned candidate is inside
the requested district and the candidates form one compact site. It never
falls back to a dong or district centroid.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from estate.db import connect, now_iso  # noqa: E402


SEARCH_URL = "https://juso.app/search"
DETAIL_URL = "https://juso.app/b/{identifier}"
ARCGIS_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
USER_AGENT = "KoreaApartmentTransactionMap/1.0 coordinate-quality-audit"
DETAIL_LINK = re.compile(r'href="/b/([^"?]+)"')
COORDINATES = re.compile(r'"coordinates":\[\{"latitude":([0-9.]+),"longitude":([0-9.]+)\}\]')
CENTERS = {"41465": (37.322, 127.097), "41135": (37.382, 127.119), "41117": (37.294, 127.047)}
_local = threading.local()


def distance_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


def client():
    if not hasattr(_local, "client"):
        _local.client = requests.Session()
        _local.client.headers["User-Agent"] = USER_AGENT
    return _local.client


def fetch(url, **params):
    error = None
    for attempt in range(4):
        try:
            response = client().get(url, params=params, timeout=30)
            response.raise_for_status()
            return html.unescape(response.text)
        except requests.RequestException as exc:
            error = exc
            time.sleep(1.5 * (attempt + 1))
    raise error


def validated_center(points, region_code):
    points = list(dict.fromkeys(points))
    if not points:
        return None, "검색 결과에 필지 좌표 없음"
    center = CENTERS.get(region_code)
    if center is None or any(distance_km(point, center) > 18 for point in points):
        return None, "선택 지역 밖 좌표"
    if any(distance_km(points[0], point) > 0.8 for point in points[1:]):
        return None, "동일 지번 후보가 서로 멀리 떨어짐"
    return (median(point[0] for point in points), median(point[1] for point in points)), ""


def arcgis_site(address, region_code):
    response = client().get(ARCGIS_URL, params={"f": "json", "maxLocations": 5,
                            "SingleLine": address}, timeout=30)
    response.raise_for_status()
    parcel, dong = address.split()[-1], address.split()[-2]
    points = []
    for candidate in response.json().get("candidates", []):
        label = candidate.get("address", "")
        location = candidate.get("location", {})
        if (candidate.get("score", 0) >= 95 and dong in label and parcel in label
                and location.get("x") is not None and location.get("y") is not None):
            points.append((float(location["y"]), float(location["x"])))
    point, reason = validated_center(points, region_code)
    return point, "arcgis" if point else reason


def juso_site(address, region_code):
    search = fetch(SEARCH_URL, q=address)
    identifiers = list(dict.fromkeys(DETAIL_LINK.findall(search)))[:12]
    points = []
    for identifier in identifiers:
        detail = fetch(DETAIL_URL.format(identifier=identifier))
        points.extend((float(lat), float(lon)) for lat, lon in COORDINATES.findall(detail))
    point, reason = validated_center(points, region_code)
    return point, "juso.app" if point else reason


def exact_site(address, region_code):
    point, provider = arcgis_site(address, region_code)
    if point:
        return point, provider
    fallback, fallback_provider = juso_site(address, region_code)
    return (fallback, fallback_provider) if fallback else (None, f"{provider}; {fallback_provider}")


def missing_addresses(path, regions):
    placeholders = ",".join("?" for _ in regions)
    with connect(path) as conn:
        return [dict(row) for row in conn.execute(f"""
            WITH addresses AS (
              SELECT region_code,address,MAX(apartment) apartment FROM trades
              WHERE cancelled=0 AND address!='' AND region_code IN ({placeholders})
              GROUP BY region_code,address
              UNION
              SELECT region_code,address,MAX(apartment) apartment FROM listing_snapshots
              WHERE address!='' AND region_code IN ({placeholders}) GROUP BY region_code,address
            )
            SELECT a.* FROM addresses a LEFT JOIN geocodes g USING(address)
            WHERE g.address IS NULL ORDER BY a.region_code,a.address
        """, [*regions, *regions]).fetchall()]


def merge_seed(seed_path, additions):
    existing = {}
    if seed_path.exists():
        with seed_path.open(encoding="utf-8-sig", newline="") as stream:
            existing = {row["address"]: row for row in csv.DictReader(stream)}
    for address, lat, lon, provider, updated_at in additions:
        existing[address] = {"address": address, "latitude": lat, "longitude": lon,
                             "provider": provider, "updated_at": updated_at}
    with seed_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["address", "latitude", "longitude", "provider", "updated_at"])
        writer.writeheader()
        writer.writerows(existing[address] for address in sorted(existing))


def run(path, seed_path, regions, workers=3):
    pending = missing_addresses(path, regions)
    matched, failures = [], []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(exact_site, row["address"], row["region_code"]): row for row in pending}
        for index, future in enumerate(as_completed(futures), 1):
            row = futures[future]
            try:
                point, provider = future.result()
            except Exception as exc:  # Preserve the address for a later retry.
                point, provider = None, f"연결 실패: {type(exc).__name__}"
            if point:
                matched.append((row["address"], point[0], point[1], provider, now_iso()))
            else:
                failures.append({**row, "reason": provider})
            if index % 25 == 0 or index == len(pending):
                print(f"확인 {index}/{len(pending)} · 좌표 {len(matched)} · 미확정 {len(failures)}", flush=True)
    if matched:
        with connect(path) as conn:
            conn.executemany("""INSERT INTO geocodes(address,latitude,longitude,provider,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET latitude=excluded.latitude,
                longitude=excluded.longitude,provider=excluded.provider,updated_at=excluded.updated_at""", matched)
        merge_seed(seed_path, matched)
    return matched, failures


def main():
    parser = argparse.ArgumentParser(description="정확한 지번 결과로 누락 아파트 좌표를 보완합니다.")
    parser.add_argument("--database", type=Path, default=ROOT / "data/estate.sqlite3")
    parser.add_argument("--seed", type=Path, default=ROOT / "data/geocodes.csv")
    parser.add_argument("--regions", nargs="+", choices=sorted(CENTERS), default=sorted(CENTERS))
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--failures", type=Path, default=ROOT / "data/geocode_failures.json")
    args = parser.parse_args()
    matched, failures = run(args.database, args.seed, args.regions, args.workers)
    args.failures.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료: 좌표 {len(matched)} · 미확정 {len(failures)} · 보고서 {args.failures}")


if __name__ == "__main__":
    main()

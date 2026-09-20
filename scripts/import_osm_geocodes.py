"""Import conservative apartment coordinates from OpenStreetMap.

Only an exact normalized apartment-name match inside the selected district is
accepted. Reused apartment names, or OSM matches split across distant sites,
remain unresolved for the address geocoder to handle.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from estate.db import connect, now_iso  # noqa: E402


DISTRICTS = {
    "41465": "수지구",
    "41135": "분당구",
    "41117": "영통구",
}
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "KoreaApartmentTransactionMap/1.0"


def normalized_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣]", "", value or "").lower()
    return value.removesuffix("아파트")


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


def one_site(points: list[tuple[float, float]], radius_km: float = 0.35):
    """Return one site center, or None when a name refers to distant sites."""
    unique = []
    for point in points:
        if not any(distance_km(point, existing) < 0.01 for existing in unique):
            unique.append(point)
    if not unique:
        return None
    pending, clusters = set(range(len(unique))), []
    while pending:
        cluster, frontier = set(), {pending.pop()}
        while frontier:
            index = frontier.pop()
            cluster.add(index)
            neighbours = {other for other in pending
                          if distance_km(unique[index], unique[other]) <= radius_km}
            pending -= neighbours
            frontier |= neighbours
        clusters.append(cluster)
    if len(clusters) != 1:
        return None
    return median(point[0] for point in unique), median(point[1] for point in unique)


def osm_sites(district: str, endpoint: str = OVERPASS_URL):
    query = f'''[out:json][timeout:120];
area["name"="{district}"]["boundary"="administrative"]->.district;
(
  nwr["name"]["building"="apartments"](area.district);
  nwr["name"]["landuse"="residential"](area.district);
);
out center tags;'''
    response = requests.get(endpoint, params={"data": query},
                            headers={"User-Agent": USER_AGENT}, timeout=150)
    response.raise_for_status()
    candidates = defaultdict(dict)
    for element in response.json().get("elements", []):
        tags = element.get("tags", {})
        center = element.get("center", element)
        if center.get("lat") is None or center.get("lon") is None:
            continue
        for field in ("name", "name:ko", "official_name", "alt_name", "short_name"):
            name = normalized_name(tags.get(field, ""))
            if name:
                candidates[name][(element.get("type"), element.get("id"))] = (
                    float(center["lat"]), float(center["lon"]))
    return {name: one_site(list(elements.values())) for name, elements in candidates.items()}


def import_region(path: Path, region: str, endpoint: str = OVERPASS_URL, dry_run=False):
    district = DISTRICTS[region]
    sites = osm_sites(district, endpoint)
    with connect(path) as conn:
        rows = conn.execute("""
            SELECT apartment,address,COUNT(*) transactions
            FROM trades WHERE region_code=? AND address!=''
            GROUP BY apartment,address ORDER BY transactions DESC
        """, (region,)).fetchall()
    by_name = defaultdict(list)
    for row in rows:
        by_name[normalized_name(row["apartment"])].append(row)
    matched, unresolved = [], 0
    for name, apartments in by_name.items():
        site = sites.get(name)
        if site is None or len(apartments) != 1:
            unresolved += len(apartments)
            continue
        row = apartments[0]
        matched.append((row["address"], site[0], site[1], "openstreetmap", now_iso()))
    if matched and not dry_run:
        with connect(path) as conn:
            conn.executemany("""
                INSERT INTO geocodes(address,latitude,longitude,provider,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(address) DO NOTHING
            """, matched)
    return len(matched), unresolved


def main():
    parser = argparse.ArgumentParser(description="OpenStreetMap 아파트 좌표를 SQLite에 저장합니다.")
    parser.add_argument("--database", default="data/estate.sqlite3")
    parser.add_argument("--regions", nargs="+", choices=sorted(DISTRICTS),
                        default=list(DISTRICTS))
    parser.add_argument("--endpoint", default=OVERPASS_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    for region in args.regions:
        matched, unresolved = import_region(Path(args.database), region, args.endpoint, args.dry_run)
        print(f"{region} {DISTRICTS[region]}: 저장 {matched:,} / 미확정 {unresolved:,}")


if __name__ == "__main__":
    main()

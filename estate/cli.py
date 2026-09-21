import argparse
import os
from datetime import date
from pathlib import Path

from estate.config import db_path, juso_address_search_key, kakao_key, service_key
from estate.db import backup, connect, initialize
from estate.baseline import build_baseline, package_database
from estate.geocode import geocode_pending, geocode_pending_arcgis
from estate.juso import collect_address_lookups
from estate.listings import fetch_feed, import_rows, parse_payload
from estate.molit import collect, months_between


def main():
    parser = argparse.ArgumentParser(description="집의 흐름 데이터 관리 CLI")
    parser.add_argument("--db", type=Path, help="명시적 DB 경로 (기본: 실제 데이터 DB)")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("init")
    baseline = subs.add_parser("baseline", help="기본 3개 지역을 2000년 1월부터 수집")
    baseline.add_argument("--start", default="200001")
    baseline.add_argument("--end", default=date.today().strftime("%Y%m"))
    baseline.add_argument("--package", action="store_true", help="완료 후 배포용 .gz 생성")
    trade = subs.add_parser("collect")
    trade.add_argument("--region", required=True)
    trade.add_argument("--region-name", required=True)
    trade.add_argument("--start", required=True)
    trade.add_argument("--end", required=True)
    recent = subs.add_parser("refresh")
    recent.add_argument("--region", required=True)
    recent.add_argument("--region-name", required=True)
    recent.add_argument("--months", type=int, default=3)
    listing = subs.add_parser("import-listings")
    listing.add_argument("file", type=Path)
    subs.add_parser("fetch-listings")
    geo = subs.add_parser("geocode")
    geo.add_argument("--limit", type=int, default=100)
    addresses = subs.add_parser("search-addresses", help="공식 주소 검색 API 결과를 로컬 DB에 저장")
    addresses.add_argument("--limit", type=int, default=100)
    addresses.add_argument("--region")
    addresses.add_argument("--refresh", action="store_true", help="이미 조회한 주소도 다시 확인")
    save = subs.add_parser("backup")
    save.add_argument("destination", type=Path)
    subs.add_parser("status")
    args = parser.parse_args()
    path = args.db or db_path()
    initialize(path)
    with connect(path) as conn:
        is_demo = conn.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone() is not None
    if is_demo and args.command in {"collect", "refresh", "import-listings", "fetch-listings", "geocode", "search-addresses"}:
        parser.error("데모 DB에는 실제 데이터를 저장할 수 없습니다.")
    try:
        if args.command == "baseline":
            build_baseline(path, args.start, args.end)
            if args.package:
                packed = package_database(path)
                print(f"Packaged baseline: {packed}")
        elif args.command in {"collect", "refresh"}:
            if args.command == "refresh":
                if not 1 <= args.months <= 120:
                    raise ValueError("months 범위는 1~120입니다.")
                current = date.today()
                offset = current.year * 12 + current.month - args.months
                args.start = f"{offset // 12:04d}{offset % 12 + 1:02d}"
                args.end = current.strftime("%Y%m")
            for month in months_between(args.start, args.end):
                count = collect(path, service_key(), args.region, month, args.region_name)
                print(f"{args.region}/{month}: {count} rows")
        elif args.command == "import-listings":
            print(f"Inserted: {import_rows(path, parse_payload(args.file.read_bytes(), args.file.suffix))}")
        elif args.command == "fetch-listings":
            rows = fetch_feed(os.getenv("LISTINGS_FEED_URL", ""), os.getenv("LISTINGS_FEED_TOKEN", ""))
            print(f"Inserted: {import_rows(path, rows)}")
        elif args.command == "geocode":
            if not 1 <= args.limit <= 10000:
                raise ValueError("limit 범위는 1~10000입니다.")
            kakao_matched = 0
            if kakao_key():
                kakao_matched, _ = geocode_pending(path, kakao_key(), args.limit)
            arcgis_matched, unresolved = geocode_pending_arcgis(path, args.limit)
            print(f"Matched/unresolved: {kakao_matched + arcgis_matched}/{unresolved}")
        elif args.command == "search-addresses":
            if not 1 <= args.limit <= 10000:
                raise ValueError("limit 범위는 1~10000입니다.")
            exact, unresolved = collect_address_lookups(
                path, juso_address_search_key(), args.limit, args.region, args.refresh)
            print(f"Exact/unresolved: {exact}/{unresolved}")
        elif args.command == "backup":
            backup(path, args.destination)
            print(f"Backup: {args.destination}")
        elif args.command == "status":
            with connect(path) as conn:
                for table in ["trades", "listing_snapshots", "geocodes", "collection_runs"]:
                    print(f"{table}: {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
        else:
            print(f"DB ready: {path}")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()

import argparse
import os
from datetime import date
from pathlib import Path

from estate.config import db_path, service_key
from estate.db import backup, connect, initialize
from estate.geocode import geocode_pending
from estate.listings import fetch_feed, import_rows, parse_payload
from estate.molit import collect, months_between


def main():
    parser = argparse.ArgumentParser(description="집의 흐름 데이터 관리 CLI")
    parser.add_argument("--db", type=Path, help="명시적 DB 경로 (기본: 실제 데이터 DB)")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("init")
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
    save = subs.add_parser("backup")
    save.add_argument("destination", type=Path)
    subs.add_parser("status")
    args = parser.parse_args()
    path = args.db or db_path()
    initialize(path)
    with connect(path) as conn:
        is_demo = conn.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone() is not None
    if is_demo and args.command in {"collect", "refresh", "import-listings", "fetch-listings", "geocode"}:
        parser.error("데모 DB에는 실제 데이터를 저장할 수 없습니다.")
    try:
        if args.command in {"collect", "refresh"}:
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
            print(f"Matched/unresolved: {geocode_pending(path, os.getenv('KAKAO_REST_API_KEY', ''), args.limit)}")
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

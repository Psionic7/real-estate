import json
import sqlite3
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    region_code TEXT NOT NULL, deal_month TEXT NOT NULL,
    apartment TEXT NOT NULL, address TEXT NOT NULL, dong TEXT NOT NULL,
    deal_date TEXT NOT NULL, area_m2 REAL NOT NULL CHECK(area_m2 > 0),
    price_man INTEGER NOT NULL CHECK(price_man > 0), floor INTEGER,
    build_year INTEGER, cancelled INTEGER NOT NULL CHECK(cancelled IN (0,1)),
    latitude REAL, longitude REAL,
    source TEXT NOT NULL, raw_json TEXT NOT NULL, collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_region_date ON trades(region_code, deal_date);
CREATE INDEX IF NOT EXISTS trades_address ON trades(address);
CREATE TABLE IF NOT EXISTS listing_snapshots (
    id INTEGER PRIMARY KEY, source TEXT NOT NULL, listing_id TEXT NOT NULL,
    observed_at TEXT NOT NULL, region_code TEXT NOT NULL,
    apartment TEXT NOT NULL, address TEXT NOT NULL, dong TEXT NOT NULL,
    area_m2 REAL NOT NULL CHECK(area_m2 > 0), price_man INTEGER NOT NULL CHECK(price_man > 0),
    floor INTEGER, status TEXT NOT NULL CHECK(status IN ('active','withdrawn','sold')),
    latitude REAL, longitude REAL, source_url TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL,
    UNIQUE(source, listing_id, observed_at)
);
CREATE INDEX IF NOT EXISTS listings_latest ON listing_snapshots(source, listing_id, observed_at DESC);
CREATE TABLE IF NOT EXISTS geocodes (
    address TEXT PRIMARY KEY, latitude REAL NOT NULL, longitude REAL NOT NULL,
    provider TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY, source TEXT NOT NULL, scope TEXT NOT NULL,
    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_pages (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, page_no INTEGER NOT NULL,
    endpoint TEXT NOT NULL, request_json TEXT NOT NULL,
    response_xml BLOB NOT NULL, received_at TEXT NOT NULL,
    UNIQUE(run_id,page_no)
);
CREATE TABLE IF NOT EXISTS api_items (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, page_no INTEGER NOT NULL,
    item_no INTEGER NOT NULL, region_code TEXT NOT NULL, deal_month TEXT NOT NULL,
    item_json TEXT NOT NULL, UNIQUE(run_id,page_no,item_no)
);
CREATE INDEX IF NOT EXISTS api_items_scope ON api_items(region_code,deal_month,run_id);
CREATE TABLE IF NOT EXISTS collection_targets (
    id INTEGER PRIMARY KEY, region_code TEXT NOT NULL UNIQUE, region_name TEXT NOT NULL,
    schedule_kind TEXT NOT NULL CHECK(schedule_kind IN ('interval','daily')),
    interval_minutes INTEGER NOT NULL, daily_time TEXT NOT NULL,
    lookback_months INTEGER NOT NULL, enabled INTEGER NOT NULL,
    next_run_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_jobs (
    id INTEGER PRIMARY KEY, target_id INTEGER, kind TEXT NOT NULL,
    region_code TEXT NOT NULL, region_name TEXT NOT NULL, months_json TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
    completed_months INTEGER NOT NULL DEFAULT 0, row_count INTEGER NOT NULL DEFAULT 0,
    current_month TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_status ON collection_jobs(status,id);
CREATE TABLE IF NOT EXISTS worker_state (
    id INTEGER PRIMARY KEY CHECK(id=1), heartbeat_at TEXT NOT NULL, status TEXT NOT NULL
);
"""


@contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize(path):
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        for table in ("collection_targets", "collection_jobs"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "dong_filter" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN dong_filter TEXT NOT NULL DEFAULT '[]'")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(collection_targets)")}
        if "display_name" not in columns:
            conn.execute("ALTER TABLE collection_targets ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        conn.execute("PRAGMA user_version=2")


TRADE_FIELDS = ("region_code", "deal_month", "apartment", "address", "dong", "deal_date",
                "area_m2", "price_man", "floor", "build_year", "cancelled", "latitude",
                "longitude", "source", "raw_json", "collected_at")


def replace_trade_partition(path, region, month, rows, source="molit"):
    """Replace only a fully fetched region/month; preserve indistinguishable sales."""
    if any(r["region_code"] != region or r["deal_month"] != month or r["source"] != source for r in rows):
        raise ValueError("수집 범위와 거래 데이터가 일치하지 않습니다.")
    with connect(path) as conn:
        conn.execute("DELETE FROM trades WHERE region_code=? AND deal_month=? AND source=?",
                     (region, month, source))
        conn.executemany(
            f"INSERT INTO trades ({','.join(TRADE_FIELDS)}) VALUES ({','.join('?' for _ in TRADE_FIELDS)})",
            [tuple(r.get(k) for k in TRADE_FIELDS) for r in rows],
        )


def start_run(path, source, scope):
    with connect(path) as conn:
        return conn.execute(
            "INSERT INTO collection_runs(source,scope,started_at,status) VALUES(?,?,?,'running')",
            (source, scope, now_iso())).lastrowid


def finish_run(path, run_id, count=0, error=None):
    with connect(path) as conn:
        conn.execute("UPDATE collection_runs SET finished_at=?,status=?,row_count=?,message=? WHERE id=?",
                     (now_iso(), "failed" if error else "success", count, error or "", run_id))


def backup(path, destination):
    destination = Path(destination)
    if Path(path).resolve() == destination.resolve() or destination.exists():
        raise ValueError("백업은 기존 파일과 다른 새 경로를 지정하세요.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        target = sqlite3.connect(destination)
        try:
            conn.backup(target)
        finally:
            target.close()


def raw_json(item):
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def encode_response_xml(content):
    """Compress provider XML while keeping legacy uncompressed rows readable."""
    return zlib.compress(bytes(content), level=9)


def decode_response_xml(content):
    payload = bytes(content)
    if payload.lstrip().startswith(b"<"):
        return payload
    return zlib.decompress(payload)


def compact_api_archive(path):
    """Compress legacy XML and remove the duplicate per-item archive.

    Every API field remains in api_pages.response_xml. Normalized records also
    retain their original item JSON in trades.raw_json.
    """
    with connect(path) as conn:
        pages = conn.execute("SELECT id,response_xml FROM api_pages").fetchall()
        for page in pages:
            payload = bytes(page["response_xml"])
            if payload.lstrip().startswith(b"<"):
                conn.execute("UPDATE api_pages SET response_xml=? WHERE id=?",
                             (encode_response_xml(payload), page["id"]))
        conn.execute("DELETE FROM api_items")
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()

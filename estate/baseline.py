"""Build and package the default historical transaction baseline."""
import gzip
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path

from estate.config import api_endpoint, service_key
from estate.db import compact_api_archive, connect, initialize, now_iso
from estate.molit import collect, months_between
from estate.scheduler import DEFAULT_TARGETS, ensure_defaults


def completed_scopes(path):
    with connect(path) as conn:
        return {row[0] for row in conn.execute(
            "SELECT DISTINCT scope FROM collection_runs WHERE source='molit' AND status='success'")}


def build_baseline(path, start="200001", end=None, reporter=print):
    """Collect every missing default-region month, safely resuming completed work."""
    end = end or date.today().strftime("%Y%m")
    months = months_between(start, end)
    key, endpoint = service_key(), api_endpoint()
    if not key:
        raise ValueError("일반인증키.txt 또는 MOLIT_SERVICE_KEY를 설정하세요.")
    initialize(path)
    ensure_defaults(path)
    done = completed_scopes(path)
    total = len(DEFAULT_TARGETS) * len(months)
    finished = 0
    for region, region_name, display_name, dongs in DEFAULT_TARGETS:
        for month in months:
            scope = f"{region}/{month}"
            finished += 1
            if scope in done:
                reporter(f"[{finished}/{total}] {display_name} {month}: already collected")
                continue
            count = collect(path, key, region, month, region_name, endpoint=endpoint, dongs=dongs)
            reporter(f"[{finished}/{total}] {display_name} {month}: {count:,} rows")
    with connect(path) as conn:
        conn.execute("INSERT INTO metadata(key,value) VALUES('baseline_range',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (json.dumps({"start": start, "end": end, "completed_at": now_iso()},
                                 ensure_ascii=False),))
    compact_api_archive(path)


def package_database(path, destination=None):
    """Create a consistent, read-only public dataset from the local WAL database."""
    path = Path(path)
    destination = Path(destination or path.with_suffix(path.suffix + ".gz"))
    if not path.exists():
        raise ValueError("로컬 데이터베이스가 없습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="estate-publish-", dir=destination.parent) as working:
        snapshot = Path(working) / "public.sqlite3"
        with closing(sqlite3.connect(path, timeout=30)) as source, closing(sqlite3.connect(snapshot)) as target:
            if source.execute("SELECT COUNT(*) FROM collection_jobs WHERE status='running'").fetchone()[0]:
                raise ValueError("실행 중인 수집 작업이 끝난 뒤 배포 데이터를 만드세요.")
            source.backup(target)
            for table in ("collection_jobs", "worker_state", "collection_runs",
                          "api_pages", "api_items"):
                target.execute(f"DELETE FROM {table}")
            target.execute("DELETE FROM metadata WHERE key NOT IN ('baseline_range')")
            target.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('baseline_range','public-snapshot')")
            target.execute("INSERT INTO metadata(key,value) VALUES('snapshot_created_at',?)", (now_iso(),))
            target.commit()
            target.execute("VACUUM")
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("배포 데이터 검증에 실패했습니다.")
        # Create the final temporary file in the destination directory so it
        # inherits that directory's Windows ACL (including the Git user's access).
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            with snapshot.open("rb") as source, gzip.open(temporary, "wb", compresslevel=9) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination

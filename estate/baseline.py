"""Build and package the default historical transaction baseline."""
import gzip
import json
import shutil
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
    """Create the compressed immutable seed used by Streamlit deployments."""
    path = Path(path)
    destination = Path(destination or path.with_suffix(path.suffix + ".gz"))
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=9) as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    temporary.replace(destination)
    return destination

import json
import gzip
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import Mock

import pytest

from estate.config import api_endpoint, service_key
from estate.db import connect, decode_response_xml, initialize
from estate.scheduler import (claim_job, enqueue, enqueue_due, ensure_defaults, execute_job,
                              next_due, recent_months, save_target, targets, toggle_target)
from estate.worker import WorkerLock
from estate.molit import collect
from test_pipeline import client_for, trade_item, xml_page


@pytest.fixture
def scheduled_db(tmp_path):
    path = tmp_path / "scheduled.sqlite3"
    initialize(path)
    ensure_defaults(path)
    return path


def test_config_files_and_endpoint_normalization(tmp_path, monkeypatch):
    import estate.config as config
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("MOLIT_SERVICE_KEY", raising=False)
    monkeypatch.delenv("MOLIT_ENDPOINT", raising=False)
    (tmp_path / "일반인증키.txt").write_text("\ufeffsecret\n", encoding="utf-8")
    (tmp_path / "엔드포인트.txt").write_text("https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade", encoding="utf-8")
    assert service_key() == "secret"
    assert api_endpoint().endswith("/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade")
    monkeypatch.setenv("MOLIT_ENDPOINT", "https://evil.example/collect")
    with pytest.raises(ValueError):
        api_endpoint()


def test_packaged_baseline_replaces_legacy_empty_database(tmp_path, monkeypatch):
    import estate.config as config
    source = tmp_path / "source.sqlite3"
    initialize(source)
    with connect(source) as conn:
        conn.execute("INSERT INTO metadata VALUES('baseline_range','200001-202609')")
    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    runtime = data_dir / "estate.sqlite3"
    initialize(runtime)
    with source.open("rb") as raw, gzip.open(data_dir / "estate.sqlite3.gz", "wb") as packed:
        shutil.copyfileobj(raw, packed)
    monkeypatch.setenv("REAL_ESTATE_DATA_DIR", str(data_dir))
    assert config.db_path() == runtime
    with connect(runtime) as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key='baseline_range'").fetchone()[0] == "200001-202609"


def test_concurrent_packaged_database_restore_uses_separate_temporary_files(tmp_path, monkeypatch):
    import estate.config as config
    source = tmp_path / "source.sqlite3"
    initialize(source)
    with connect(source) as conn:
        conn.execute("INSERT INTO metadata VALUES('baseline_range','200001-202609')")
    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    with source.open("rb") as raw, gzip.open(data_dir / "estate.sqlite3.gz", "wb") as packed:
        shutil.copyfileobj(raw, packed)
    monkeypatch.setenv("REAL_ESTATE_DATA_DIR", str(data_dir))
    rendezvous = Barrier(2)
    original_copy = shutil.copyfileobj
    copies = []

    def synchronized_copy(source_file, target_file):
        copies.append(target_file.name)
        time.sleep(0.1)
        return original_copy(source_file, target_file)

    def restore(_):
        rendezvous.wait(timeout=5)
        return config.db_path()

    monkeypatch.setattr(config.shutil, "copyfileobj", synchronized_copy)
    with ThreadPoolExecutor(max_workers=2) as pool:
        restored = list(pool.map(restore, range(2)))
    assert restored == [data_dir / "estate.sqlite3"] * 2
    assert len(copies) == 1
    assert not list(data_dir.glob("*.tmp"))
    with connect(restored[0]) as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key='baseline_range'").fetchone()[0] == "200001-202609"


def test_defaults_daily_kst_and_idempotent(scheduled_db):
    ensure_defaults(scheduled_db)
    saved = targets(scheduled_db)
    assert len(saved) == 3
    assert {r["region_code"] for r in saved} == {"41465", "41135", "41117"}
    assert all(r["schedule_kind"] == "daily" and r["daily_time"] == "06:00" for r in saved)
    now = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)  # KST 05:00
    assert next_due("daily", now=now) == "2026-09-18T21:00:00+00:00"
    assert next_due("daily", now=datetime(2026, 9, 18, 22, tzinfo=timezone.utc)) == "2026-09-19T21:00:00+00:00"
    assert recent_months(12, now)[0] == "202510"


def test_due_only_enabled_regions_once_and_pause(scheduled_db):
    now = datetime(2026, 9, 19, 0, tzinfo=timezone.utc)
    with connect(scheduled_db) as conn:
        conn.execute("UPDATE collection_targets SET next_run_at='2026-09-18T00:00:00+00:00'")
    toggle_target(scheduled_db, 3, False)
    enqueue_due(scheduled_db, now)
    enqueue_due(scheduled_db, now)
    with connect(scheduled_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM collection_jobs").fetchone()[0] == 2
    toggle_target(scheduled_db, 1, False)
    assert claim_job(scheduled_db)["target_id"] == 2
    assert claim_job(scheduled_db) is None


def test_duplicate_queue_scope_change_and_resume_progress(scheduled_db, monkeypatch):
    enqueue(scheduled_db, 1, "202601", "202602")
    with pytest.raises(ValueError):
        enqueue(scheduled_db, 1)
    with pytest.raises(ValueError):
        save_target(scheduled_db, "41465", "경기도 용인시 수지구", "수지", ["죽전동"])
    job = claim_job(scheduled_db)
    assert claim_job(scheduled_db) is None
    # A previous completed month is not re-counted after a restart.
    with connect(scheduled_db) as conn:
        conn.execute("UPDATE collection_jobs SET completed_months=1,row_count=10 WHERE id=?", (job["id"],))
    job["completed_months"] = 1
    monkeypatch.setattr("estate.scheduler.service_key", lambda: "private-key")
    monkeypatch.setattr("estate.scheduler.kakao_key", lambda: "coordinate-key")
    geocoder = Mock(return_value=(2, 0))
    monkeypatch.setattr("estate.scheduler.geocode_pending", geocoder)
    public_geocoder = Mock(return_value=(0, 0))
    monkeypatch.setattr("estate.scheduler.geocode_pending_arcgis", public_geocoder)
    collector = Mock(return_value=7)
    execute_job(scheduled_db, job, collector)
    assert collector.call_count == 1 and collector.call_args.args[3] == "202602"
    geocoder.assert_called_once_with(scheduled_db, "coordinate-key", limit=1_000_000, region="41465")
    public_geocoder.assert_called_once_with(scheduled_db, limit=1_000_000, region="41465")
    with connect(scheduled_db) as conn:
        saved = conn.execute("SELECT * FROM collection_jobs WHERE id=?", (job["id"],)).fetchone()
        assert saved["status"] == "success" and saved["row_count"] == 17
        assert "좌표 자동 보강 2건" in saved["message"]


def test_job_failure_keeps_month_progress_and_masks_error(scheduled_db, monkeypatch):
    enqueue(scheduled_db, 1, "202601", "202602")
    job = claim_job(scheduled_db)
    monkeypatch.setattr("estate.scheduler.service_key", lambda: "private-key")
    execute_job(scheduled_db, job, Mock(side_effect=[3, ValueError("private-key")]))
    with connect(scheduled_db) as conn:
        saved = conn.execute("SELECT * FROM collection_jobs WHERE id=?", (job["id"],)).fetchone()
        assert saved["status"] == "failed" and saved["completed_months"] == 1
        assert "private-key" not in saved["message"]


@pytest.mark.parametrize("lookup_result", [(1, 0), ValueError("private-address-key")])
def test_address_lookup_never_blocks_coordinate_refresh(scheduled_db, monkeypatch, lookup_result):
    enqueue(scheduled_db, 1, "202601", "202601")
    job = claim_job(scheduled_db)
    monkeypatch.setattr("estate.scheduler.service_key", lambda: "private-trade-key")
    monkeypatch.setattr("estate.scheduler.juso_address_search_key", lambda: "private-address-key")
    monkeypatch.setattr("estate.scheduler.kakao_key", lambda: "")
    lookup = Mock(side_effect=lookup_result) if isinstance(lookup_result, Exception) else Mock(return_value=lookup_result)
    coordinate = Mock(return_value=(2, 0))
    monkeypatch.setattr("estate.scheduler.collect_address_lookups", lookup)
    monkeypatch.setattr("estate.scheduler.geocode_pending_arcgis", coordinate)
    execute_job(scheduled_db, job, Mock(return_value=1))
    lookup.assert_called_once_with(scheduled_db, "private-address-key", limit=500, region="41465")
    coordinate.assert_called_once()
    with connect(scheduled_db) as conn:
        saved = conn.execute("SELECT status,message FROM collection_jobs WHERE id=?", (job["id"],)).fetchone()
        assert saved["status"] == "success"
        assert "좌표 자동 보강 2건" in saved["message"]
        assert "private-address-key" not in saved["message"]


def test_all_api_fields_archive_and_dong_filter(scheduled_db):
    items = [trade_item(umdNm="이의동", sggCd="41117", newFutureField="retained"),
             trade_item(umdNm="매탄동", sggCd="41117")]
    count = collect(scheduled_db, "test-secret", "41117", "202601", "경기도 수원시 영통구",
                    client=client_for(xml_page(items)), dongs=["이의동", "하동"])
    assert count == 1
    with connect(scheduled_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM api_items").fetchone()[0] == 0
        page = conn.execute("SELECT request_json,response_xml FROM api_pages").fetchone()
        assert b"newFutureField" in decode_response_xml(page["response_xml"])
        assert "serviceKey" not in page["request_json"]


def test_single_worker_lock(scheduled_db):
    first, second = WorkerLock(scheduled_db), WorkerLock(scheduled_db)
    try:
        assert first.acquire()
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_schema_upgrade_keeps_existing_trades(scheduled_db):
    with connect(scheduled_db) as conn:
        conn.execute("PRAGMA user_version=1")
        conn.execute("INSERT INTO metadata VALUES('preserve','yes')")
    initialize(scheduled_db)
    with connect(scheduled_db) as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key='preserve'").fetchone()[0] == "yes"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3

import gzip
import shutil

import pytest

from estate.admin_access import local_admin_allowed
from estate.baseline import package_database
from estate.db import connect, initialize, start_run
from estate.scheduler import delete_target, enqueue, ensure_defaults, targets


def test_admin_requires_explicit_loopback_launch_and_rejects_cloud():
    assert local_admin_allowed("127.0.0.1", {"ESTATE_ADMIN_LOCAL": "1"})
    assert not local_admin_allowed("0.0.0.0", {"ESTATE_ADMIN_LOCAL": "1"})
    assert not local_admin_allowed("127.0.0.1", {})
    assert not local_admin_allowed("127.0.0.1", {"ESTATE_ADMIN_LOCAL": "1", "IS_STREAMLIT_CLOUD": "1"})


def test_delete_target_cancels_queued_jobs_without_deleting_data(tmp_path):
    path = tmp_path / "estate.sqlite3"
    initialize(path)
    ensure_defaults(path)
    job = enqueue(path, 1, "202601", "202601")
    with connect(path) as conn:
        conn.execute("INSERT INTO geocodes VALUES('아파트 주소',37.3,127.1,'test','2026-09-21')")
    delete_target(path, 1)
    ensure_defaults(path)
    with connect(path) as conn:
        assert conn.execute("SELECT status FROM collection_jobs WHERE id=?", (job,)).fetchone()[0] == "cancelled"
        assert conn.execute("SELECT COUNT(*) FROM geocodes").fetchone()[0] == 1
    assert len(targets(path)) == 2
    with pytest.raises(ValueError):
        delete_target(path, 1)


def test_public_snapshot_uses_online_backup_and_strips_admin_archive(tmp_path):
    path = tmp_path / "estate.sqlite3"
    initialize(path)
    ensure_defaults(path)
    with connect(path) as conn:
        conn.execute("INSERT INTO metadata VALUES('baseline_range','200001-202609')")
        conn.execute("INSERT INTO geocodes VALUES('새 주소',37.3,127.1,'test','2026-09-21')")
        conn.execute("INSERT INTO address_lookups VALUES('새 주소','exact','{}','{}','2026-09-21')")
    start_run(path, "molit", "41465/202609")
    packed = package_database(path)
    restored = tmp_path / "public.sqlite3"
    with gzip.open(packed, "rb") as source, restored.open("wb") as target:
        shutil.copyfileobj(source, target)
    with connect(restored) as conn:
        assert conn.execute("SELECT COUNT(*) FROM geocodes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM collection_targets").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM collection_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM address_lookups").fetchone()[0] == 0
        assert conn.execute("SELECT value FROM metadata WHERE key='snapshot_created_at'").fetchone()[0]
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0] == 1

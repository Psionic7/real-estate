"""Persistent region schedules and sequential collection job queue."""
import json
import re
from datetime import datetime, timedelta, timezone

from estate.config import api_endpoint, juso_address_search_key, kakao_key, service_key
from estate.db import connect, now_iso
from estate.geocode import geocode_pending, geocode_pending_arcgis
from estate.juso import collect_address_lookups
from estate.molit import collect, months_between, validate_scope

KST = timezone(timedelta(hours=9))
DEFAULT_TARGETS = [
    ("41465", "경기도 용인시 수지구", "용인 수지", []),
    ("41135", "경기도 성남시 분당구", "성남 분당", []),
    ("41117", "경기도 수원시 영통구", "수원 광교", ["이의동", "하동", "원천동"]),
]


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def recent_months(count, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    count = int(count)
    if not 1 <= count <= 300:
        raise ValueError("수집 기간은 1~300개월입니다.")
    offset = now.year * 12 + now.month - count
    return months_between(f"{offset // 12:04d}{offset % 12 + 1:02d}", now.strftime("%Y%m"))


def next_due(kind, minutes=1440, daily_time="06:00", now=None):
    now = now or datetime.now(timezone.utc)
    if kind == "interval":
        if not 60 <= int(minutes) <= 43200:
            raise ValueError("반복 간격은 60~43,200분입니다.")
        return iso(now + timedelta(minutes=int(minutes)))
    if kind != "daily" or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_time):
        raise ValueError("매일 실행 시각은 HH:MM 형식이어야 합니다.")
    hour, minute = map(int, daily_time.split(":"))
    candidate = now.astimezone(KST).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return iso(candidate)


def clean_dongs(dongs):
    if isinstance(dongs, str):
        dongs = dongs.split(",")
    values = sorted(set(d.strip() for d in dongs if d.strip()))
    if any(len(d) > 40 for d in values) or len(values) > 200:
        raise ValueError("법정동 목록을 확인하세요.")
    return values


def save_target(path, region, name, display_name, dongs=(), kind="daily", minutes=1440,
                daily_time="06:00", lookback=12, enabled=True):
    region, name = region.strip(), name.strip()
    validate_scope(region, datetime.now(KST).strftime("%Y%m"))
    if not name or len(name) > 100:
        raise ValueError("시도·시군구 전체 이름을 입력하세요.")
    recent_months(lookback)
    due = next_due(kind, minutes, daily_time)
    values = (region, name, kind, int(minutes), daily_time, int(lookback), int(enabled), due,
              now_iso(), json.dumps(clean_dongs(dongs), ensure_ascii=False), display_name.strip() or name)
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone():
            raise ValueError("데모 DB에 실제 수집을 설정할 수 없습니다.")
        # Avoid changing the scope while an older request is still in flight.
        busy = conn.execute("SELECT 1 FROM collection_jobs WHERE region_code=? AND status IN ('queued','running')", (region,)).fetchone()
        if busy:
            raise ValueError("해당 지역의 수집이 대기/실행 중입니다. 완료 후 설정을 변경하세요.")
        conn.execute("""INSERT INTO collection_targets(region_code,region_name,schedule_kind,interval_minutes,
            daily_time,lookback_months,enabled,next_run_at,updated_at,dong_filter,display_name)
            VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(region_code) DO UPDATE SET
            region_name=excluded.region_name,schedule_kind=excluded.schedule_kind,
            interval_minutes=excluded.interval_minutes,daily_time=excluded.daily_time,
            lookback_months=excluded.lookback_months,enabled=excluded.enabled,next_run_at=excluded.next_run_at,
            updated_at=excluded.updated_at,dong_filter=excluded.dong_filter,display_name=excluded.display_name""", values)
        return conn.execute("SELECT id FROM collection_targets WHERE region_code=?", (region,)).fetchone()[0]


def ensure_defaults(path):
    with connect(path) as conn:
        if conn.execute("SELECT 1 FROM metadata WHERE key='targets_initialized'").fetchone():
            return
        for code, name, label, dongs in DEFAULT_TARGETS:
            conn.execute("""INSERT OR IGNORE INTO collection_targets(region_code,region_name,display_name,dong_filter,
                schedule_kind,interval_minutes,daily_time,lookback_months,enabled,next_run_at,updated_at)
                VALUES(?,?,?,?,'daily',1440,'06:00',12,1,?,?)""",
                (code, name, label, json.dumps(dongs, ensure_ascii=False), next_due("daily"), now_iso()))
        conn.execute("INSERT OR IGNORE INTO metadata VALUES('targets_initialized',?)", (now_iso(),))


def targets(path):
    with connect(path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM collection_targets ORDER BY id")]


def enqueue(path, target_id, start=None, end=None, kind="manual", now=None):
    now = now or datetime.now(timezone.utc)
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute("SELECT * FROM collection_targets WHERE id=?", (target_id,)).fetchone()
        if target is None:
            raise ValueError("수집 지역을 먼저 저장하세요.")
        months = months_between(start, end) if start and end else recent_months(target["lookback_months"], now)
        if len(months) > 300:
            raise ValueError("한 번의 수집은 최대 300개월입니다.")
        if conn.execute("SELECT 1 FROM collection_jobs WHERE region_code=? AND status IN ('queued','running')",
                        (target["region_code"],)).fetchone():
            raise ValueError("이 지역은 이미 수집 대기 또는 실행 중입니다.")
        return conn.execute("""INSERT INTO collection_jobs(target_id,kind,region_code,region_name,months_json,
            status,created_at,dong_filter) VALUES(?,?,?,?,?,'queued',?,?)""",
            (target_id, kind, target["region_code"], target["region_name"], json.dumps(months),
             iso(now), target["dong_filter"])).lastrowid


def enqueue_due(path, now=None):
    now = now or datetime.now(timezone.utc)
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        due = conn.execute("SELECT * FROM collection_targets WHERE enabled=1 AND next_run_at<=?", (iso(now),)).fetchall()
        for target in due:
            busy = conn.execute("SELECT 1 FROM collection_jobs WHERE region_code=? AND status IN ('queued','running')",
                                (target["region_code"],)).fetchone()
            if busy:
                continue
            months = recent_months(target["lookback_months"], now)
            conn.execute("""INSERT INTO collection_jobs(target_id,kind,region_code,region_name,months_json,
                status,created_at,dong_filter) VALUES(?,'scheduled',?,?,?,'queued',?,?)""",
                (target["id"], target["region_code"], target["region_name"], json.dumps(months), iso(now), target["dong_filter"]))
            conn.execute("UPDATE collection_targets SET next_run_at=? WHERE id=?",
                         (next_due(target["schedule_kind"], target["interval_minutes"], target["daily_time"], now), target["id"]))


def claim_job(path):
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute("SELECT * FROM collection_jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not job:
            return None
        conn.execute("UPDATE collection_jobs SET status='running',started_at=?,message='' WHERE id=?", (now_iso(), job["id"]))
        return dict(job)


def execute_job(path, job, collector=collect):
    try:
        key, endpoint = service_key(), api_endpoint()
        if not key:
            raise ValueError("일반인증키.txt 또는 MOLIT_SERVICE_KEY를 설정하세요.")
        months = json.loads(job["months_json"])
        # Progress is committed per month. After a crash the unfinished month is retried.
        for index in range(job["completed_months"], len(months)):
            month = months[index]
            with connect(path) as conn:
                conn.execute("UPDATE collection_jobs SET current_month=? WHERE id=?", (month, job["id"]))
            count = collector(path, key, job["region_code"], month, job["region_name"],
                              endpoint=endpoint, dongs=json.loads(job["dong_filter"]))
            with connect(path) as conn:
                conn.execute("UPDATE collection_jobs SET completed_months=?,row_count=row_count+? WHERE id=?",
                             (index + 1, count, job["id"]))
        messages = []
        address_key = juso_address_search_key()
        if address_key:
            try:
                exact, unresolved = collect_address_lookups(
                    path, address_key, limit=500, region=job["region_code"])
                messages.append(f"주소 확인 {exact}건 · 미확정 {unresolved}건")
            except Exception:
                messages.append("주소 검색 API 확인 실패")
        coordinate_key = kakao_key()
        try:
            matched = 0
            if coordinate_key:
                matched, unresolved = geocode_pending(path, coordinate_key, limit=1_000_000,
                                                       region=job["region_code"])
            public_matched, unresolved = geocode_pending_arcgis(path, limit=1_000_000,
                                                                region=job["region_code"])
            messages.append(f"좌표 자동 보강 {matched + public_matched}건 · 미확정 {unresolved}건")
        except Exception:
            messages.append("좌표 자동 보강 실패")
        with connect(path) as conn:
            conn.execute("UPDATE collection_jobs SET status='success',finished_at=?,current_month='',message=? WHERE id=?",
                         (now_iso(), " · ".join(messages), job["id"]))
    except Exception:
        # Do not leak keys, request URLs, or untrusted provider errors into job logs.
        with connect(path) as conn:
            conn.execute("UPDATE collection_jobs SET status='failed',finished_at=?,message=? WHERE id=?",
                         (now_iso(), "수집 실패: 인증·연결·API 응답과 최근 수집 기록을 확인하세요. 완료된 월은 보존됩니다.", job["id"]))


def cancel_pending(path, job_id):
    with connect(path) as conn:
        conn.execute("UPDATE collection_jobs SET status='cancelled',finished_at=? WHERE id=? AND status='queued'", (now_iso(), job_id))


def toggle_target(path, target_id, enabled):
    with connect(path) as conn:
        conn.execute("UPDATE collection_targets SET enabled=?,updated_at=? WHERE id=?", (int(enabled), now_iso(), target_id))
        if not enabled:
            conn.execute("UPDATE collection_jobs SET status='cancelled',finished_at=? "
                         "WHERE target_id=? AND kind='scheduled' AND status='queued'", (now_iso(), target_id))


def delete_target(path, target_id):
    """Stop collecting a region without erasing its historical transactions."""
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute("SELECT id FROM collection_targets WHERE id=?", (target_id,)).fetchone()
        if target is None:
            raise ValueError("삭제할 수집 지역이 없습니다.")
        running = conn.execute("SELECT 1 FROM collection_jobs WHERE target_id=? AND status='running'",
                               (target_id,)).fetchone()
        if running:
            raise ValueError("이 지역의 수집이 실행 중입니다. 완료된 뒤 삭제하세요.")
        conn.execute("UPDATE collection_jobs SET status='cancelled',finished_at=? "
                     "WHERE target_id=? AND status='queued'", (now_iso(), target_id))
        conn.execute("DELETE FROM collection_targets WHERE id=?", (target_id,))

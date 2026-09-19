"""One local worker per SQLite DB; independent of browser session lifetime."""
import argparse
import os
import threading
import time
from pathlib import Path

from estate.config import db_path
from estate.db import connect, initialize, now_iso
from estate.scheduler import claim_job, enqueue_due, ensure_defaults, execute_job


class WorkerLock:
    def __init__(self, path):
        self.path = Path(str(path) + ".worker.lock")
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.file.close()
            self.file = None
            return False

    def release(self):
        if self.file:
            self.file.close()
            self.file = None


def heartbeat(path, status="running"):
    with connect(path) as conn:
        conn.execute("INSERT INTO worker_state VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET "
                     "heartbeat_at=excluded.heartbeat_at,status=excluded.status", (now_iso(), status))


def recover_interrupted(path):
    # Must only be called after acquiring the exclusive OS lock.
    with connect(path) as conn:
        conn.execute("UPDATE collection_jobs SET status='queued',message='중단된 작업 재개' WHERE status='running'")
        conn.execute("UPDATE collection_runs SET status='failed',finished_at=?,message='프로세스 중단 후 재수집' "
                     "WHERE status='running'", (now_iso(),))


def serve(path, stop=None):
    stop = stop or threading.Event()
    initialize(path)
    lock = WorkerLock(path)
    if not lock.acquire():
        return
    pulse_stop = threading.Event()
    def pulse():
        while not pulse_stop.wait(10):
            try:
                heartbeat(path)
            except Exception:
                pass
    pulse_thread = threading.Thread(target=pulse, daemon=True)
    try:
        with connect(path) as conn:
            if conn.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone():
                return
        recover_interrupted(path)
        heartbeat(path)
        pulse_thread.start()
        while not stop.is_set():
            try:
                enqueue_due(path)
                job = claim_job(path)
                if job:
                    execute_job(path, job)
                else:
                    stop.wait(3)
            except Exception:
                # Retry infrastructure failures without exposing provider secrets.
                stop.wait(10)
    finally:
        pulse_stop.set()
        if pulse_thread.is_alive():
            pulse_thread.join(timeout=12)
        heartbeat(path, "stopped")
        lock.release()


def start_background(path):
    if os.getenv("ESTATE_DISABLE_WORKER") == "1":
        return None
    def supervise():
        while True:
            try:
                serve(path)
            except Exception:
                pass
            time.sleep(5)
    thread = threading.Thread(target=supervise, name="estate-collector", daemon=True)
    thread.start()
    return thread


def main():
    parser = argparse.ArgumentParser(description="지역별 실거래 수집 워커")
    parser.add_argument("--once", action="store_true", help="대기 작업을 처리한 뒤 종료")
    args = parser.parse_args()
    path = db_path()
    initialize(path)
    ensure_defaults(path)
    if args.once:
        lock = WorkerLock(path)
        if not lock.acquire():
            return  # The web worker already owns the queue; a successful no-op.
        try:
            recover_interrupted(path)
            heartbeat(path)
            enqueue_due(path)
            while job := claim_job(path):
                heartbeat(path)
                execute_job(path, job)
                print(f"Processed job {job['id']}", flush=True)
        finally:
            heartbeat(path, "stopped")
            lock.release()
    else:
        serve(path)


if __name__ == "__main__":
    main()

import gzip
import os
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def data_dir() -> Path:
    path = Path(os.getenv("REAL_ESTATE_DATA_DIR", "data"))
    return path if path.is_absolute() else ROOT / path


def has_historical_baseline(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key='baseline_range'").fetchone()
            return bool(row)
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def db_path() -> Path:
    path = data_dir() / "estate.sqlite3"
    packaged = path.with_suffix(path.suffix + ".gz")
    if packaged.exists() and not has_historical_baseline(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with gzip.open(packaged, "rb") as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def read_setting(env_name, filenames, default=""):
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    if isinstance(filenames, str):
        filenames = [filenames]
    for filename in filenames:
        path = ROOT / filename
        if path.exists():
            return path.read_text(encoding="utf-8-sig").strip()
    return default


def service_key():
    return read_setting("MOLIT_SERVICE_KEY", ["api-key.txt", "일반인증키.txt"])


def api_endpoint():
    value = read_setting("MOLIT_ENDPOINT", ["end-point.txt", "엔드포인트.txt"],
                         "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "apis.data.go.kr" or parsed.query or parsed.fragment:
        raise ValueError("엔드포인트는 인증정보 없는 공공데이터포털 HTTPS 주소여야 합니다.")
    base = "https://apis.data.go.kr/1613000/"
    for service in ("RTMSDataSvcAptTrade", "RTMSDataSvcAptTradeDev"):
        endpoint = base + service
        if value.rstrip("/") in (endpoint, endpoint + "/get" + service):
            return endpoint + "/get" + service
    raise ValueError("현재 아파트 매매 일반/상세 API 엔드포인트를 지원합니다.")

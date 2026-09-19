import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def data_dir() -> Path:
    path = Path(os.getenv("REAL_ESTATE_DATA_DIR", "data"))
    return path if path.is_absolute() else ROOT / path


def db_path(demo: bool = False) -> Path:
    return data_dir() / ("demo.sqlite3" if demo else "estate.sqlite3")


def read_setting(env_name, filename, default=""):
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    path = ROOT / filename
    return path.read_text(encoding="utf-8-sig").strip() if path.exists() else default


def service_key():
    return read_setting("MOLIT_SERVICE_KEY", "일반인증키.txt")


def api_endpoint():
    value = read_setting("MOLIT_ENDPOINT", "엔드포인트.txt",
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

import csv
import io
import json
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from estate.db import connect, finish_run, now_iso, start_run
from estate.http import DataSourceError, get, session

FIELDS = ["source", "listing_id", "observed_at", "region_code", "apartment", "address", "dong",
          "area_m2", "price_man", "floor", "status", "latitude", "longitude", "source_url"]


def parse_payload(payload: bytes, extension: str):
    if len(payload) > 10 * 1024 * 1024:
        raise ValueError("파일은 10MB 이하여야 합니다.")
    try:
        text = payload.decode("utf-8-sig")
        if extension.lower() == ".csv":
            rows = list(csv.DictReader(io.StringIO(text)))
        elif extension.lower() == ".json":
            rows = json.loads(text)
        else:
            raise ValueError("CSV 또는 JSON을 사용하세요.")
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error):
        raise ValueError("UTF-8 CSV 또는 JSON 배열 형식인지 확인하세요.") from None
    if not isinstance(rows, list) or not rows or len(rows) > 50000:
        raise ValueError("1~50,000개의 매물 객체가 필요합니다.")
    return validate_rows(rows)


def validate_rows(rows, now=None):
    now = now or datetime.now(timezone.utc)
    cleaned, seen = [], set()
    for index, row in enumerate(rows, 1):
        try:
            r = {}
            for field in ("source", "listing_id", "region_code", "apartment", "address", "dong", "status"):
                value = str(row.get(field) or "").strip()
                if not value or len(value) > 500:
                    raise ValueError(field)
                r[field] = value
            if not re.fullmatch(r"\d{5}", r["region_code"]):
                raise ValueError("region_code")
            if r["status"] not in {"active", "withdrawn", "sold"}:
                raise ValueError("status")
            stamp = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp > now + timedelta(minutes=5):
                raise ValueError("observed_at")
            r["observed_at"] = stamp.astimezone(timezone.utc).isoformat(timespec="seconds")
            r["area_m2"] = float(row["area_m2"])
            price = float(str(row["price_man"]).replace(",", ""))
            if not 0 < r["area_m2"] < 10000 or not math.isfinite(price) or price <= 0 or not price.is_integer():
                raise ValueError("area_m2/price_man")
            r["price_man"] = int(price)
            floor = row.get("floor")
            r["floor"] = int(str(floor)) if floor not in (None, "") else None
            lat, lon = row.get("latitude"), row.get("longitude")
            if lat in (None, "") and lon in (None, ""):
                r["latitude"], r["longitude"] = None, None
            else:
                lat, lon = float(lat), float(lon)
                if not (32 <= lat <= 39.5 and 124 <= lon <= 132):
                    raise ValueError("latitude/longitude")
                r["latitude"], r["longitude"] = lat, lon
            url = str(row.get("source_url") or "").strip()
            if url and (urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc):
                raise ValueError("source_url")
            r["source_url"] = url
            key = (r["source"], r["listing_id"], r["observed_at"])
            if key in seen:
                raise ValueError("중복 source/listing_id/observed_at")
            seen.add(key)
            cleaned.append(r)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise ValueError(f"{index}행 검증 실패: 필수 열, 날짜/시간대, 상태, 숫자와 좌표를 확인하세요.") from None
    return cleaned


def import_rows(path, rows):
    rows = validate_rows(rows)
    if not rows:
        raise ValueError("가져올 매물이 없습니다.")
    run = start_run(path, "listings", "snapshot import")
    try:
        inserted = 0
        with connect(path) as conn:
            for r in rows:
                old = conn.execute("SELECT * FROM listing_snapshots WHERE source=? AND listing_id=? AND observed_at=?",
                                   (r["source"], r["listing_id"], r["observed_at"])).fetchone()
                if old:
                    if any(old[k] != r.get(k) for k in FIELDS):
                        raise ValueError("동일 매물·확인 시각의 내용이 다릅니다. 확인 시각을 검토하세요.")
                    continue
                conn.execute(f"INSERT INTO listing_snapshots ({','.join(FIELDS)},imported_at) "
                             f"VALUES ({','.join('?' for _ in range(len(FIELDS) + 1))})",
                             [r.get(k) for k in FIELDS] + [now_iso()])
                inserted += 1
        finish_run(path, run, inserted)
        return inserted
    except Exception as exc:
        finish_run(path, run, error=str(exc) if isinstance(exc, ValueError) else "매물 저장 실패")
        raise


def fetch_feed(url, token=""):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("매물 피드는 인증정보가 URL에 포함되지 않은 HTTPS 주소여야 합니다.")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with session() as client:
        response = get(client, url, headers=headers, stream=True, allow_redirects=False)
        try:
            if response.status_code != 200:
                raise DataSourceError("매물 피드는 리디렉션 없는 200 응답이어야 합니다.")
            payload = bytearray()
            for chunk in response.iter_content(65536):
                payload.extend(chunk)
                if len(payload) > 10 * 1024 * 1024:
                    raise DataSourceError("매물 피드가 최대 크기 10MB를 초과했습니다.")
            return parse_payload(bytes(payload), ".json")
        finally:
            response.close()

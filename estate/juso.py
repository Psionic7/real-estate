"""Cache official Juso address-search results without treating them as coordinates."""
import json
import re

from estate.db import connect, now_iso
from estate.http import DataSourceError, get, session


SEARCH_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"


def _parcel_address(value):
    value = re.sub(r"\s*\([^)]*\)\s*$", "", str(value or ""))
    return " ".join(value.split())


def _same_parcel(query, candidate):
    query, candidate = _parcel_address(query), _parcel_address(candidate)
    # Juso often appends an apartment name to jibunAddr after the parcel number.
    # Require a whitespace boundary so parcel 176-1 never matches 176-10.
    return bool(query) and (candidate == query or candidate.startswith(query + " "))


def parse_search_result(address, payload):
    """Keep all returned fields; accept a match only for one exact parcel address."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, dict):
        raise DataSourceError("주소 검색 API 응답 형식이 올바르지 않습니다.")
    common = results.get("common")
    if not isinstance(common, dict):
        raise DataSourceError("주소 검색 API 응답 형식이 올바르지 않습니다.")
    if str(common.get("errorCode", "")) != "0":
        raise DataSourceError("주소 검색 API가 요청을 거부했습니다. 승인키 유형·이용 상태를 확인하세요.")
    candidates = results.get("juso") or []
    if not isinstance(candidates, list):
        raise DataSourceError("주소 검색 API 응답 형식이 올바르지 않습니다.")
    exact = [item for item in candidates if isinstance(item, dict)
             and _same_parcel(address, item.get("jibunAddr"))]
    if len(exact) == 1:
        return "exact", exact[0]
    return ("ambiguous" if len(exact) > 1 else "unmatched"), None


def search_address(client, key, address):
    if not key.strip():
        raise ValueError("JUSO_ADDRESS_SEARCH_KEY를 설정하세요.")
    response = get(client, SEARCH_URL, params={
        "confmKey": key, "currentPage": 1, "countPerPage": 100,
        "keyword": address, "resultType": "json",
    })
    try:
        payload = response.json()
    except ValueError:
        raise DataSourceError("주소 검색 API 응답이 JSON이 아닙니다.") from None
    status, match = parse_search_result(address, payload)
    return status, match, payload


def pending_lookups(path, limit=100, region=None, refresh=False):
    with connect(path) as conn:
        return [row[0] for row in conn.execute("""
            SELECT DISTINCT a.address FROM (
                SELECT address,region_code FROM trades WHERE address!=''
                UNION SELECT address,region_code FROM listing_snapshots WHERE address!=''
            ) a LEFT JOIN address_lookups j ON a.address=j.address
            WHERE (j.address IS NULL OR ?) AND (? IS NULL OR a.region_code=?)
            ORDER BY a.address LIMIT ?
        """, (int(refresh), region, region, limit))]


def collect_address_lookups(path, key, limit=100, region=None, refresh=False):
    if not key.strip():
        raise ValueError("JUSO_ADDRESS_SEARCH_KEY를 설정하세요.")
    addresses = pending_lookups(path, limit, region, refresh)
    exact_count = 0
    with session() as client:
        for address in addresses:
            status, match, payload = search_address(client, key, address)
            with connect(path) as conn:
                conn.execute("""INSERT INTO address_lookups
                    (address,status,matched_address_json,response_json,fetched_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET
                    status=excluded.status,matched_address_json=excluded.matched_address_json,
                    response_json=excluded.response_json,fetched_at=excluded.fetched_at""",
                    (address, status, json.dumps(match, ensure_ascii=False) if match else None,
                     json.dumps(payload, ensure_ascii=False), now_iso()))
            exact_count += status == "exact"
    return exact_count, len(addresses) - exact_count

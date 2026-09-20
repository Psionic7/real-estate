import re
import time
from datetime import date, datetime
from urllib.parse import unquote

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from estate.db import (connect, encode_response_xml, finish_run, now_iso, raw_json,
                       replace_trade_partition, start_run)
from estate.config import api_endpoint
from estate.http import DataSourceError, get, session

ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"


def validate_scope(region, month):
    if not re.fullmatch(r"\d{5}", region):
        raise ValueError("지역코드는 법정동 코드 앞 5자리여야 합니다.")
    if not re.fullmatch(r"\d{6}", month):
        raise ValueError("계약월은 YYYYMM 형식이어야 합니다.")
    try:
        datetime.strptime(month, "%Y%m")
    except ValueError:
        raise ValueError("유효하지 않은 계약월입니다.") from None
    if month > date.today().strftime("%Y%m"):
        raise ValueError("미래 계약월은 수집할 수 없습니다.")


def months_between(start, end):
    validate_scope("11110", start)
    validate_scope("11110", end)
    if start > end:
        raise ValueError("시작월이 종료월보다 늦습니다.")
    year, month = int(start[:4]), int(start[4:])
    result = []
    while f"{year:04d}{month:02d}" <= end:
        result.append(f"{year:04d}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def parse_page(content):
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, DefusedXmlException):
        raise DataSourceError("실거래 응답이 정상 XML이 아닙니다.") from None
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in {"00", "000", "0"}:
        raise DataSourceError("실거래 API 오류: 인증·활용신청·호출 한도 또는 응답 명세를 확인하세요.")
    try:
        total = int(root.findtext(".//totalCount"))
        if total < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise DataSourceError("실거래 응답에 유효한 totalCount가 없습니다.") from None
    return total, [{child.tag: (child.text or "").strip() for child in item}
                   for item in root.findall(".//items/item")]


def normalize(item, region, month, region_name):
    def required(name):
        value = item.get(name, "").strip()
        if not value:
            raise ValueError(name)
        return value
    try:
        deal_date = date(int(required("dealYear")), int(required("dealMonth")), int(required("dealDay")))
        area = float(required("excluUseAr"))
        price = int(required("dealAmount").replace(",", "").replace(" ", ""))
        if not 0 < area < 10000 or price <= 0 or deal_date.strftime("%Y%m") != month:
            raise ValueError
        if item.get("sggCd") and item["sggCd"] != region:
            raise ValueError
        dong, jibun = required("umdNm"), item.get("jibun", "").strip()
        # No lot number means no precise address: keep it empty and off the map.
        address = f"{region_name.strip()} {dong} {jibun}" if jibun else ""
        return dict(region_code=region, deal_month=month, apartment=required("aptNm"),
                    address=address, dong=dong, deal_date=deal_date.isoformat(), area_m2=area,
                    price_man=price, floor=int(item["floor"]) if item.get("floor") else None,
                    build_year=int(item["buildYear"]) if item.get("buildYear") else None,
                    cancelled=int(item.get("cdealType", "").upper() in {"O", "Y", "1"}
                                  or bool(item.get("cdealDay", "").strip())),
                    latitude=None, longitude=None, source="molit", raw_json=raw_json(item),
                    collected_at=now_iso())
    except (ValueError, TypeError, KeyError, OverflowError):
        raise DataSourceError("실거래 필수 필드·금액·면적·날짜 검증 실패. 기존 DB는 유지됩니다.") from None


def collect(path, key, region, month, region_name, client=None, endpoint=None, dongs=None):
    validate_scope(region, month)
    if not key.strip() or not region_name.strip():
        raise ValueError("API 키와 시도·시군구 전체 이름을 설정하세요.")
    run = start_run(path, "molit", f"{region}/{month}")
    owned = client is None
    client = client or session()
    try:
        endpoint = endpoint or api_endpoint()
        rows, expected, page = [], None, 1
        while True:
            params = {"LAWD_CD": region, "DEAL_YMD": month, "pageNo": page, "numOfRows": 1000}
            response = get(client, endpoint, params={"serviceKey": unquote(key.strip()), **params})
            content = response.content
            # Preserve full responses but never persist an echoed credential.
            for secret in {key.strip(), unquote(key.strip())}:
                content = content.replace(secret.encode(), b"[REDACTED]")
            with connect(path) as conn:
                conn.execute("INSERT INTO api_pages(run_id,page_no,endpoint,request_json,response_xml,received_at) "
                             "VALUES(?,?,?,?,?,?)", (run, page, endpoint, raw_json(params),
                                                      encode_response_xml(content), now_iso()))
            total, items = parse_page(content)
            if expected is not None and total != expected:
                raise DataSourceError("수집 도중 총 건수가 변경되었습니다. 월 전체를 다시 수집하세요.")
            expected = total
            rows.extend(normalize(item, region, month, region_name) for item in items)
            if len(rows) == total:
                break
            if not items or len(rows) > total or page >= 1000:
                raise DataSourceError("페이지가 누락되었거나 총 건수가 맞지 않습니다. 기존 DB는 유지됩니다.")
            page += 1
            time.sleep(0.15)
        if dongs:
            rows = [row for row in rows if row["dong"] in dongs]
        replace_trade_partition(path, region, month, rows)
        finish_run(path, run, len(rows))
        return len(rows)
    except Exception as exc:
        finish_run(path, run, error=str(exc) if isinstance(exc, ValueError) else "수집 처리 실패")
        raise
    finally:
        if owned:
            client.close()

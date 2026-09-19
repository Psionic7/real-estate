import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from estate.analytics import active_listings, comparable_gap, export_csv, load_data, within_radius
from estate.db import backup, connect, initialize, replace_trade_partition
from estate.http import DataSourceError, get
from estate.listings import import_rows, parse_payload, validate_rows
from estate.molit import collect, months_between, normalize, parse_page


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize(path)
    return path


def trade_item(**changes):
    item = dict(aptNm="테스트단지", umdNm="역삼동", jibun="123-4", sggCd="11680",
                dealYear="2026", dealMonth="1", dealDay="5", excluUseAr="84.9",
                dealAmount="150,000", floor="12", buildYear="2015", cdealType="", cdealDay="")
    return dict(item, **changes)


def xml_page(items, total=None):
    total = len(items) if total is None else total
    values = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in item.items()) + "</item>" for item in items)
    return f"<response><header><resultCode>000</resultCode></header><body><totalCount>{total}</totalCount><items>{values}</items></body></response>".encode()


def client_for(*pages):
    client = Mock()
    client.get.side_effect = [SimpleNamespace(content=p, raise_for_status=lambda: None) for p in pages]
    return client


def sample_listing(**changes):
    r = dict(source="partner", listing_id="A1", observed_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
             region_code="11680", apartment="테스트단지", address="서울특별시 강남구 역삼동 123-4",
             dong="역삼동", area_m2=84.9, price_man=160000, floor=12, status="active",
             latitude=37.5, longitude=127.03, source_url="")
    return dict(r, **changes)


def test_paging_and_repeated_import_keep_distinct_identical_trades(database):
    page1, page2 = xml_page([trade_item()], 2), xml_page([trade_item()], 2)
    for _ in range(2):
        client = client_for(page1, page2)
        assert collect(database, "a%2Bb%3D", "11680", "202601", "서울특별시 강남구", client) == 2
        assert client.get.call_args_list[0].kwargs["params"]["serviceKey"] == "a+b="
        assert client.get.call_args_list[1].kwargs["params"]["pageNo"] == 2
    with connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 2


def test_correction_cancellation_and_empty_month(database):
    collect(database, "key", "11680", "202601", "서울특별시 강남구", client_for(xml_page([trade_item()])))
    collect(database, "key", "11680", "202601", "서울특별시 강남구",
            client_for(xml_page([trade_item(dealAmount="140,000", cdealType="O", cdealDay="26.02.01")])) )
    trades, _ = load_data(database)
    assert len(trades) == 1 and trades.iloc[0]["price_man"] == 140000 and trades.iloc[0]["cancelled"] == 1
    collect(database, "key", "11680", "202601", "서울특별시 강남구", client_for(xml_page([])))
    assert load_data(database)[0].empty


@pytest.mark.parametrize("bad_page", [xml_page([], 2), xml_page([trade_item()], 3),
                                      xml_page([trade_item(dealAmount="oops")], 2)])
def test_incomplete_page_or_bad_row_preserves_database(database, bad_page):
    collect(database, "key", "11680", "202601", "서울특별시 강남구", client_for(xml_page([trade_item()])))
    with pytest.raises(DataSourceError):
        collect(database, "key", "11680", "202601", "서울특별시 강남구",
                client_for(xml_page([trade_item()], 2), bad_page))
    trades, _ = load_data(database)
    assert len(trades) == 1
    with connect(database) as conn:
        assert conn.execute("SELECT status FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "failed"


def test_api_error_and_unsafe_xml():
    for value in [b"<response><header><resultCode>30</resultCode></header></response>",
                  b"not xml", b'<!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>']:
        with pytest.raises(DataSourceError):
            parse_page(value)


def test_network_error_never_exposes_service_key():
    client = Mock()
    client.get.side_effect = requests.ConnectionError("https://example.com?serviceKey=SECRET")
    with pytest.raises(DataSourceError) as error:
        get(client, "https://example.com")
    assert "SECRET" not in str(error.value)


def test_months_and_missing_address():
    assert months_between("202511", "202602") == ["202511", "202512", "202601", "202602"]
    with pytest.raises(ValueError):
        months_between("202601", "202513")
    assert normalize(trade_item(jibun=""), "11680", "202601", "서울특별시 강남구")["address"] == ""


def test_latest_withdrawal_not_resurrected_by_old_import(database):
    older = sample_listing(observed_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    newer = sample_listing(status="withdrawn")
    import_rows(database, [newer])
    import_rows(database, [older])
    assert import_rows(database, [older]) == 0
    _, listings = load_data(database)
    assert len(listings) == 1 and listings.iloc[0]["status"] == "withdrawn"
    assert active_listings(listings).empty


def test_stale_future_and_other_sources(database):
    now = datetime.now(timezone.utc)
    import_rows(database, [sample_listing(), sample_listing(source="other"),
                          sample_listing(listing_id="OLD", observed_at=(now - timedelta(days=20)).isoformat()),
                          sample_listing(listing_id="FUTURE", observed_at=(now + timedelta(minutes=2)).isoformat())])
    _, listings = load_data(database)
    assert len(listings) == 4
    assert len(active_listings(listings, now=now)) == 2


@pytest.mark.parametrize("changes", [dict(price_man=-1), dict(price_man="NaN"), dict(price_man="1.5"),
                                    dict(area_m2=float("nan")), dict(observed_at="2026-01-01T12:00:00"),
                                    dict(latitude=127.0, longitude=37.0), dict(status="unknown"),
                                    dict(region_code="1168"), dict(source_url="javascript:alert(1)")])
def test_invalid_listings(changes):
    with pytest.raises(ValueError):
        validate_rows([sample_listing(**changes)])


def test_atomic_conflict_rollback(database):
    original = sample_listing()
    import_rows(database, [original])
    conflict = dict(original, price_man=170000)
    with pytest.raises(ValueError):
        import_rows(database, [sample_listing(listing_id="NEW"), conflict])
    with connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM listing_snapshots").fetchone()[0] == 1


def test_json_roundtrip_duplicate_and_invalid_json():
    rows = parse_payload(json.dumps([sample_listing()]).encode("utf-8"), ".json")
    assert rows[0]["price_man"] == 160000
    with pytest.raises(ValueError):
        parse_payload(b"{}", ".json")
    with pytest.raises(ValueError):
        validate_rows([rows[0], rows[0]])


def test_geocode_cache_and_radius(database):
    row = normalize(trade_item(), "11680", "202601", "서울특별시 강남구")
    replace_trade_partition(database, "11680", "202601", [row])
    with connect(database) as conn:
        conn.execute("INSERT INTO geocodes VALUES(?,?,?,?,?)", (row["address"], 37.5, 127.03, "test", "2026-01-01"))
    trades, _ = load_data(database)
    assert len(within_radius(trades, 37.5, 127.03, 1)) == 1
    assert within_radius(trades, 35.1, 129.1, 1).empty


def test_gap_requires_comparable_three_sales():
    trades = pd.DataFrame([dict(address="a", apartment="apt", area_m2=84.9, price_eok=p) for p in [9, 10, 11]])
    listings = pd.DataFrame([dict(address="a", apartment="apt", area_m2=84.9, price_eok=12)])
    assert comparable_gap(trades, listings).iloc[0]["호가차이(%)"] == pytest.approx(20)
    assert comparable_gap(trades.iloc[:2], listings).empty
    assert comparable_gap(trades, listings.assign(area_m2=59)).empty


def test_online_backup_integrity(database, tmp_path):
    import_rows(database, [sample_listing()])
    target = tmp_path / "backup.sqlite3"
    backup(database, target)
    with connect(target) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM listing_snapshots").fetchone()[0] == 1
    with pytest.raises(ValueError):
        backup(database, target)


def test_csv_formula_sanitization():
    result = export_csv(pd.DataFrame({"name": ["=CMD()", "normal", "  +1"]})).decode("utf-8-sig")
    assert "'=CMD()" in result and "'  +1" in result

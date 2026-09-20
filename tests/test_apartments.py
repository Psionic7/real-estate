import pandas as pd
import pytest

from estate.analytics import apartment_stats, apartment_sample, map_price_points
from estate.maps import housing_deck


def sample(**changes):
    return dict(dict(id=1, region_code="41465", dong="풍덕천동", address="수지구 풍덕천동 1",
                     apartment="같은이름", deal_date="2026-08-01", deal_month="202608",
                     price_eok=10.0, period_start="2026-06", period_end="2026-08",
                     period_kind="최근 3개월",
                     price_per_pyeong=4000.0, area_m2=84.0, lat=None, lon=None, cancelled=0), **changes)


def test_summary_keeps_unlocated_trades_and_latest_day_median():
    trades = pd.DataFrame([sample(), sample(id=2, price_eok=12, lat=37.32, lon=127.09),
                           sample(id=3, deal_date="2026-07-01", price_eok=8),
                           sample(id=4, cancelled=1, price_eok=99)])
    stats = apartment_stats(trades)
    row = stats.iloc[0]
    assert row["count"] == 3
    assert row["median_price"] == 10
    assert row["latest_price"] == 11
    assert row["latest_count"] == 2
    assert row["total_price"] == 30
    assert row["lat"] == pytest.approx(37.32)
    points = map_price_points(trades, {"41465": (37.32, 127.09, 12)})
    assert points[0]["count"] == 3
    assert points[0]["average_price"] == 10
    assert "10.00억" in points[0]["label"]
    assert "계산 기간 2026-06~2026-08" in points[0]["summary"]
    deck = housing_deck(points, "41465")
    assert deck.layers[-1].id == "apartment-labels"
    assert len(housing_deck(points, "41465", False).layers) == 2


def test_equal_names_different_addresses_and_regions_are_not_merged():
    trades = pd.DataFrame([sample(), sample(id=2, address="수지구 풍덕천동 2"),
                           sample(id=3, region_code="41135")])
    summary = apartment_stats(trades)
    assert len(summary) == 3
    assert len(apartment_sample(trades, summary.iloc[0])) == 1
    points = map_price_points(trades, {"41465": (37.32, 127.09, 12), "41135": (37.38, 127.12, 12)})
    assert len(points) == 2
    assert all(point["kind"] == "지역 요약" for point in points)


def test_cancelled_only_and_empty_samples_have_no_apartment_stats():
    trades = pd.DataFrame([sample(cancelled=1)])
    assert apartment_stats(trades).empty
    assert apartment_stats(trades.iloc[:0]).empty


def test_recent_and_fallback_periods_stay_separate_on_map():
    trades = pd.DataFrame([
        sample(id=1, apartment="최근단지", address="주소1", price_eok=10, lat=37.3, lon=127.1),
        sample(id=2, apartment="최근단지", address="주소1", price_eok=12, lat=37.3, lon=127.1),
        sample(id=3, apartment="과거단지", address="주소2", deal_month="202001",
               deal_date="2020-01-02", price_eok=6, lat=37.31, lon=127.11,
               period_start="2020-01", period_end="2020-01", period_kind="최근 거래월"),
    ])
    points = map_price_points(trades, {"41465": (37.32, 127.09, 12)})
    by_name = {point["apartment"]: point for point in points}
    assert by_name["최근단지"]["average_price"] == 11
    assert by_name["최근단지"]["period"] == "2026-06~2026-08"
    assert by_name["과거단지"]["average_price"] == 6
    assert by_name["과거단지"]["period_kind"] == "최근 거래월"

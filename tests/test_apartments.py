import pandas as pd
import pytest

from estate.analytics import apartment_stats, apartment_sample, map_points
from estate.maps import housing_deck


def sample(**changes):
    return dict(dict(id=1, region_code="41465", dong="풍덕천동", address="수지구 풍덕천동 1",
                     apartment="같은이름", deal_date="2026-08-01", price_eok=10.0,
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
    points = map_points(trades, pd.DataFrame(columns=trades.columns))
    assert points[0]["count"] == 3
    assert points[0]["median_price"] == "10.00"
    assert "10.00억 · 3건" in points[0]["label"]
    assert "최근일 중위 11.00억원" in points[0]["summary"]
    deck = housing_deck(points, "41465")
    assert deck.layers[-1].id == "apartment-labels"
    assert len(housing_deck(points, "41465", False).layers) == 2


def test_equal_names_different_addresses_and_regions_are_not_merged():
    trades = pd.DataFrame([sample(), sample(id=2, address="수지구 풍덕천동 2"),
                           sample(id=3, region_code="41135")])
    summary = apartment_stats(trades)
    assert len(summary) == 3
    assert len(apartment_sample(trades, summary.iloc[0])) == 1
    assert map_points(trades, pd.DataFrame(columns=trades.columns)) == []


def test_cancelled_only_and_empty_samples_have_no_apartment_stats():
    trades = pd.DataFrame([sample(cancelled=1)])
    assert apartment_stats(trades).empty
    assert apartment_stats(trades.iloc[:0]).empty

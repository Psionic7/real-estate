import json
from datetime import date, timedelta
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from estate.analytics import (active_listings, apartment_stats, apartment_sample, comparable_gap, export_csv, filter_common,
                              latest_deal_date, load_data, load_map_trades, map_price_points, monthly_stats,
                              within_radius)
from estate.area import area_label, to_display_area, to_square_metres
from estate.config import db_path
from estate.complexes import ensure_apartment_complexes, load_apartment_complexes
from estate.db import connect, initialize
from estate.dashboard import render_dashboard, render_watchlist
from estate.favorites import apartment_id, apartment_identity, filter_favorites, parse_favorites
from estate.geocode import load_seed_geocodes
from estate.maps import DEFAULT_REGION, REGION_VIEWS, housing_deck
from estate.scheduler import targets

st.set_page_config(page_title="집의 흐름 | 아파트 데이터 지도", page_icon="🏙️", layout="wide")

LABELS = {"41465": "용인시 수지구", "11680": "서울 강남구", "11710": "서울 송파구", "11440": "서울 마포구",
          "41135": "성남 분당구", "26350": "부산 해운대구"}
DISPLAY = {"apartment": "단지", "address": "주소", "dong": "법정동", "deal_date": "계약일",
           "area_m2": "전용면적(㎡)", "price_eok": "가격(억원)", "floor": "층",
           "price_per_pyeong": "평당가격(만원)", "source": "출처", "observed_at": "확인시각(UTC)",
           "listing_id": "매물ID", "status": "상태", "region_code": "지역코드"}


def show_table(frame, listing=False, key="export", area_unit="㎡"):
    columns = (["source", "listing_id", "observed_at"] if listing else ["deal_date"]) + [
        "apartment", "address", "area_m2", "floor", "price_eok", "price_per_pyeong"]
    view = frame[columns].copy()
    view["area_m2"] = to_display_area(pd.to_numeric(view["area_m2"], errors="coerce"), area_unit).round(
        1 if area_unit == "평" else 2)
    view = view.rename(columns={**DISPLAY, "area_m2": area_label(area_unit)})
    st.dataframe(view, hide_index=True, width="stretch", column_config={
        "가격(억원)": st.column_config.NumberColumn(format="%.2f"),
        "평당가격(만원)": st.column_config.NumberColumn(format="%.0f"),
        area_label(area_unit): st.column_config.NumberColumn(format="%.1f" if area_unit == "평" else "%.2f"),
    })
    st.download_button("조회 결과 CSV 저장", export_csv(view), file_name=f"{key}.csv",
                       mime="text/csv", key=key)


APP_CSS = """
<style>
[data-testid="stAppViewContainer"] {background:#eef2f6;}
[data-testid="stSidebar"] {min-width:390px; width:390px; background:#fff;
  border-right:1px solid #dfe5ec; box-shadow:8px 0 30px rgba(21,38,61,.08);}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {padding-top:0;}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:.65rem;}
.block-container {max-width:none; padding: 2.15rem 1rem 2rem;}
.side-brand {margin:-1rem -1rem .35rem; padding:22px 20px 18px; color:#fff;
  background:linear-gradient(135deg,#102a43 0%,#0c6872 62%,#15909a 100%);
  box-shadow:0 12px 28px rgba(12,70,84,.2);}
.side-brand-kicker {font-size:.69rem; font-weight:800; letter-spacing:.17em; opacity:.72;}
.side-brand-title {margin:6px 0 2px; font-size:1.55rem; font-weight:880; letter-spacing:-.04em;}
.side-brand-copy {font-size:.81rem; opacity:.78;}
.region-panel {margin:2px 0 4px; padding:18px; border:1px solid #e1e6ed; border-radius:18px;
  background:#fff; box-shadow:0 8px 24px rgba(25,44,70,.06);}
.region-panel-label {color:#7a8798; font-size:.72rem; font-weight:750; letter-spacing:.08em;}
.region-panel-title {margin:4px 0 14px; color:#12263f; font-size:1.22rem; font-weight:860;}
.region-metrics {display:grid; grid-template-columns:1fr 1fr; gap:10px;}
.region-metric {padding:12px; border-radius:13px; background:#f4f7fa;}
.region-metric span {display:block; color:#7a8798; font-size:.69rem; font-weight:700;}
.region-metric strong {display:block; margin-top:4px; color:#0c6872; font-size:1.13rem;}
.region-rank {display:flex; align-items:center; gap:10px; padding:9px 2px;
  border-bottom:1px solid #edf0f4;}
.region-rank:last-child {border-bottom:0;}
.region-rank-no {display:flex; width:25px; height:25px; align-items:center; justify-content:center;
  border-radius:8px; color:#fff; background:#0f7b83; font-size:.72rem; font-weight:850;}
.region-rank-name {min-width:0; flex:1; color:#172b4d; font-size:.83rem; font-weight:760;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.region-rank-meta {color:#718096; font-size:.72rem; white-space:nowrap;}
.map-hero {display:flex; align-items:center; justify-content:space-between; gap:16px; padding:10px 4px 12px;}
.map-hero-kicker {color:#0f7b83; font-size:.7rem; font-weight:850; letter-spacing:.14em;}
.map-hero-title {margin:3px 0 2px; color:#10233e; font-size:1.72rem; font-weight:880; letter-spacing:-.045em;}
.map-hero-copy {color:#69788b; font-size:.86rem;}
.map-hero-badge {padding:9px 13px; border:1px solid #d8e1e8; border-radius:999px;
  color:#365066; background:#fff; font-size:.76rem; font-weight:750; white-space:nowrap;}
.map-summary {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:4px 0 10px;}
.map-summary-item {display:flex; align-items:baseline; justify-content:space-between; gap:10px;
  padding:10px 13px; border:1px solid #dbe2e9; border-radius:12px; background:rgba(255,255,255,.78);}
.map-summary-item span {color:#65758a; font-size:.76rem; font-weight:700;}
.map-summary-item strong {color:#10233e; font-size:1.05rem; font-weight:850; white-space:nowrap;}
.map-legend {display:flex; flex-wrap:wrap; gap:16px; align-items:center; color:#637083;
  font-size:.78rem; margin:2px 0 8px;}
.legend-dot {display:inline-block; width:14px; height:11px; margin-right:6px; border-radius:3px;
  background:#087f8c; vertical-align:-1px;}
.legend-ring {display:inline-block; width:14px; height:11px; margin-right:6px; background:#ab5d1c;
  border-radius:3px; vertical-align:-1px;}
.legend-history {display:inline-block; width:14px; height:11px; margin-right:6px; background:#62758c;
  border-radius:3px; vertical-align:-1px;}
.legend-apartment {display:inline-block; width:14px; height:11px; margin-right:6px; background:#fff;
  border:1px solid #9ba8b7; border-radius:3px; vertical-align:-1px;}
.selection-empty {min-height:150px; display:flex; flex-direction:column; justify-content:center;
  align-items:center; text-align:center; padding:30px; border:1px dashed #cbd5e1; border-radius:22px;
  color:#718096; background:rgba(255,255,255,.55);}
.selection-empty strong {color:#10233e; font-size:1.1rem; margin:10px 0 5px;}
div[data-testid="stDeckGlJsonChart"] {border:1px solid #dbe2e9; border-radius:18px;
  overflow:hidden; box-shadow:0 12px 32px rgba(24,43,68,.11);}
@media (max-width: 900px) {
  [data-testid="stSidebar"] {min-width:330px; width:330px;}
  .map-hero-title{font-size:1.4rem}.map-hero-badge{display:none}
  .map-summary {grid-template-columns:1fr;}
}
</style>
"""


def load_favorite_ids():
    if "favorite_ids" not in st.session_state:
        st.session_state["favorite_ids"] = parse_favorites(st.query_params.get("favorites", "[]"))
    return list(st.session_state["favorite_ids"])


def save_favorite_ids(values):
    values = list(dict.fromkeys(values))[:20]
    st.session_state["favorite_ids"] = values
    if values:
        st.query_params["favorites"] = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    elif "favorites" in st.query_params:
        del st.query_params["favorites"]


def toggle_favorite(item):
    values = load_favorite_ids()
    value = apartment_id(item)
    if value in values:
        values.remove(value)
    elif len(values) < 20:
        values.append(value)
    save_favorite_ids(values)


def remove_favorite(value):
    save_favorite_ids([item for item in load_favorite_ids() if item != value])


def render_region_overview(trades, region_label):
    """Compact regional pulse for the fixed map-side panel."""
    st.html(f'<section class="region-panel"><div class="region-panel-label">REGION PULSE</div>'
            f'<div class="region-panel-title">{escape(str(region_label))}</div></section>')
    if trades.empty:
        st.caption("선택 지역의 최근 실거래가 없습니다.")
        return
    monthly = monthly_stats(trades).tail(36)
    latest = monthly.iloc[-1]
    st.html(
        '<div class="region-metrics">'
        f'<div class="region-metric"><span>{escape(str(latest["계약월"]))} 평당 중위가</span>'
        f'<strong>{latest["평당중위가격(만원)"]:,.0f}만원</strong></div>'
        f'<div class="region-metric"><span>{escape(str(latest["계약월"]))} 거래량</span>'
        f'<strong>{int(latest["거래량"]):,}건</strong></div></div>')

    chart = alt.layer(
        alt.Chart(monthly).mark_area(color="#d8eef0", opacity=.85).encode(
            x=alt.X("계약월:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=54, tickCount=4)),
            y=alt.Y("거래량:Q", title=None, axis=None),
            tooltip=["계약월:N", "거래량:Q"],
        ),
        alt.Chart(monthly).mark_line(color="#0d747d", strokeWidth=3,
                                     point={"filled": True, "size": 35}).encode(
            x=alt.X("계약월:N", title=None),
            y=alt.Y("평당중위가격(만원):Q", title=None, axis=alt.Axis(format="~s"),
                    scale=alt.Scale(zero=False)),
            tooltip=["계약월:N", alt.Tooltip("평당중위가격(만원):Q", format=",.0f"), "거래량:Q"],
        ),
    ).resolve_scale(y="independent").properties(height=155)
    st.altair_chart(chart)

    last_day = pd.to_datetime(trades["deal_date"]).max()
    cutoff = (last_day.date() - timedelta(days=92)).isoformat()
    recent = trades[trades["deal_date"] >= cutoff]
    ranked = apartment_stats(recent).head(5)
    st.markdown("**최근 3개월 아파트 거래 순위**")
    if ranked.empty:
        st.caption("순위를 계산할 거래가 없습니다.")
        return
    rows = []
    for rank, row in enumerate(ranked.itertuples(), start=1):
        rows.append(
            f'<div class="region-rank"><span class="region-rank-no">{rank}</span>'
            f'<span class="region-rank-name">{escape(str(row.apartment))}</span>'
            f'<span class="region-rank-meta">{escape(str(row.dong))} · {row.count:,}건</span></div>')
    st.html('<div class="region-panel">' + "".join(rows) + "</div>")


def render_selected_apartment(item, map_trades, live_listings, area_unit="㎡"):
    identity = apartment_identity(apartment_id(item))
    sample = apartment_sample(map_trades, identity)
    listing_sample = apartment_sample(live_listings, identity) if not live_listings.empty else live_listings.copy()
    saved = apartment_id(item) in load_favorite_ids()
    st.markdown(f"### {item['apartment']}")
    st.caption(item.get("address") or item.get("dong"))
    if st.button("관심 해제" if saved else "관심 단지 저장", icon=":material/star:",
                 type="primary" if not saved else "secondary", width="stretch", key="toggle_map_favorite"):
        toggle_favorite(item)
        st.rerun()
    left, right = st.columns(2)
    average = item.get("average_price")
    left.metric(item.get("period_kind", "최근") + " 평균", f"{average:.2f}억원" if average is not None else "—")
    right.metric("활성 매물", f"{len(listing_sample):,}건",
                 f"중위 {listing_sample['price_eok'].median():.2f}억원" if len(listing_sample) else "확인 자료 없음")
    st.caption(f"실거래 계산 기간 {item.get('period', '—')} · {len(sample):,}건")
    sale_tab, listing_tab = st.tabs(["최근 실거래", "현재 매물"])
    with sale_tab:
        if sample.empty:
            st.caption("표시할 실거래가 없습니다.")
        else:
            recent = sample.sort_values("deal_date", ascending=False).head(7)[
                ["deal_date", "area_m2", "price_eok", "floor"]].copy()
            recent["area_m2"] = to_display_area(recent["area_m2"], area_unit).round(1 if area_unit == "평" else 2)
            recent = recent.rename(columns={
                "deal_date": "계약일", "area_m2": area_label(area_unit, "면적"),
                "price_eok": "가격(억)", "floor": "층"})
            st.dataframe(recent, hide_index=True, height=270, width="stretch",
                         column_config={"가격(억)": st.column_config.NumberColumn(format="%.2f")})
    with listing_tab:
        if listing_sample.empty:
            st.caption("사용 권한이 있는 자료에서 활성 매물이 확인되지 않았습니다.")
        else:
            current = listing_sample.sort_values("observed_at", ascending=False).head(7)[
                ["area_m2", "price_eok", "floor", "source", "source_url"]].copy()
            current["area_m2"] = to_display_area(current["area_m2"], area_unit).round(1 if area_unit == "평" else 2)
            current = current.rename(columns={
                    "area_m2": area_label(area_unit, "면적"), "price_eok": "호가(억)", "floor": "층",
                    "source": "출처", "source_url": "원문"})
            st.dataframe(current, hide_index=True, height=270, width="stretch", column_config={
                "호가(억)": st.column_config.NumberColumn(format="%.2f"),
                "원문": st.column_config.LinkColumn(display_text="보기"),
            })


st.html(APP_CSS)
st.sidebar.html(
    '<section class="side-brand"><div class="side-brand-kicker">KOREA APARTMENT MAP</div>'
    '<div class="side-brand-title">집의 흐름</div>'
    '<div class="side-brand-copy">지도에서 찾고, 관심 단지는 깊게 분석하세요.</div></section>')
path = db_path()
initialize(path)
load_seed_geocodes(path)

LABELS.update({r["region_code"]: r["display_name"] for r in targets(path)})
with connect(path) as conn:
    stored_regions = {r[0] for r in conn.execute(
        "SELECT region_code FROM trades UNION SELECT region_code FROM listing_snapshots")}
regions = sorted(stored_regions | {DEFAULT_REGION})
region = st.sidebar.selectbox("지도 지역", ["전체"] + regions,
                              index=regions.index(DEFAULT_REGION) + 1,
                              format_func=lambda r: LABELS.get(r, r), key="region")
query = st.sidebar.text_input("아파트·주소 검색", placeholder="단지명 또는 법정동 검색", key="search",
                              icon=":material/search:")
region_overview = st.sidebar.container()
area_unit = st.sidebar.segmented_control(
    "전용면적 표시", ["㎡", "평"], default="평", required=True, key="area_unit",
    help="전용면적 기준 1평 = 3.305785㎡입니다. 공급면적 기준 평형과 다릅니다.",
)
latest = latest_deal_date(path, region)
last_date = date.fromisoformat(latest) if latest else date.today()
with st.sidebar.expander("지도 상세 필터", expanded=False, icon=":material/tune:"):
    period = st.date_input("실거래 계약 기간", (last_date - timedelta(days=365), last_date), key=f"period_{region}")
    slider_key = "area_filter_pyeong" if area_unit == "평" else "area_filter_m2"
    previous_unit = st.session_state.get("_area_filter_unit")
    if previous_unit is not None and previous_unit != area_unit:
        low, high = st.session_state.get("_area_filter_m2", (66.116, 132.231))
        if area_unit == "평":
            st.session_state[slider_key] = tuple(
                min(91.0, round(to_display_area(value, "평") * 2) / 2) for value in (low, high))
        else:
            st.session_state[slider_key] = tuple(min(300, round(value)) for value in (low, high))
    st.session_state["_area_filter_unit"] = area_unit
    if area_unit == "평":
        display_area = st.slider("전용면적 (평)", 0.0, 91.0, (20.0, 40.0),
                                 step=0.5, key=slider_key)
    else:
        display_area = st.slider("전용면적 (㎡)", 0, 300, (66, 132), key=slider_key)
    area = tuple(round(to_square_metres(value, area_unit), 3) for value in display_area)
    st.session_state["_area_filter_m2"] = area
    price = st.slider("실거래가·호가 (억원)", 0.0, 300.0, (10.0, 30.0),
                      step=0.5, key="price_filter")
    freshness = st.selectbox(
        "매물 확인 유효기간", [None, 1, 3, 7, 14, 30, 60, 90, 180],
        format_func=lambda value: "제한 없음" if value is None else f"최근 {value}일",
        key="listing_freshness",
        help="제한 없음은 수집 시점과 관계없이 현재 상태가 활성인 매물을 모두 표시합니다.",
    )
if st.sidebar.button("데이터 새로고침", icon=":material/refresh:", width="stretch"):
    st.rerun()

start_date, end_date = (period[0].isoformat(), period[1].isoformat()) if len(period) == 2 else (None, None)
ensure_apartment_complexes(path, region)
complexes = load_apartment_complexes(path, region)
if query and not complexes.empty:
    complex_mask = (complexes["apartment"].str.contains(query, regex=False, na=False)
                    | complexes["address"].str.contains(query, regex=False, na=False))
    complexes = complexes[complex_mask].copy()
trades, listings = load_data(path, region, start_date, end_date)
trades = trades[trades["cancelled"] == 0].copy()
live = active_listings(listings, freshness)
filtered_trades = filter_common(trades, region, area, price, query)
filtered_listings = filter_common(live, region, area, price, query)
map_trades = filter_common(load_map_trades(path, region), region, area, price, query)

trend_start = (last_date - timedelta(days=1095)).isoformat()
region_trades, _ = load_data(path, region, trend_start, last_date.isoformat())
region_trades = region_trades[region_trades["cancelled"] == 0].copy()
with region_overview:
    render_region_overview(region_trades, LABELS.get(region, region))

if len(period) != 2:
    st.warning("실거래 기간의 시작일과 종료일을 모두 선택하세요.")
    filtered_trades = filtered_trades.iloc[0:0]

if st.sidebar.checkbox("선택 단지 주변만 보기", key="radius_enabled"):
    anchors = pd.concat([filtered_trades, filtered_listings], ignore_index=True).dropna(subset=["lat", "lon"])
    anchors = anchors.drop_duplicates(["address", "apartment"])
    if anchors.empty:
        st.sidebar.info("반경 중심으로 사용할 좌표가 없습니다.")
    else:
        options = anchors.to_dict("records")
        idx = st.sidebar.selectbox("중심 아파트", range(len(options)),
                                   format_func=lambda i, values=options: f"{values[i]['apartment']} · {values[i]['address']}")
        radius = st.sidebar.slider("반경 (km)", 0.2, 10.0, 2.0, step=0.2)
        center = options[idx]
        filtered_trades = within_radius(filtered_trades, center["lat"], center["lon"], radius)
        filtered_listings = within_radius(filtered_listings, center["lat"], center["lon"], radius)
        map_trades = within_radius(map_trades, center["lat"], center["lon"], radius)
        complexes = within_radius(complexes, center["lat"], center["lon"], radius)

favorite_ids = load_favorite_ids()
st.sidebar.metric("관심 단지", f"{len(favorite_ids)}개")
st.sidebar.caption("관심 단지는 현재 브라우저 주소에 저장됩니다. 최대 20개까지 비교할 수 있습니다.")

st.html(f"""
<header class="map-hero">
  <div><div class="map-hero-kicker">LIVE APARTMENT EXPLORER</div>
  <div class="map-hero-title">{escape(str(LABELS.get(region, region)))} 아파트 지도</div>
  <div class="map-hero-copy">실거래가와 현재 매물을 지도에서 비교하고 관심 단지로 저장하세요.</div></div>
  <div class="map-hero-badge">최근 데이터 {escape(str(last_date))}</div>
</header>
""")

map_tab, watch_tab, market_tab = st.tabs(
    ["지도 탐색", f"관심 단지 {len(favorite_ids)}", "지역 흐름"])

with map_tab:
    points = map_price_points(map_trades, REGION_VIEWS, filtered_listings)
    st.html(
        '<div class="map-summary">'
        f'<div class="map-summary-item"><span>저장 아파트</span><strong>{len(complexes):,}개</strong></div>'
        f'<div class="map-summary-item"><span>최근 실거래</span><strong>{len(map_trades):,}건</strong></div>'
        f'<div class="map-summary-item"><span>활성 매물</span><strong>{len(filtered_listings):,}건</strong></div>'
        '</div>'
    )
    if not points and (len(map_trades) or len(filtered_listings)):
        st.info("현재 조건에 맞는 아파트 중 좌표가 확인된 단지가 없습니다.")
    elif not points:
        st.info("현재 조건에 맞는 실거래 또는 매물 데이터가 없습니다. 지역과 검색 조건을 조정해 주세요.")
    price_control, background_control, note = st.columns([1, 1, 2], vertical_alignment="center")
    show_labels = price_control.checkbox("단지명·가격 카드", value=True, key="map_labels")
    show_complexes = background_control.checkbox("아파트 배경", value=True, key="complex_background")
    note.caption("저장된 단지는 옅은 이름표로, 조건에 맞는 단지는 가격 카드로 표시합니다.")
    st.html('<div class="map-legend"><span><i class="legend-dot"></i>청록 · 최근 실거래</span>'
            '<span><i class="legend-history"></i>회청 · 최근 거래월</span>'
            '<span><i class="legend-ring"></i>주황 · 매물 호가</span>'
            '<span><i class="legend-apartment"></i>흰색 · 저장 아파트</span></div>')
    complex_points = complexes.to_dict("records")
    event = st.pydeck_chart(housing_deck(points, region, show_labels, area_unit,
                                         complex_points, show_complexes), height=760,
                            on_select="rerun", selection_mode="single-object",
                            key=f"housing_map_{region}_{query}")
    selected = [item for group in event.selection.get("objects", {}).values() for item in group]
    if selected:
        st.session_state["map_selected_apartment"] = selected[0]
    current = st.session_state.get("map_selected_apartment")
    valid_ids = {apartment_id(point) for point in [*points, *complex_points]}
    if current and apartment_id(current) not in valid_ids:
        current = None
        st.session_state.pop("map_selected_apartment", None)
    if current:
        with st.container(border=True):
            render_selected_apartment(current, map_trades, filtered_listings, area_unit)
    else:
        st.html('<div class="selection-empty"><span style="font-size:2rem">⌖</span>'
                '<strong>지도에서 아파트를 선택하세요</strong>'
                '<span>실거래 요약과 현재 매물을 확인하고 관심 단지로 저장할 수 있습니다.</span></div>')
    located_keys = {apartment_id(point) for point in points}
    available_frames = [frame for frame in (map_trades, filtered_listings) if not frame.empty]
    all_groups = (pd.concat(available_frames, ignore_index=True).drop_duplicates(
        ["region_code", "dong", "address", "apartment"])
        if available_frames else map_trades.iloc[0:0])
    missing = sum(apartment_id(row) not in located_keys for row in all_groups.to_dict("records"))
    if missing:
        st.caption(f"좌표 미확정 아파트 {missing:,}개는 지도에서 제외되었습니다.")
    st.caption("실거래가 없던 단지는 최근 거래월 평균을 표시합니다. 좌표 출처: © OpenStreetMap contributors (ODbL), Esri ArcGIS World Geocoding Service, 도로명주소 조회 자료.")

with watch_tab:
    if favorite_ids:
        global_latest = latest_deal_date(path)
        watch_end = date.fromisoformat(global_latest) if global_latest else date.today()
        watch_start = watch_end - timedelta(days=365)
        watch_trades, watch_listings = load_data(path, None, watch_start.isoformat(), watch_end.isoformat())
        watch_trades = filter_favorites(watch_trades[watch_trades["cancelled"] == 0], favorite_ids)
        watch_listings = filter_favorites(active_listings(watch_listings, freshness), favorite_ids)
    else:
        watch_trades, watch_listings = trades.iloc[0:0].copy(), listings.iloc[0:0].copy()
    render_watchlist(watch_trades, watch_listings, favorite_ids, remove_favorite, area_unit)

with market_tab:
    apartments = apartment_stats(filtered_trades)
    render_dashboard(apartments, filtered_trades, LABELS.get(region, region),
                     include_detail=False, area_unit=area_unit)
    st.subheader("실거래와 호가 비교", icon=":material/compare_arrows:")
    gap = comparable_gap(filtered_trades, filtered_listings)
    if gap.empty:
        st.info("같은 단지·유사 면적의 실거래 3건 이상과 활성 매물이 있어야 비교할 수 있습니다.")
    else:
        if area_unit == "평":
            gap = gap.rename(columns={"전용면적(㎡)": "전용면적(평)"})
            gap["전용면적(평)"] = to_display_area(gap["전용면적(평)"], area_unit)
        st.dataframe(gap.round(2), hide_index=True, width="stretch")
    with st.expander("전체 실거래와 매물 내역"):
        left, right = st.columns(2)
        with left:
            st.markdown("**실거래 내역**")
            show_table(filtered_trades.sort_values("deal_date", ascending=False),
                       key="trades", area_unit=area_unit)
        with right:
            st.markdown("**현재 매물**")
            if filtered_listings.empty:
                st.caption("연결된 매물 자료가 없습니다.")
            show_table(filtered_listings.sort_values("observed_at", ascending=False),
                       True, "listings", area_unit)

st.divider()
st.caption(f"집의 흐름 · 지도 기반 아파트 실거래·매물 탐색 | 금액: 억원 · 면적: 전용{area_unit}")

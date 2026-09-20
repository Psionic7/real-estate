import os
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from estate.analytics import (active_listings, apartment_stats, apartment_sample, comparable_gap, export_csv, filter_common,
                              latest_deal_date, load_data, load_map_trades, map_price_points,
                              within_radius)
from estate.config import ROOT, db_path, service_key
from estate.collection_ui import render_collection, render_archive
from estate.db import connect, initialize
from estate.dashboard import render_dashboard, render_watchlist
from estate.favorites import apartment_id, apartment_identity, filter_favorites, parse_favorites
from estate.geocode import geocode_pending, load_seed_geocodes
from estate.listings import import_rows, parse_payload
from estate.maps import DEFAULT_REGION, REGION_VIEWS, housing_deck
from estate.scheduler import ensure_defaults, targets
from estate.worker import start_background

st.set_page_config(page_title="집의 흐름 | 아파트 데이터 지도", page_icon="🏙️", layout="wide")

LABELS = {"41465": "용인시 수지구", "11680": "서울 강남구", "11710": "서울 송파구", "11440": "서울 마포구",
          "41135": "성남 분당구", "26350": "부산 해운대구"}
DISPLAY = {"apartment": "단지", "address": "주소", "dong": "법정동", "deal_date": "계약일",
           "area_m2": "전용면적(㎡)", "price_eok": "가격(억원)", "floor": "층",
           "price_per_pyeong": "평당가격(만원)", "source": "출처", "observed_at": "확인시각(UTC)",
           "listing_id": "매물ID", "status": "상태", "region_code": "지역코드"}


def show_table(frame, listing=False, key="export"):
    columns = (["source", "listing_id", "observed_at"] if listing else ["deal_date"]) + [
        "apartment", "address", "area_m2", "floor", "price_eok", "price_per_pyeong"]
    view = frame[columns].rename(columns=DISPLAY)
    st.dataframe(view, hide_index=True, width="stretch", column_config={
        "가격(억원)": st.column_config.NumberColumn(format="%.2f"),
        "평당가격(만원)": st.column_config.NumberColumn(format="%.0f"),
        "전용면적(㎡)": st.column_config.NumberColumn(format="%.2f"),
    })
    st.download_button("조회 결과 CSV 저장", export_csv(view), file_name=f"{key}.csv",
                       mime="text/csv", key=key)


def data_management(path, selected_region):
    st.subheader("데이터 수집 및 품질")
    st.caption("인증키·엔드포인트는 Streamlit Secrets, 환경변수 또는 로컬 TXT/.env에서 설정합니다.")
    with connect(path) as conn:
        coverage = pd.read_sql_query("""SELECT region_code AS 지역코드,deal_month AS 계약월,
            COUNT(*) AS 전체건수,SUM(cancelled) AS 해제건수,MAX(collected_at) AS 수집시각
            FROM trades GROUP BY region_code,deal_month ORDER BY deal_month DESC,region_code""", conn)
        runs = pd.read_sql_query("SELECT source,scope,started_at,finished_at,status,row_count,message "
                                 "FROM collection_runs ORDER BY id DESC LIMIT 30", conn)
    a, b, c = st.columns(3)
    a.metric("실거래 API 키", "설정됨" if service_key() else "미설정")
    b.metric("주소 좌표 API 키", "설정됨" if os.getenv("KAKAO_REST_API_KEY") else "미설정")
    c.metric("수집된 지역·월", f"{len(coverage):,}")
    render_collection(path)
    with st.expander("API 전체 필드·수집 원문"):
        render_archive(path)
    with st.expander("② 현재 매물 CSV·JSON 가져오기"):
        st.caption("사용 권한이 있는 아파트 매매 자료를 표준 열에 맞춰 가져오세요. 누락 매물을 자동 종료하지 않으므로 종료 시 status를 갱신해야 합니다.")
        st.download_button("CSV 양식 다운로드", (ROOT / "examples/listings_template.csv").read_bytes(),
                           file_name="listings_template.csv", mime="text/csv")
        uploaded = st.file_uploader("매물 파일 (UTF-8, 최대 10MB)", type=["csv", "json"])
        if uploaded:
            try:
                rows = parse_payload(uploaded.getvalue(), Path(uploaded.name).suffix)
                st.dataframe(pd.DataFrame(rows).head(20), hide_index=True, width="stretch")
                st.caption(f"검증 통과: {len(rows):,}행 / 미리보기 최대 20행")
                if st.button("검증된 매물 저장"):
                    count = import_rows(path, rows)
                    st.success(f"신규 스냅샷 {count:,}건 저장. 새로고침하면 화면에 반영됩니다.")
            except ValueError as exc:
                st.error(str(exc))
    with st.expander("③ 주소를 지도 좌표로 변환"):
        st.caption("국토부 실거래 API에는 위도·경도가 없습니다. KAKAO_REST_API_KEY를 Secrets 또는 .env에 설정한 뒤 좌표를 수집하세요. 정확한 주소가 하나로 검색된 결과만 지도에 표시합니다.")
        st.caption(f"좌표 수집 범위: {LABELS.get(selected_region, selected_region)} · 왼쪽 지역 선택을 따릅니다.")
        limit = st.number_input("이번 실행 최대 주소 수", 1, 1000, 100, key="geo_limit")
        if st.button("미등록 주소 좌표 수집", disabled=not os.getenv("KAKAO_REST_API_KEY")):
            try:
                with st.spinner("주소 좌표를 수집하고 있습니다."):
                    matched, missing = geocode_pending(path, os.getenv("KAKAO_REST_API_KEY", ""), limit,
                                                       region=None if selected_region == "전체" else selected_region)
                st.session_state["geocode_result"] = f"좌표 저장 {matched}건 / 미확정 {missing}건"
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if "geocode_result" in st.session_state:
            st.success(st.session_state.pop("geocode_result"))
    st.markdown("**실거래 수집 범위**")
    st.dataframe(coverage, hide_index=True, width="stretch")
    st.markdown("**최근 수집 기록**")
    st.dataframe(runs, hide_index=True, width="stretch")
    st.caption("running 상태가 계속되면 중단된 작업일 수 있습니다. 해당 지역·월을 다시 수집하세요.")


APP_CSS = """
<style>
.block-container {max-width: 1540px; padding-top: 1.35rem; padding-bottom: 2rem;}
.app-hero {display:flex; justify-content:space-between; align-items:flex-end; gap:24px;
  padding: 14px 4px 20px;}
.app-kicker {color:#087f8c; font-size:.76rem; font-weight:800; letter-spacing:.14em;}
.app-title {margin:5px 0 3px; color:#10233e; font-size:2.35rem; font-weight:880; letter-spacing:-.055em;}
.app-copy {color:#66758a; font-size:.97rem;}
.map-legend {display:flex; flex-wrap:wrap; gap:16px; align-items:center; color:#637083;
  font-size:.82rem; margin:2px 0 10px;}
.legend-dot {display:inline-block; width:11px; height:11px; margin-right:6px; border-radius:50%;
  background:#087f8c; vertical-align:-1px;}
.legend-ring {display:inline-block; width:14px; height:14px; margin-right:6px; border:3px solid #e29137;
  border-radius:50%; vertical-align:-3px;}
.selection-empty {min-height:150px; display:flex; flex-direction:column; justify-content:center;
  align-items:center; text-align:center; padding:30px; border:1px dashed #cbd5e1; border-radius:22px;
  color:#718096; background:rgba(255,255,255,.55);}
.selection-empty strong {color:#10233e; font-size:1.1rem; margin:10px 0 5px;}
@media (max-width: 760px) {.app-title{font-size:1.85rem}.app-hero{align-items:flex-start;flex-direction:column}}
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


def render_selected_apartment(item, map_trades, live_listings):
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
                ["deal_date", "area_m2", "price_eok", "floor"]].rename(columns={
                    "deal_date": "계약일", "area_m2": "면적(㎡)", "price_eok": "가격(억)", "floor": "층"})
            st.dataframe(recent, hide_index=True, height=270, width="stretch",
                         column_config={"가격(억)": st.column_config.NumberColumn(format="%.2f")})
    with listing_tab:
        if listing_sample.empty:
            st.caption("사용 권한이 있는 자료에서 활성 매물이 확인되지 않았습니다.")
        else:
            current = listing_sample.sort_values("observed_at", ascending=False).head(7)[
                ["area_m2", "price_eok", "floor", "source", "source_url"]].rename(columns={
                    "area_m2": "면적(㎡)", "price_eok": "호가(억)", "floor": "층",
                    "source": "출처", "source_url": "원문"})
            st.dataframe(current, hide_index=True, height=270, width="stretch", column_config={
                "호가(억)": st.column_config.NumberColumn(format="%.2f"),
                "원문": st.column_config.LinkColumn(display_text="보기"),
            })


st.html(APP_CSS)
st.sidebar.title("집의 흐름")
st.sidebar.caption("MAP-BASED APARTMENT INSIGHT")
path = db_path()
initialize(path)
load_seed_geocodes(path)
ensure_defaults(path)


@st.cache_resource
def collection_worker(database):
    return start_background(database)


collection_worker(str(path))
if st.sidebar.button("새로고침", icon=":material/refresh:", width="stretch"):
    st.rerun()

saved_targets = targets(path)
LABELS.update({r["region_code"]: r["display_name"] for r in saved_targets})
LABELS[DEFAULT_REGION] = "용인시 수지구"
with connect(path) as conn:
    stored_regions = {r[0] for r in conn.execute(
        "SELECT region_code FROM trades UNION SELECT region_code FROM listing_snapshots")}
regions = sorted(stored_regions | {r["region_code"] for r in saved_targets} | {DEFAULT_REGION})
region = st.sidebar.selectbox("지도 지역", ["전체"] + regions,
                              index=regions.index(DEFAULT_REGION) + 1,
                              format_func=lambda r: LABELS.get(r, r), key="region")
query = st.sidebar.text_input("아파트·주소 검색", placeholder="예: 현대성우, 풍덕천동", key="search")
latest = latest_deal_date(path, region)
last_date = date.fromisoformat(latest) if latest else date.today()
with st.sidebar.expander("상세 필터", expanded=True):
    period = st.date_input("실거래 계약 기간", (last_date - timedelta(days=180), last_date), key=f"period_{region}")
    area = st.slider("전용면적 (㎡)", 0, 300, (0, 200))
    price = st.slider("실거래가·호가 (억원)", 0.0, 300.0, (0.0, 100.0), step=0.5)
    freshness = st.slider("매물 확인 유효기간 (일)", 1, 60, 7)

start_date, end_date = (period[0].isoformat(), period[1].isoformat()) if len(period) == 2 else (None, None)
trades, listings = load_data(path, region, start_date, end_date)
trades = trades[trades["cancelled"] == 0].copy()
live = active_listings(listings, freshness)
filtered_trades = filter_common(trades, region, area, price, query)
filtered_listings = filter_common(live, region, area, price, query)
map_trades = filter_common(load_map_trades(path, region), region, area, price, query)

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

favorite_ids = load_favorite_ids()
st.sidebar.metric("관심 단지", f"{len(favorite_ids)}개")
st.sidebar.caption("관심 단지는 현재 브라우저 주소에 저장됩니다. 최대 20개까지 비교할 수 있습니다.")

st.html(f"""
<header class="app-hero">
  <div><div class="app-kicker">KOREA APARTMENT MAP</div>
  <div class="app-title">지도에서 찾고, 관심 단지만 깊게</div>
  <div class="app-copy">{LABELS.get(region, region)}의 실거래가와 현재 매물을 한곳에서 비교하세요.</div></div>
</header>
""")

map_tab, watch_tab, market_tab, manage_tab = st.tabs(
    ["지도 탐색", f"관심 단지 {len(favorite_ids)}", "지역 흐름", "데이터 관리"])

with map_tab:
    points = map_price_points(map_trades, REGION_VIEWS, filtered_listings)
    top_a, top_b, top_c = st.columns(3, border=True)
    top_a.metric("지도 아파트", f"{len(points):,}개")
    top_b.metric("최근 실거래", f"{len(map_trades):,}건")
    top_c.metric("활성 매물", f"{len(filtered_listings):,}건")
    if not points and (len(map_trades) or len(filtered_listings)):
        st.info("현재 조건에 맞는 아파트 중 좌표가 확인된 단지가 없습니다. 데이터 관리에서 주소 좌표를 보완해 주세요.")
    elif not points:
        st.info("현재 조건에 맞는 실거래 또는 매물 데이터가 없습니다. 지역과 검색 조건을 조정해 주세요.")
    control, note = st.columns([1, 3], vertical_alignment="center")
    show_labels = control.checkbox("가격 라벨", value=True, key="map_labels")
    note.caption("원 안 숫자는 최근 3개 계약월 평균(억원)입니다. 주황색 테두리는 현재 매물이 있는 단지입니다.")
    st.html('<div class="map-legend"><span><i class="legend-dot"></i>실거래가 있는 아파트</span>'
            '<span><i class="legend-ring"></i>활성 매물이 있는 아파트</span></div>')
    event = st.pydeck_chart(housing_deck(points, region, show_labels), height=590,
                            on_select="rerun", selection_mode="single-object",
                            key=f"housing_map_{region}_{query}")
    selected = [item for group in event.selection.get("objects", {}).values() for item in group]
    if selected:
        st.session_state["map_selected_apartment"] = selected[0]
    current = st.session_state.get("map_selected_apartment")
    valid_ids = {apartment_id(point) for point in points}
    if current and apartment_id(current) not in valid_ids:
        current = None
        st.session_state.pop("map_selected_apartment", None)
    if current:
        with st.container(border=True):
            render_selected_apartment(current, map_trades, filtered_listings)
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
        st.caption(f"좌표 미확정 아파트 {missing:,}개는 지도에서 제외되었습니다. 데이터 관리에서 주소 좌표를 보완할 수 있습니다.")
    st.caption("실거래가 없던 단지는 최근 거래월 평균을 표시합니다. 지도 좌표 일부: © OpenStreetMap contributors (ODbL).")

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
    render_watchlist(watch_trades, watch_listings, favorite_ids, remove_favorite)

with market_tab:
    apartments = apartment_stats(filtered_trades)
    render_dashboard(apartments, filtered_trades, LABELS.get(region, region), include_detail=False)
    st.subheader("실거래와 호가 비교", icon=":material/compare_arrows:")
    gap = comparable_gap(filtered_trades, filtered_listings)
    if gap.empty:
        st.info("같은 단지·유사 면적의 실거래 3건 이상과 활성 매물이 있어야 비교할 수 있습니다.")
    else:
        st.dataframe(gap.round(2), hide_index=True, width="stretch")
    with st.expander("전체 실거래와 매물 내역"):
        left, right = st.columns(2)
        with left:
            st.markdown("**실거래 내역**")
            show_table(filtered_trades.sort_values("deal_date", ascending=False), key="trades")
        with right:
            st.markdown("**현재 매물**")
            if filtered_listings.empty:
                st.caption("연결된 매물 자료가 없습니다.")
            show_table(filtered_listings.sort_values("observed_at", ascending=False), True, "listings")

with manage_tab:
    data_management(path, region)

st.divider()
st.caption("집의 흐름 · 지도 기반 아파트 실거래·매물 탐색 | 금액: 억원 · 면적: 전용㎡")

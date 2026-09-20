import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from estate.analytics import (active_listings, apartment_stats, apartment_sample, comparable_gap, export_csv, filter_common,
                              latest_deal_date, load_data, load_map_trades, map_price_points,
                              monthly_stats, within_radius)
from estate.config import ROOT, db_path, service_key
from estate.collection_ui import render_collection, render_archive
from estate.db import connect, initialize
from estate.dashboard import render_dashboard, render_apartment_detail
from estate.geocode import geocode_pending
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


def data_management(path):
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
        st.caption(f"좌표 수집 범위: {LABELS.get(region, region)} · 왼쪽 지역 선택을 따릅니다.")
        limit = st.number_input("이번 실행 최대 주소 수", 1, 1000, 100, key="geo_limit")
        if st.button("미등록 주소 좌표 수집", disabled=not os.getenv("KAKAO_REST_API_KEY")):
            try:
                with st.spinner("주소 좌표를 수집하고 있습니다."):
                    matched, missing = geocode_pending(path, os.getenv("KAKAO_REST_API_KEY", ""), limit,
                                                       region=None if region == "전체" else region)
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


st.sidebar.title("집의 흐름")
st.sidebar.caption("KOREA HOUSING OBSERVATORY")
path = db_path()
initialize(path)
ensure_defaults(path)


@st.cache_resource
def collection_worker(database):
    return start_background(database)


collection_worker(str(path))
if st.sidebar.button("새로고침"):
    st.rerun()

saved_targets = targets(path)
LABELS.update({r["region_code"]: r["display_name"] for r in saved_targets})
LABELS[DEFAULT_REGION] = "용인시 수지구"
with connect(path) as conn:
    stored_regions = {r[0] for r in conn.execute(
        "SELECT region_code FROM trades UNION SELECT region_code FROM listing_snapshots")}
regions = sorted(stored_regions | {r["region_code"] for r in saved_targets} | {DEFAULT_REGION})
region = st.sidebar.selectbox("지역", ["전체"] + regions,
                              index=regions.index(DEFAULT_REGION) + 1,
                              format_func=lambda r: LABELS.get(r, r), key="region")
query = st.sidebar.text_input("단지·주소 검색", placeholder="예: 풍덕천동, 상현동", key="search")
latest = latest_deal_date(path, region)
last_date = date.fromisoformat(latest) if latest else date.today()
period = st.sidebar.date_input("실거래 계약 기간", (last_date - timedelta(days=180), last_date), key=f"period_{region}")
area = st.sidebar.slider("전용면적 (㎡)", 0, 300, (0, 200))
price = st.sidebar.slider("거래가·호가 (억원)", 0.0, 300.0, (0.0, 100.0), step=0.5)
freshness = st.sidebar.slider("매물 확인 유효기간 (일)", 1, 60, 7)
st.sidebar.caption("최근 확인된 active 매물만 집계합니다. 실거래 계약 기간과 매물 확인 기간은 별개입니다.")

start_date, end_date = (period[0].isoformat(), period[1].isoformat()) if len(period) == 2 else (None, None)
trades, listings = load_data(path, region, start_date, end_date)

st.title("집의 흐름")
st.markdown(f"**{LABELS.get(region, region)}** · 아파트별 실거래를 대시보드와 지도에서 한눈에.")

trades = trades[trades["cancelled"] == 0].copy()
live = active_listings(listings, freshness)
filtered_trades = filter_common(trades, region, area, price, query)
filtered_listings = filter_common(live, region, area, price, query)
if len(period) != 2:
    st.warning("실거래 기간의 시작일과 종료일을 모두 선택하세요.")
    filtered_trades = filtered_trades.iloc[0:0]

if st.sidebar.checkbox("반경으로 범위 좁히기", key="radius_enabled"):
    anchors = pd.concat([filtered_trades, filtered_listings], ignore_index=True).dropna(subset=["lat", "lon"])
    anchors = anchors.drop_duplicates(["address", "apartment"])
    if anchors.empty:
        st.sidebar.info("반경 중심으로 사용할 좌표가 없습니다.")
    else:
        options = anchors.to_dict("records")
        idx = st.sidebar.selectbox("반경 중심 단지", range(len(options)),
                                   format_func=lambda i, values=options: f"{values[i]['apartment']} · {values[i]['address']}")
        radius = st.sidebar.slider("반경 (km)", 0.2, 10.0, 2.0, step=0.2)
        center = options[idx]
        filtered_trades = within_radius(filtered_trades, center["lat"], center["lon"], radius)
        filtered_listings = within_radius(filtered_listings, center["lat"], center["lon"], radius)
        st.caption(f"반경 범위: {center['apartment']}에서 {radius:.1f}km · 좌표가 없는 데이터는 제외")

apartments = apartment_stats(filtered_trades)
a, b, c, d = st.columns(4, border=True, vertical_alignment="center")
a.metric("실거래 건수", f"{len(filtered_trades):,}건")
b.metric("실거래 중위가격", f"{filtered_trades['price_eok'].median():.2f}억원" if len(filtered_trades) else "—")
c.metric("거래된 아파트", f"{len(apartments):,}개")
total_price = filtered_trades['price_eok'].sum()
d.metric("실거래 총액", f"{total_price / 10000:.2f}조원" if total_price >= 10000 else f"{total_price:,.0f}억원",
         help=f"{total_price:,.1f}억원")
st.caption("국토부 실거래 자료 · 해제 거래 제외 · 선택한 기간·면적·가격 범위 기준")

dashboard_tab, map_tab, stats_tab, table_tab, manage_tab = st.tabs(
    ["아파트 대시보드", "지도 탐색", "지역 통계", "거래·매물 내역", "데이터 관리"])
with dashboard_tab:
    render_dashboard(apartments, filtered_trades, LABELS.get(region, region))
with map_tab:
    st.subheader("지도 위 최근 실거래 평균")
    st.caption("청록: 좌표가 확인된 아파트 · 파랑: 좌표가 없을 때의 선택 지역 전체 요약. 원을 선택하면 계산 표본을 확인할 수 있습니다.")
    map_trades = filter_common(load_map_trades(path, region), region, area, price, query)
    points = map_price_points(map_trades, REGION_VIEWS)
    show_labels = st.checkbox("지도에 아파트명·평균가격 표시", value=True, key="map_labels")
    st.caption("가격 라벨은 최근 3개 계약월의 산술평균입니다. 거래가 없으면 단지의 최근 거래월 평균과 계산 기간을 표시합니다.")
    map_apartments = map_trades.groupby(["region_code", "dong", "address", "apartment"], dropna=False)
    missing = sum(group[["lat", "lon"]].isna().all(axis=1).all() for _, group in map_apartments)
    st.caption(f"지도 오버레이 {len(points):,}개 / 좌표 미확정 아파트 {missing:,}개")
    if missing and not any(point["kind"] == "아파트" for point in points):
        st.info("단지 좌표가 아직 없습니다. 선택 지역 중심에 지역 평균을 표시하며, 주소 좌표가 저장되면 아파트별 오버레이로 바뀝니다.")
    if len(points) > 5000:
        st.warning("지도는 최대 5,000개 그룹을 표시합니다. 지역·검색·반경 필터로 범위를 좁히세요.")
    event = st.pydeck_chart(housing_deck(points, region, show_labels), height=510,
                           on_select="rerun", selection_mode="single-object",
                           key=f"housing_map_{region}_{query}")
    selected = [item for group in event.selection.get("objects", {}).values() for item in group]
    if selected:
        item = selected[0]
        st.markdown(f"**{item['apartment']} · 평균 {item['average_price']:.2f}억원**")
        st.caption(f"{item['period_kind']} · 계산 기간 {item['period']} · 실거래 {item['count']:,}건")
        if item["kind"] == "아파트":
            subset = apartment_sample(map_trades, item)
            st.markdown("**평균 계산에 포함된 실거래**")
            show_table(subset.sort_values("deal_date", ascending=False), key="map_sample")
        else:
            st.info("현재 단지 좌표가 없어 선택 지역 중심에 전체 평균을 표시합니다. 주소 좌표를 수집하면 아파트별 오버레이로 자동 전환됩니다.")
    elif points:
        st.info("지도 원을 선택하면 단지의 실거래와 현재 매물을 함께 살펴볼 수 있습니다.")
    else:
        st.info("현재 조건에 맞는 거래·매물이 없습니다. 지역·기간·검색 조건을 조정하거나 데이터 관리에서 수집하세요.")
    if not points and region not in {"41465", "41135", "41117", "11680", "11710", "11440", "26350", "전체"}:
        st.caption("이 지역은 아직 지도 중심 좌표가 없어 전국 지도로 표시합니다.")
    st.caption("지도 평균은 왼쪽 면적·가격·검색 조건을 따르며 계약 기간 필터와는 별개로 최근 3개 계약월을 계산합니다. 지도 이동·확대는 통계 범위를 바꾸지 않습니다.")

with stats_tab:
    st.subheader("가격과 거래량의 흐름")
    stats = monthly_stats(filtered_trades)
    if stats.empty:
        st.info("조건에 맞는 실거래가 없습니다.")
    else:
        x, y = st.columns(2)
        with x:
            st.markdown("**월별 중위 거래가격 (억원)**")
            st.line_chart(stats.set_index("계약월")[["중위가격(억원)"]], color="#087F8C")
        with y:
            st.markdown("**월별 거래량 (건)**")
            st.bar_chart(stats.set_index("계약월")[["거래량"]], color="#087F8C")
        st.caption("거래가 없는 월은 그래프에서 생략됩니다. 거래 구성 변화가 반영되므로 가격지수·동일주택 수익률을 의미하지 않습니다.")
        st.dataframe(stats, hide_index=True, width="stretch")
        grouped = filtered_trades.groupby(["region_code", "dong"]).agg(
            거래수=("id", "size"), 중위가격_억원=("price_eok", "median"),
            평당중위가격_만원=("price_per_pyeong", "median")).reset_index().rename(columns=DISPLAY)
        st.markdown("**법정동별 통계**")
        st.dataframe(grouped, hide_index=True, width="stretch")
    st.subheader("유사 면적 실거래와 호가 비교")
    st.caption("선택 기간 내 같은 주소·단지, 매물 면적 ±5%, 해제 제외 거래 3건 이상. 층·향·상태는 보정하지 않습니다.")
    gap = comparable_gap(filtered_trades, filtered_listings)
    if gap.empty:
        st.info("비교 조건을 만족하는 표본이 없습니다.")
    else:
        st.dataframe(gap.round(2), hide_index=True, width="stretch")

with table_tab:
    left, right = st.columns(2)
    with left:
        st.subheader("실거래 내역")
        show_table(filtered_trades.sort_values("deal_date", ascending=False), key="trades")
    with right:
        st.subheader("현재 매물 관측")
        if listings.empty:
            st.info("현재 매물 제공 자료가 아직 연결되지 않았습니다. 데이터 관리에서 사용 권한이 있는 CSV·JSON을 가져오세요.")
        show_table(filtered_listings.sort_values("observed_at", ascending=False), True, "listings")
    st.subheader("매물 가격·상태 변경 이력")
    if not filtered_listings.empty:
        options = filtered_listings[["source", "listing_id", "apartment"]].to_dict("records")
        selected_id = st.selectbox("이력을 볼 매물", range(len(options)),
                                   format_func=lambda i, values=options: f"{values[i]['apartment']} · {values[i]['source']}/{values[i]['listing_id']}")
        listing = options[selected_id]
        with connect(path) as conn:
            history = pd.read_sql_query("SELECT observed_at,price_man,status FROM listing_snapshots "
                                        "WHERE source=? AND listing_id=? ORDER BY observed_at DESC", conn,
                                        params=(listing["source"], listing["listing_id"]))
        history["가격(억원)"] = history.pop("price_man") / 10000
        st.dataframe(history.rename(columns=DISPLAY), hide_index=True, width="stretch")
    else:
        st.caption("조회된 현재 매물이 있으면 가격 변경 이력을 확인할 수 있습니다.")

with manage_tab:
    data_management(path)

st.divider()
st.caption("집의 흐름 · 아파트 매매 MVP | 금액 저장: 만원 · 표시: 억원 | 면적: 전용㎡ · 1평=3.305785㎡")

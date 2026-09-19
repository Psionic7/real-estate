import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from estate.analytics import (active_listings, comparable_gap, export_csv, filter_common,
                              load_data, map_points, monthly_stats, within_radius)
from estate.config import ROOT, db_path, service_key, api_endpoint
from estate.collection_ui import render_collection, render_archive
from estate.db import connect, initialize
from estate.demo import seed
from estate.geocode import geocode_pending
from estate.listings import import_rows, parse_payload
from estate.molit import collect, months_between
from estate.scheduler import ensure_defaults, targets
from estate.worker import start_background

st.set_page_config(page_title="집의 흐름 | 아파트 데이터 지도", page_icon="🏙️", layout="wide")

LABELS = {"11680": "서울 강남구", "11710": "서울 송파구", "11440": "서울 마포구",
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


def data_management(path, demo):
    st.subheader("데이터 수집 및 품질")
    st.caption("인증키·엔드포인트는 프로젝트의 TXT 파일 또는 .env에서 읽습니다. 키 내용은 표시하지 않습니다.")
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
    if demo:
        st.info("현재는 데모 모드입니다. 실제 데이터를 저장하려면 왼쪽에서 ‘실제 데이터’를 선택하세요.")
    if not demo:
        render_collection(path)
        with st.expander("API 전체 필드·수집 원문"):
            render_archive(path)
    with st.expander("② 현재 매물 CSV·JSON 가져오기"):
        st.caption("사용 권한이 있는 아파트 매매 자료를 표준 열에 맞춰 가져오세요. 누락 매물을 자동 종료하지 않으므로 종료 시 status를 갱신해야 합니다.")
        st.download_button("CSV 양식 다운로드", (ROOT / "examples/listings_template.csv").read_bytes(),
                           file_name="listings_template.csv", mime="text/csv")
        uploaded = st.file_uploader("매물 파일 (UTF-8, 최대 10MB)", type=["csv", "json"], disabled=demo)
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
        st.caption("정확한 주소가 하나로 검색된 결과만 사용합니다. 누락·중복 검색 결과는 지도에서 제외합니다.")
        limit = st.number_input("이번 실행 최대 주소 수", 1, 1000, 100, key="geo_limit")
        if st.button("미등록 주소 좌표 수집", disabled=demo):
            try:
                with st.spinner("주소 좌표를 수집하고 있습니다."):
                    matched, missing = geocode_pending(path, os.getenv("KAKAO_REST_API_KEY", ""), limit)
                st.success(f"좌표 저장 {matched}건 / 미확정 {missing}건. 새로고침으로 지도를 갱신하세요.")
            except ValueError as exc:
                st.error(str(exc))
    st.markdown("**실거래 수집 범위**")
    st.dataframe(coverage, hide_index=True, width="stretch")
    st.markdown("**최근 수집 기록**")
    st.dataframe(runs, hide_index=True, width="stretch")
    st.caption("running 상태가 계속되면 중단된 작업일 수 있습니다. 해당 지역·월을 다시 수집하세요.")


st.sidebar.title("집의 흐름")
st.sidebar.caption("KOREA HOUSING OBSERVATORY")
live_path = db_path(False)
initialize(live_path)
ensure_defaults(live_path)


@st.cache_resource
def collection_worker(database):
    return start_background(database)


collection_worker(str(live_path))
mode = st.sidebar.radio("데이터 모드", ["데모 데이터", "실제 데이터"], key="mode",
                        index=1 if service_key() and os.getenv("ESTATE_DEFAULT_MODE") != "demo" else 0)
demo = mode == "데모 데이터"
path = db_path(demo)
if demo:
    seed(path)
else:
    initialize(path)
if st.sidebar.button("새로고침"):
    st.rerun()

trades, listings = load_data(path)
if not demo:
    LABELS.update({r["region_code"]: r["display_name"] for r in targets(path)})
regions = sorted(set(trades["region_code"]) | set(listings["region_code"]))
region = st.sidebar.selectbox("지역", ["전체"] + regions,
                              format_func=lambda r: LABELS.get(r, r), key=f"region_{demo}")
query = st.sidebar.text_input("단지·주소 검색", placeholder="예: 역삼, 잠실", key="search")
last_date = date.fromisoformat(trades["deal_date"].max()) if not trades.empty else date.today()
period = st.sidebar.date_input("실거래 계약 기간", (last_date - timedelta(days=180), last_date), key=f"period_{demo}")
area = st.sidebar.slider("전용면적 (㎡)", 0, 300, (0, 200))
price = st.sidebar.slider("거래가·호가 (억원)", 0.0, 300.0, (0.0, 100.0), step=0.5)
freshness = st.sidebar.slider("매물 확인 유효기간 (일)", 1, 60, 7)
st.sidebar.caption("최근 확인된 active 매물만 집계합니다. 실거래 계약 기간과 매물 확인 기간은 별개입니다.")

st.title("집의 흐름")
st.markdown("지역의 거래와 지금의 호가를, 지도 위에서 한눈에.")
if demo:
    with connect(path) as conn:
        demo_date = conn.execute("SELECT value FROM metadata WHERE key='demo_seeded'").fetchone()[0]
    st.warning(f"데모 · 모든 단지명·가격·위치는 합성 예시이며 실제 시세가 아닙니다. 생성 기준일 {demo_date}")
else:
    st.info("실제 데이터 · 수집된 지역·기간과 제공처 범위 안에서만 집계됩니다.")

trades = trades[trades["cancelled"] == 0].copy()
live = active_listings(listings, freshness)
filtered_trades = filter_common(trades, region, area, price, query)
filtered_listings = filter_common(live, region, area, price, query)
if len(period) == 2:
    filtered_trades = filtered_trades[filtered_trades["deal_date"].between(period[0].isoformat(), period[1].isoformat())]
else:
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

a, b, c, d = st.columns(4)
a.metric("실거래 건수", f"{len(filtered_trades):,}건")
b.metric("실거래 중위가격", f"{filtered_trades['price_eok'].median():.2f}억원" if len(filtered_trades) else "—")
c.metric("현재 매물 관측 수", f"{len(filtered_listings):,}건")
d.metric("매물 중위호가", f"{filtered_listings['price_eok'].median():.2f}억원" if len(filtered_listings) else "—")
st.caption("해제 거래 제외 · 매물 수는 제공처별 매물ID 기준이며 동일 주택의 중복 광고가 포함될 수 있습니다.")

map_tab, stats_tab, table_tab, manage_tab = st.tabs(["지도 탐색", "지역 통계", "거래·매물 내역", "데이터 관리"])
with map_tab:
    st.subheader("거래가 쌓인 곳, 매물이 나온 곳")
    st.caption("청록: 실거래 / 주황: 매물 호가 · 원의 크기: 관측 수 · 원을 클릭하면 해당 주소·단지의 상세가 표시됩니다.")
    points = map_points(filtered_trades, filtered_listings)
    if points:
        missing = filtered_trades["lat"].isna().sum() + filtered_listings["lat"].isna().sum()
        st.caption(f"지도 표시 {len(points):,}개 그룹 / 좌표 미확정 {missing:,}건 (반경 필터가 없으면 지역 통계에는 포함)")
        shown = points[:5000]
        if len(points) > 5000:
            st.warning("지도는 최대 5,000개 그룹을 표시합니다. 지역·검색·반경 필터로 범위를 좁히세요.")
        deck = pdk.Deck(map_style=None, initial_view_state=pdk.ViewState(
            latitude=float(pd.Series([p["lat"] for p in shown]).median()),
            longitude=float(pd.Series([p["lon"] for p in shown]).median()), zoom=10 if region != "전체" else 6.5),
            layers=[pdk.Layer("ScatterplotLayer", data=[p for p in shown if p["kind"] == kind],
                              id=layer_id, get_position="[lon, lat]", get_fill_color="color",
                              get_radius="radius", radius_min_pixels=min_pixels, radius_max_pixels=max_pixels,
                              stroked=True, get_line_color=[255, 255, 255, 200], line_width_min_pixels=1,
                              pickable=True, auto_highlight=True)
                    for kind, layer_id, min_pixels, max_pixels in [("실거래", "trades", 12, 35),
                                                                  ("매물 호가", "listings", 6, 20)]],
            tooltip={"text": "{apartment}\n{kind} {count}건 · 중위 {median_price}억원\n{address}"})
        event = st.pydeck_chart(deck, height=510, on_select="rerun", selection_mode="single-object",
                               key=f"housing_map_{demo}_{region}_{query}")
        selected = [item for group in event.selection.get("objects", {}).values() for item in group]
        if selected:
            item = selected[0]
            st.markdown(f"**선택 단지: {item['apartment']}**")
            st.caption(item["address"])
            for frame, is_listing in [(filtered_trades, False), (filtered_listings, True)]:
                subset = frame[(frame["address"] == item["address"]) & (frame["apartment"] == item["apartment"])]
                st.write("현재 매물" if is_listing else "실거래 내역")
                show_table(subset, is_listing, f"selected_{is_listing}")
        else:
            st.info("지도 원을 선택하면 단지의 실거래와 현재 매물을 함께 살펴볼 수 있습니다.")
    else:
        st.info("표시할 좌표가 없습니다. 필터를 조정하거나 데이터 관리에서 수집·좌표 변환을 진행하세요.")
    st.caption("지도 이동·확대는 통계 범위를 바꾸지 않습니다. 왼쪽 지역·반경 필터로 범위를 지정하세요. 배경지도는 인터넷 연결이 필요합니다.")

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
    data_management(path, demo)

st.divider()
st.caption("집의 흐름 · 아파트 매매 MVP | 금액 저장: 만원 · 표시: 억원 | 면적: 전용㎡ · 1평=3.305785㎡")

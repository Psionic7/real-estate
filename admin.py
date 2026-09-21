"""Local-only collection and publishing console. Never use as a cloud entrypoint."""
from pathlib import Path

import pandas as pd
import streamlit as st

from estate.admin_access import local_admin_allowed
from estate.baseline import package_database
from estate.collection_ui import render_archive, render_manual_collection, render_target_settings
from estate.config import (db_path, juso_address_search_key, juso_coordinate_search_key,
                           kakao_key, service_key)
from estate.db import connect, initialize
from estate.geocode import geocode_pending, geocode_pending_arcgis, load_seed_geocodes
from estate.juso import collect_address_lookups
from estate.listings import import_rows, parse_payload
from estate.scheduler import ensure_defaults, targets
from estate.worker import start_background

st.set_page_config(page_title="집의 흐름 | 로컬 관리자", page_icon="🛠️", layout="wide")

if not local_admin_allowed(st.get_option("server.address")):
    st.error("관리자 화면은 run-admin.bat으로 이 PC의 127.0.0.1에서만 실행할 수 있습니다.")
    st.stop()

path = db_path()
initialize(path)
load_seed_geocodes(path)
ensure_defaults(path)


@st.cache_resource
def collection_worker(database):
    return start_background(database)


collection_worker(str(path))
st.sidebar.title("집의 흐름 · 관리자")
st.sidebar.caption("이 PC에서만 수집·수정할 수 있습니다.")
page = st.sidebar.radio("관리자 메뉴", ["수집 지역", "실거래 수집", "데이터 품질·매물", "배포 데이터"],
                        label_visibility="collapsed")
st.title(page)

if page == "수집 지역":
    render_target_settings(path)
elif page == "실거래 수집":
    st.caption("등록된 지역의 계약월을 직접 지정하거나 모든 지역의 최근 기간을 요청합니다. 자동 수집은 로컬 처리기가 실행 중일 때만 동작합니다.")
    render_manual_collection(path)
elif page == "데이터 품질·매물":
    with connect(path) as conn:
        coverage = pd.read_sql_query("""SELECT region_code AS 지역코드,deal_month AS 계약월,
            COUNT(*) AS 전체건수,SUM(cancelled) AS 해제건수,MAX(collected_at) AS 수집시각
            FROM trades GROUP BY region_code,deal_month ORDER BY deal_month DESC,region_code""", conn)
        runs = pd.read_sql_query("SELECT source,scope,started_at,finished_at,status,row_count,message "
                                 "FROM collection_runs ORDER BY id DESC LIMIT 30", conn)
        total, located = conn.execute("""WITH addresses AS (
            SELECT DISTINCT address FROM trades WHERE cancelled=0 AND address!=''
            UNION SELECT DISTINCT address FROM listing_snapshots WHERE address!=''
        ) SELECT COUNT(*),COUNT(g.address) FROM addresses a LEFT JOIN geocodes g USING(address)""").fetchone()
        lookup_count, exact_count = conn.execute("SELECT COUNT(*),SUM(status='exact') FROM address_lookups").fetchone()
    a, b, c, d, e = st.columns(5)
    a.metric("실거래 API 키", "설정됨" if service_key() else "미설정")
    b.metric("주소 검색 API 키", "설정됨" if juso_address_search_key() else "미설정")
    c.metric("주소 확인", f"{exact_count or 0:,}개", f"조회 {lookup_count:,}개")
    d.metric("좌표제공 API 키", "설정됨" if juso_coordinate_search_key() else "미설정")
    e.metric("지도 좌표 커버리지", f"{located / total:.1%}" if total else "—", f"미확정 {total-located:,}개")
    st.caption(f"실거래 수집 범위: {len(coverage):,}개 지역·월. 주소 검색 API는 주소 코드만 제공하며 지도 좌표는 제공하지 않습니다.")
    with st.expander("공식 주소 검색·저장"):
        st.caption("실거래·매물에 있는 지번주소를 행정안전부 API에서 조회해 응답 전체를 로컬 DB에 저장합니다. 좌표제공 키 없이 실행할 수 있습니다.")
        search_regions = {"전체": None, **{f"{r['display_name']} · {r['region_code']}": r['region_code']
                                             for r in targets(path)}}
        search_region = st.selectbox("주소 검색 대상 지역", list(search_regions))
        search_limit = st.number_input("이번 실행 최대 주소 검색", 1, 1000, 100)
        refresh_search = st.checkbox("기존 조회 결과도 다시 확인", value=False)
        if st.button("미조회 주소 검색·저장", disabled=not bool(juso_address_search_key())):
            with st.spinner("공식 주소정보를 조회하고 있습니다."):
                try:
                    exact, unresolved = collect_address_lookups(
                        path, juso_address_search_key(), search_limit,
                        search_regions[search_region], refresh_search)
                    st.success(f"정확히 일치한 주소 {exact}건 · 미확정 {unresolved}건")
                except ValueError as exc:
                    st.error(str(exc))
    if total > located:
        st.warning(f"좌표 미확정 주소 {total-located:,}개를 보강하세요.")
    with st.expander("주소 좌표 보강"):
        region_options = {"전체": None, **{f"{r['display_name']} · {r['region_code']}": r['region_code']
                                         for r in targets(path)}}
        region_label = st.selectbox("대상 지역", list(region_options))
        limit = st.number_input("이번 실행 최대 주소", 1, 1000, 100)
        if st.button("좌표 검증·수집"):
            with st.spinner("좌표를 확인하고 있습니다."):
                try:
                    if kakao_key():
                        first, _ = geocode_pending(path, kakao_key(), limit, region_options[region_label])
                    else:
                        first = 0
                    second, unresolved = geocode_pending_arcgis(path, limit, region_options[region_label])
                    st.success(f"좌표 저장 {first + second}건 · 미확정 {unresolved}건")
                except Exception:
                    st.error("좌표 조회에 실패했습니다. 연결 상태와 제공처 응답을 확인하세요.")
    with st.expander("현재 매물 CSV·JSON 가져오기"):
        st.caption("사용 권한이 있는 매물 자료만 가져오세요. 파일은 최대 10MB입니다.")
        from estate.config import ROOT
        st.download_button("CSV 양식 다운로드", (ROOT / "examples/listings_template.csv").read_bytes(),
                           file_name="listings_template.csv", mime="text/csv")
        uploaded = st.file_uploader("매물 파일", type=["csv", "json"])
        if uploaded:
            try:
                rows = parse_payload(uploaded.getvalue(), Path(uploaded.name).suffix)
                st.dataframe(pd.DataFrame(rows).head(20), hide_index=True)
                if st.button("검증된 매물 저장"):
                    count = import_rows(path, rows)
                    st.success(f"신규 매물 스냅샷 {count:,}건 저장")
            except ValueError as exc:
                st.error(str(exc))
    with st.expander("API 전체 필드·수집 원문"):
        render_archive(path)
    st.subheader("실거래 수집 범위")
    st.dataframe(coverage, hide_index=True)
    st.subheader("최근 수집 기록")
    st.dataframe(runs, hide_index=True)
else:
    st.subheader("공개 앱용 데이터 스냅샷")
    st.caption("로컬 DB에서 실거래·매물·좌표만 복사합니다. 수집 작업·API 원문·인증정보는 공개 파일에 넣지 않습니다.")
    with connect(path) as conn:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("trades", "listing_snapshots", "geocodes")}
        active = conn.execute("SELECT COUNT(*) FROM collection_jobs WHERE status='running'").fetchone()[0]
    a, b, c = st.columns(3)
    a.metric("실거래", f"{counts['trades']:,}건")
    b.metric("매물 이력", f"{counts['listing_snapshots']:,}건")
    c.metric("좌표", f"{counts['geocodes']:,}개")
    if active:
        st.warning("수집 작업이 실행 중입니다. 완료 후 스냅샷을 만드세요.")
    if st.button("배포용 스냅샷 생성", type="primary", disabled=bool(active)):
        try:
            with st.spinner("일관된 DB 사본을 압축하고 있습니다."):
                output = package_database(path)
            st.success(f"생성 완료: {output} ({output.stat().st_size / 1024 / 1024:.1f} MB)")
        except (OSError, ValueError) as exc:
            st.error(str(exc))
    st.info("스냅샷 생성 후 data/estate.sqlite3.gz를 GitHub에 커밋·푸시하면 Streamlit Cloud의 조회 데이터가 갱신됩니다.")

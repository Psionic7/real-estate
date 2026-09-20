"""Apartment dashboard and shared drill-down, using the current filter sample."""
import streamlit as st

from estate.analytics import apartment_sample, apartment_stats, export_csv, monthly_stats

SUMMARY_LABELS = {
    "apartment": "아파트", "address": "주소", "dong": "법정동", "count": "거래수",
    "median_price": "중위가격(억원)", "min_price": "최저가(억원)", "max_price": "최고가(억원)",
    "latest_date": "최근 계약일", "latest_price": "최근일 중위가(억원)", "latest_count": "최근일 거래수",
    "median_per_pyeong": "평당중위가(만원)", "min_area": "최소면적(㎡)", "max_area": "최대면적(㎡)",
}


def render_apartment_detail(sample, key):
    if sample.empty:
        st.info("현재 필터에 해당하는 실거래가 없습니다.")
        return
    row = apartment_stats(sample).iloc[0]
    st.subheader(row["apartment"])
    st.caption(row["address"] or f"{row['dong']} · 상세 주소 미제공")
    a, b, c, d = st.columns(4)
    a.metric("단지 거래수", f"{row['count']:,}건")
    b.metric("단지 중위가격", f"{row['median_price']:.2f}억원")
    c.metric("최고 실거래가", f"{row['max_price']:.2f}억원")
    d.metric("최근일 중위가", f"{row['latest_price']:.2f}억원")
    st.caption(f"최근 계약일 {row['latest_date']} · 해당 일 {row['latest_count']}건의 중앙값. "
               "모든 지표는 왼쪽 필터로 선택한 기간·면적·가격 범위를 따릅니다.")
    trend = monthly_stats(sample)
    left, right = st.columns(2)
    with left:
        st.markdown("**월별 중위 실거래가**")
        st.line_chart(trend, x="계약월", y="중위가격(억원)", color="#087F8C", height=230)
    with right:
        st.markdown("**전용면적별 실거래**")
        by_area = sample.groupby("area_m2").agg(
            거래수=("id", "size"), 중위가격=("price_eok", "median"),
            최저가=("price_eok", "min"), 최고가=("price_eok", "max"),
        ).reset_index().rename(columns={"area_m2": "전용면적(㎡)", "중위가격": "중위가격(억원)",
                                       "최저가": "최저가(억원)", "최고가": "최고가(억원)"})
        st.dataframe(by_area.round(2), hide_index=True, height=230, key=f"{key}_area")


def render_dashboard(summary, trades, region_label):
    st.subheader(f"{region_label} 아파트 대시보드")
    if summary.empty:
        st.info("선택 조건에 맞는 실거래가 없습니다. 왼쪽 지역·기간·검색 조건을 조정하세요.")
        return
    left, right = st.columns([2, 1])
    sort = left.selectbox("아파트 정렬", ["거래 많은 순", "중위가격 높은 순", "최근 거래 순"], key="apartment_sort")
    minimum = right.number_input("단지별 최소 거래수", min_value=1, max_value=1000, value=1, key="apartment_min_count")
    sort_key = {"거래 많은 순": "count", "중위가격 높은 순": "median_price", "최근 거래 순": "latest_date"}[sort]
    ranked = summary[summary["count"] >= minimum].sort_values(
        [sort_key, "apartment", "address"], ascending=[False, True, True]).reset_index(drop=True)
    st.caption(f"전체 {len(summary):,}개 단지 중 {len(ranked):,}개 표시 · "
               "서로 다른 면적·층의 거래가 섞인 통계입니다. 면적 필터와 단지별 면적 통계를 함께 확인하세요.")
    if ranked.empty:
        st.info("최소 거래수를 만족하는 단지가 없습니다. 최소 거래수를 낮춰 주세요.")
        return
    cards = ranked.head(6).to_dict("records")
    for offset in range(0, len(cards), 3):
        for column, row in zip(st.columns(3), cards[offset:offset + 3]):
            with column.container(border=True):
                st.markdown(f"**{row['apartment']}**")
                st.caption(row["address"] or row["dong"])
                st.metric("중위 실거래가", f"{row['median_price']:.2f}억원")
                st.write(f"거래 **{row['count']:,}건** · {row['min_price']:.2f}~{row['max_price']:.2f}억")
                st.caption(f"최근 {row['latest_date']} · 당일 중위 {row['latest_price']:.2f}억")

    st.markdown("**선택 정렬 기준 상위 12개 단지 비교**")
    comparison = ranked.head(12).copy()
    # Include rank and address so identically named complexes do not merge in charts.
    comparison["단지"] = [f"{i + 1:02d}. {r.apartment} · {r.dong}" for i, r in comparison.iterrows()]
    comparison = comparison.rename(columns={"count": "거래수", "median_price": "중위가격(억원)"})
    a, b = st.columns(2)
    a.bar_chart(comparison, x="단지", y="거래수", horizontal=True, color="#087F8C", height=350)
    b.bar_chart(comparison, x="단지", y="중위가격(억원)", horizontal=True, color="#D98A32", height=350)

    st.markdown("**아파트별 전체 통계**")
    table = ranked[list(SUMMARY_LABELS)].rename(columns=SUMMARY_LABELS).round(2)
    st.dataframe(table, hide_index=True, key="apartment_summary", height=380)
    st.download_button("아파트 통계 CSV 저장", export_csv(table), file_name="apartment-statistics.csv",
                       mime="text/csv", key="apartment_export")
    st.divider()
    options = list(range(len(ranked)))
    # Filters may shrink or reorder rows: reset the drill-down rather than retain a wrong apartment.
    signature = tuple(tuple(row) for row in ranked[["region_code", "dong", "address", "apartment"]].values)
    if st.session_state.get("apartment_options") != signature:
        st.session_state["apartment_detail"] = 0
        st.session_state["apartment_options"] = signature
    selected = st.selectbox("상세 통계를 볼 아파트", options, key="apartment_detail",
                            format_func=lambda i: f"{ranked.iloc[i]['apartment']} · {ranked.iloc[i]['address'] or ranked.iloc[i]['dong']}")
    render_apartment_detail(apartment_sample(trades, ranked.iloc[selected]), "dashboard")

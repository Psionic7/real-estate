"""Apartment dashboard and shared drill-down, using the current filter sample."""
from html import escape

import altair as alt
import streamlit as st

from estate.analytics import apartment_sample, apartment_stats, export_csv, monthly_stats

SUMMARY_LABELS = {
    "apartment": "아파트", "address": "주소", "dong": "법정동", "count": "거래수",
    "median_price": "중위가격(억원)", "min_price": "최저가(억원)", "max_price": "최고가(억원)",
    "latest_date": "최근 계약일", "latest_price": "최근일 중위가(억원)", "latest_count": "최근일 거래수",
    "median_per_pyeong": "평당중위가(만원)", "min_area": "최소면적(㎡)", "max_area": "최대면적(㎡)",
}


APARTMENT_DASHBOARD_CSS = """
<style>
.apt-hero {
  position: relative; overflow: hidden; min-height: 190px; padding: 34px 38px;
  border-radius: 28px; color: #fff; margin: 4px 0 16px;
  background:
    radial-gradient(circle at 82% 12%, rgba(84, 194, 203, .45), transparent 28%),
    linear-gradient(125deg, #0c2340 0%, #174c67 58%, #268895 100%);
  box-shadow: 0 18px 44px rgba(12, 35, 64, .18);
}
.apt-hero::after {
  content: ""; position: absolute; width: 48%; height: 170%; right: -8%; bottom: -78%;
  transform: rotate(-12deg); opacity: .18;
  background: repeating-linear-gradient(90deg, #fff 0 3px, transparent 3px 27px),
              repeating-linear-gradient(0deg, #fff 0 3px, transparent 3px 22px);
}
.apt-eyebrow {font-size: .78rem; font-weight: 750; letter-spacing: .12em; opacity: .74;}
.apt-title {position: relative; z-index: 1; margin: 12px 0 4px; font-size: 2.15rem;
  line-height: 1.18; font-weight: 850; letter-spacing: -.04em;}
.apt-address {position: relative; z-index: 1; color: rgba(255,255,255,.76); font-size: .94rem;}
.apt-summary {position: relative; z-index: 1; display: inline-flex; flex-wrap: wrap; gap: 8px;
  margin-top: 28px; padding: 11px 18px; border-radius: 999px; color: #10233e;
  background: linear-gradient(90deg, #f5d992, #e7bc60); font-size: .94rem; font-weight: 750;}
.apt-kpi-grid {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px;
  margin: 8px 0 18px;}
.apt-kpi {min-height: 124px; padding: 20px 21px; border: 1px solid #e6e1d8;
  border-radius: 22px; background: #fffdf9; box-shadow: 0 8px 24px rgba(19, 37, 63, .05);}
.apt-kpi-label {color: #718096; font-size: .8rem; font-weight: 720;}
.apt-kpi-value {margin-top: 9px; color: #10233e; font-size: 1.65rem; font-weight: 850;
  letter-spacing: -.035em; white-space: nowrap;}
.apt-kpi-note {margin-top: 9px; color: #8b857b; font-size: .8rem;}
.apt-dot {display: inline-block; width: 9px; height: 9px; margin-right: 8px; border-radius: 50%;}
.apt-dot.teal {background:#168c91}.apt-dot.gold {background:#d89b2b}
.apt-dot.blue {background:#3677bb}.apt-dot.red {background:#c95748}
.apt-type-card {padding: 20px 22px; margin: 8px 0 18px; border: 1px solid #e6e1d8;
  border-radius: 22px; background: #fffdf9;}
.apt-section-title {margin-bottom: 14px; color: #5f6d82; font-size: .86rem; font-weight: 780;}
.apt-type-grid {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 18px;}
.apt-type {display:flex; justify-content:space-between; align-items:baseline; gap:8px;
  padding: 7px 0; border-bottom: 1px solid #eee8df;}
.apt-type-name {color:#10233e; font-size:.9rem; font-weight:780;}
.apt-type-price {color:#2672bb; font-size:.98rem; font-weight:820; white-space:nowrap;}
.apt-type-count {color:#8a94a6; font-size:.78rem; font-weight:550;}
@media (max-width: 900px) {
  .apt-hero {padding: 28px 24px}.apt-title{font-size:1.75rem}
  .apt-kpi-grid {grid-template-columns: repeat(2, minmax(0, 1fr));}
  .apt-type-grid {grid-template-columns: repeat(2, minmax(0, 1fr));}
}
@media (max-width: 560px) {
  .apt-kpi-grid,.apt-type-grid {grid-template-columns: 1fr;}
}
</style>
"""


def _metric_card(label, value, note, color):
    return (f'<div class="apt-kpi"><div class="apt-kpi-label"><span class="apt-dot {color}"></span>'
            f'{escape(label)}</div><div class="apt-kpi-value">{escape(value)}</div>'
            f'<div class="apt-kpi-note">{escape(note)}</div></div>')


def _area_summary(sample):
    by_area = sample.assign(area_group=sample["area_m2"].round(1)).groupby("area_group").agg(
        거래수=("id", "size"), 중위가격=("price_eok", "median"),
        최저가=("price_eok", "min"), 최고가=("price_eok", "max"),
        최근계약=("deal_date", "max"),
    ).reset_index()
    if len(by_area) > 15:
        by_area = by_area.nlargest(15, "거래수")
    return by_area.sort_values("area_group").reset_index(drop=True)


def render_apartment_detail(sample, key):
    if sample.empty:
        st.info("현재 필터에 해당하는 실거래가 없습니다.")
        return
    row = apartment_stats(sample).iloc[0]
    trend = monthly_stats(sample)
    st.html(APARTMENT_DASHBOARD_CSS)
    address = row["address"] or f"{row['dong']} · 상세 주소 미제공"
    area_range = f"전용 {row['min_area']:.0f}~{row['max_area']:.0f}㎡"
    st.html(f"""
    <section class="apt-hero">
      <div class="apt-eyebrow">APARTMENT TRANSACTION DASHBOARD</div>
      <div class="apt-title">{escape(str(row['apartment']))}</div>
      <div class="apt-address">{escape(str(address))}</div>
      <div class="apt-summary">실거래 {row['count']:,}건 · {escape(area_range)} · 최근 계약 {escape(str(row['latest_date']))}</div>
    </section>
    """)
    cards = "".join([
        _metric_card("선택 기간 거래", f"{row['count']:,}건", f"최근 계약 {row['latest_date']}", "teal"),
        _metric_card("중위 실거래가", f"{row['median_price']:.2f}억원",
                     f"평당 {row['median_per_pyeong']:,.0f}만원", "gold"),
        _metric_card("최근일 중위가", f"{row['latest_price']:.2f}억원",
                     f"해당 일 {row['latest_count']:,}건 기준", "blue"),
        _metric_card("실거래 범위", f"{row['min_price']:.2f}~{row['max_price']:.2f}억",
                     "선택 조건 내 최저~최고", "red"),
    ])
    st.html(f'<div class="apt-kpi-grid">{cards}</div>')

    by_area = _area_summary(sample)
    type_items = "".join(
        f'<div class="apt-type"><span class="apt-type-name">전용 {area:.1f}㎡</span>'
        f'<span class="apt-type-price">{price:.2f}억 <span class="apt-type-count">({count:,}건)</span></span></div>'
        for area, price, count in by_area[["area_group", "중위가격", "거래수"]].itertuples(index=False, name=None)
    )
    st.html(f'<section class="apt-type-card"><div class="apt-section-title">전용면적별 중위가격 · 거래수</div>'
            f'<div class="apt-type-grid">{type_items}</div></section>')

    left, right = st.columns([3, 2])
    with left.container(border=True, height="stretch"):
        st.markdown("**월별 중위 실거래가**")
        price_chart = (alt.Chart(trend).mark_area(
            line={"color": "#2477B8", "strokeWidth": 3}, color="#D7E9F6", opacity=.65,
            point={"filled": True, "fill": "white", "stroke": "#2477B8", "strokeWidth": 2},
        ).encode(
            x=alt.X("계약월:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("중위가격(억원):Q", title="억원", scale=alt.Scale(zero=False)),
            tooltip=["계약월:N", alt.Tooltip("중위가격(억원):Q", format=".2f"), "거래량:Q"],
        ).properties(height=250))
        st.altair_chart(price_chart)
    with right.container(border=True, height="stretch"):
        st.markdown("**월별 거래량**")
        volume_chart = (alt.Chart(trend).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5,
                                                  color="#15909A").encode(
            x=alt.X("계약월:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("거래량:Q", title="건"),
            tooltip=["계약월:N", "거래량:Q"],
        ).properties(height=250))
        st.altair_chart(volume_chart)

    st.markdown("**최근 실거래**")
    recent = sample.sort_values(["deal_date", "id"], ascending=False).head(10).copy()
    recent = recent[["deal_date", "area_m2", "price_eok", "floor", "price_per_pyeong"]].rename(columns={
        "deal_date": "계약일", "area_m2": "전용면적(㎡)", "price_eok": "거래가(억원)",
        "floor": "층", "price_per_pyeong": "평당가격(만원)",
    })
    st.dataframe(recent, hide_index=True, key=f"{key}_recent", height=280, column_config={
        "전용면적(㎡)": st.column_config.NumberColumn(format="%.1f㎡"),
        "거래가(억원)": st.column_config.NumberColumn(format="%.2f억원"),
        "평당가격(만원)": st.column_config.NumberColumn(format="%,.0f만원"),
    })
    st.caption("모든 지표는 왼쪽에서 선택한 계약 기간·면적·가격 조건을 따릅니다.")


def render_dashboard(summary, trades, region_label):
    st.subheader(f"{region_label} 아파트 대시보드", icon=":material/dashboard:")
    if summary.empty:
        st.info("선택 조건에 맞는 실거래가 없습니다. 왼쪽 지역·기간·검색 조건을 조정하세요.")
        return
    monthly = monthly_stats(trades)
    latest_month = monthly.iloc[-1]
    previous_price = monthly.iloc[-2]["중위가격(억원)"] if len(monthly) > 1 else None
    delta = latest_month["중위가격(억원)"] - previous_price if previous_price is not None else None
    with st.container(horizontal=True):
        st.metric("조회 아파트", f"{len(summary):,}개", border=True,
                  help="주소가 다른 동명 아파트는 별도 단지로 계산합니다.")
        st.metric("최근 계약월", latest_month["계약월"], f"{latest_month['거래량']:,}건", border=True,
                  chart_data=monthly["거래량"].tolist(), chart_type="bar")
        st.metric("최근월 중위가격", f"{latest_month['중위가격(억원)']:.2f}억원",
                  f"{delta:+.2f}억원" if delta is not None else None, border=True,
                  chart_data=monthly["중위가격(억원)"].tolist(), chart_type="line")
        st.metric("평당 중위가격", f"{summary['median_per_pyeong'].median():,.0f}만원", border=True,
                  help="단지별 평당 중위가격의 중앙값입니다.")
    detail_rows = summary.sort_values(["count", "latest_date", "apartment"],
                                      ascending=[False, False, True]).reset_index(drop=True)
    options = list(range(len(detail_rows)))
    signature = tuple(tuple(row) for row in detail_rows[["region_code", "dong", "address", "apartment"]].values)
    if st.session_state.get("apartment_options") != signature:
        st.session_state["apartment_detail"] = 0
        st.session_state["apartment_options"] = signature
    selected = st.selectbox("상세 대시보드를 볼 아파트", options, key="apartment_detail",
                            format_func=lambda i: f"{detail_rows.iloc[i]['apartment']} · "
                                                  f"{detail_rows.iloc[i]['address'] or detail_rows.iloc[i]['dong']}")
    render_apartment_detail(apartment_sample(trades, detail_rows.iloc[selected]), "dashboard")
    st.space("medium")
    st.subheader("지역 내 아파트 비교", icon=":material/compare_arrows:")
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
    st.markdown("**거래가 활발한 아파트**")
    cards = ranked.head(6).to_dict("records")
    for offset in range(0, len(cards), 3):
        for rank, (column, row) in enumerate(zip(st.columns(3), cards[offset:offset + 3]), start=offset + 1):
            with column.container(border=True):
                st.badge(f"{rank}위", color="blue" if rank <= 3 else "gray")
                st.markdown(f"### {row['apartment']}")
                st.caption(row["address"] or row["dong"])
                st.metric("중위 실거래가", f"{row['median_price']:.2f}억원")
                st.markdown(f":material/contract: **{row['count']:,}건**　:material/straighten: "
                            f"{row['min_area']:.0f}~{row['max_area']:.0f}㎡")
                st.caption(f"범위 {row['min_price']:.2f}~{row['max_price']:.2f}억 · "
                           f"최근 {row['latest_date']} {row['latest_price']:.2f}억")

    st.markdown("**선택 정렬 기준 상위 12개 비교**")
    comparison = ranked.head(12).copy()
    # Include rank and address so identically named complexes do not merge in charts.
    comparison["단지"] = [f"{i + 1:02d}. {r.apartment} · {r.dong}" for i, r in comparison.iterrows()]
    comparison = comparison.rename(columns={"count": "거래수", "median_price": "중위가격(억원)"})
    a, b = st.columns(2)
    with a.container(border=True):
        st.markdown("**거래량**")
        st.bar_chart(comparison, x="단지", y="거래수", horizontal=True, color="#087F8C", height=350)
    with b.container(border=True):
        st.markdown("**중위 실거래가**")
        st.bar_chart(comparison, x="단지", y="중위가격(억원)", horizontal=True, color="#D98A32", height=350)

    st.markdown("**아파트별 전체 통계**")
    table = ranked[list(SUMMARY_LABELS)].rename(columns=SUMMARY_LABELS).round(2)
    st.dataframe(table, hide_index=True, key="apartment_summary", height=420,
                 column_config={
                     "아파트": st.column_config.TextColumn(pinned=True),
                     "거래수": st.column_config.ProgressColumn(min_value=0, max_value=max(ranked["count"]), format="%d건"),
                     "중위가격(억원)": st.column_config.NumberColumn(format="%.2f억원"),
                     "최저가(억원)": st.column_config.NumberColumn(format="%.2f억원"),
                     "최고가(억원)": st.column_config.NumberColumn(format="%.2f억원"),
                     "최근일 중위가(억원)": st.column_config.NumberColumn(format="%.2f억원"),
                     "평당중위가(만원)": st.column_config.NumberColumn(format="%,.0f만원"),
                 })
    st.download_button("아파트 통계 CSV 저장", export_csv(table), file_name="apartment-statistics.csv",
                       mime="text/csv", key="apartment_export")

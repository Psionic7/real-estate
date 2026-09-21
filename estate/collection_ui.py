import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from estate.config import api_endpoint, service_key
from estate.db import connect, decode_response_xml
from estate.molit import parse_page
from estate.scheduler import (KST, cancel_pending, delete_target, enqueue, recent_months, save_target,
                              targets, toggle_target)


def kst(value):
    return datetime.fromisoformat(value).astimezone(KST).strftime("%Y-%m-%d %H:%M") if value else "—"


@st.fragment(run_every=5)
def job_status(path):
    with connect(path) as conn:
        state = conn.execute("SELECT * FROM worker_state WHERE id=1").fetchone()
        jobs = pd.read_sql_query("SELECT id,kind,region_name,status,completed_months,row_count,current_month,"
                                 "created_at,finished_at,message FROM collection_jobs ORDER BY id DESC LIMIT 30", conn)
    alive = state and state["status"] == "running" and (
        datetime.now(timezone.utc) - datetime.fromisoformat(state["heartbeat_at"])).total_seconds() < 90
    st.caption("수집 처리기: 실행 중 · 작업 상태는 5초마다 갱신됩니다." if alive else
               "수집 처리기: 대기/미실행 · 웹 앱 또는 Windows 수집 작업이 실행되면 대기열을 처리합니다.")
    st.dataframe(jobs.rename(columns={"id": "작업번호", "kind": "요청유형", "region_name": "지역",
        "status": "상태", "completed_months": "완료개월", "row_count": "저장건수", "current_month": "처리월",
        "created_at": "요청시각(UTC)", "finished_at": "완료시각(UTC)", "message": "안내"}), hide_index=True, width="stretch")
    queued = jobs[jobs["status"] == "queued"] if not jobs.empty else jobs
    if not queued.empty:
        job_id = st.selectbox("취소할 대기 작업", queued["id"].tolist(), key="cancel_job_id")
        if st.button("대기 작업 취소", key="cancel_job"):
            cancel_pending(path, int(job_id))
            st.rerun(scope="fragment")


def render_target_settings(path):
    st.subheader("수집 지역 설정")
    st.caption("기본값: 용인 수지·성남 분당·수원 광교 / 매일 오전 6시(한국시간) / 최근 12개월. 저장한 지역만 자동 수집합니다.")
    st.caption("수원 광교 기본 범위는 이의동·하동·원천동 전체입니다. API는 영통구 전체를 반환하며, 분석 데이터는 선택한 법정동으로 제한합니다.")
    saved = targets(path)
    choices = {r["id"]: r for r in saved}
    selected = st.selectbox("수집할 지역 선택", [r["id"] for r in saved] + [0],
                            format_func=lambda i: f"{choices[i]['display_name']} · {choices[i]['region_code']}" if i else "새 지역 직접 입력",
                            key="collection_target")
    item = choices.get(selected, {})
    with st.form(f"target_settings_{selected}"):
        a, b = st.columns(2)
        code = a.text_input("지역코드 (법정동 앞 5자리)", item.get("region_code", ""),
                            disabled=bool(selected))
        name = b.text_input("시도·시군구 전체 이름", item.get("region_name", ""))
        label = a.text_input("화면 표시 이름", item.get("display_name", ""))
        dongs = b.text_input("수집할 법정동 (쉼표 구분, 비우면 구 전체)", ", ".join(json.loads(item.get("dong_filter", "[]"))))
        schedule = a.selectbox("수집 주기", ["매일 지정 시각", "일정 간격"],
                               index=0 if item.get("schedule_kind", "daily") == "daily" else 1)
        daily = b.text_input("매일 실행 시각 (한국시간 HH:MM)", item.get("daily_time", "06:00"))
        minutes = a.number_input("일정 간격 선택 시 반복 분", 60, 43200, item.get("interval_minutes", 1440), step=60)
        lookback = b.number_input("매번 갱신할 최근 개월 수", 1, 300, item.get("lookback_months", 12))
        enabled = st.checkbox("자동 수집 사용", bool(item.get("enabled", True)), key=f"target_enabled_{selected}")
        save = st.form_submit_button("지역·주기 저장")
    if save:
        try:
            save_target(path, code, name, label, dongs, "daily" if schedule == "매일 지정 시각" else "interval",
                        minutes, daily, lookback, enabled)
            st.success("수집 설정을 저장했습니다. 다음 실행 시각은 아래 표에서 확인할 수 있습니다.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    current = targets(path)
    st.dataframe(pd.DataFrame([{"지역": r["display_name"], "코드": r["region_code"],
        "법정동": ", ".join(json.loads(r["dong_filter"])) or "전체",
        "주기": f"매일 {r['daily_time']}" if r["schedule_kind"] == "daily" else f"{r['interval_minutes']}분",
        "최근개월": r["lookback_months"], "자동수집": bool(r["enabled"]), "다음 실행(한국시간)": kst(r["next_run_at"])}
        for r in current]), hide_index=True, width="stretch")
    if selected:
        if st.button("이 지역 자동 수집 중지" if item["enabled"] else "이 지역 자동 수집 재개", key="toggle_target"):
            toggle_target(path, selected, not item["enabled"])
            st.rerun()
        with st.expander("수집 지역 삭제"):
            st.caption("수집 일정과 대기 작업만 삭제합니다. 이미 저장된 실거래·매물·좌표는 보존됩니다.")
            with st.form(f"delete_target_{selected}"):
                confirmed = st.checkbox(f"{item['display_name']} 수집 설정 삭제 확인")
                remove = st.form_submit_button("지역 삭제", type="secondary")
            if remove:
                if not confirmed:
                    st.error("삭제 확인을 선택하세요.")
                else:
                    try:
                        delete_target(path, selected)
                        st.success("수집 지역 설정을 삭제했습니다. 기존 데이터는 보존됩니다.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))


def render_manual_collection(path):
    st.subheader("실거래 수집")
    current = targets(path)
    choices = {r["id"]: r for r in current}
    selected = st.selectbox("수집할 지역", list(choices),
                            format_func=lambda i: f"{choices[i]['display_name']} · {choices[i]['region_code']}",
                            key="manual_target") if choices else None
    if selected:
        item = choices[selected]
        default_months = recent_months(item["lookback_months"])
        with st.form(f"manual_collect_{selected}"):
            left, right = st.columns(2)
            start = left.text_input("시작 계약월 (YYYYMM)", default_months[0])
            end = right.text_input("종료 계약월 (YYYYMM)", default_months[-1])
            request = st.form_submit_button("선택 지역 지금 수집", key="request_collection")
        if request:
            try:
                if not service_key():
                    raise ValueError("일반인증키.txt 또는 .env에 인증키를 설정하세요.")
                api_endpoint()
                job = enqueue(path, selected, start, end)
                st.success(f"작업 #{job}를 접수했습니다. 아래에서 진행 상태를 확인하세요. 완료 후 왼쪽 새로고침으로 통계를 갱신합니다.")
            except ValueError as exc:
                st.error(str(exc))
    if st.button("저장한 모든 지역 지금 수집", key="collect_all", disabled=not current):
        messages = []
        if not service_key():
            st.error("일반인증키.txt 또는 .env에 인증키를 설정하세요.")
        else:
            for r in current:
                try:
                    messages.append(f"{r['display_name']}: 작업 #{enqueue(path, r['id'])} 접수")
                except ValueError as exc:
                    messages.append(f"{r['display_name']}: {exc}")
            st.info(" / ".join(messages))
    st.caption("자동 수집 중지는 이후 예약을 멈춥니다. 이미 실행 중인 수집과 직접 요청한 작업은 계속 처리합니다.")
    job_status(path)


def render_collection(path):
    """Legacy wrapper for callers that want both local administration views."""
    render_target_settings(path)
    render_manual_collection(path)


def render_archive(path):
    st.markdown("**API 전체 필드·원본 조회**")
    st.caption("분석용 현재 거래와 별도로 응답 XML·요청 조건·모든 item 필드를 수집 회차별로 저장합니다. 해제·정정 전 이력도 원본에서 확인할 수 있습니다.")
    with connect(path) as conn:
        runs = [dict(r) for r in conn.execute("SELECT r.id,r.scope,r.status,r.started_at,COUNT(p.id) pages "
            "FROM collection_runs r JOIN api_pages p ON r.id=p.run_id GROUP BY r.id ORDER BY r.id DESC LIMIT 100")]
    if not runs:
        st.info("API 수집이 완료되면 원본을 조회할 수 있습니다.")
        return
    choices = {r["id"]: r for r in runs}
    run_id = st.selectbox("원본 수집 회차 (최근 100회)", list(choices),
                         format_func=lambda i: f"#{i} · {choices[i]['scope']} · {kst(choices[i]['started_at'])} · {choices[i]['status']}")
    with connect(path) as conn:
        pages = conn.execute("SELECT page_no,response_xml,request_json FROM api_pages WHERE run_id=? ORDER BY page_no", (run_id,)).fetchall()
    xml_pages = [decode_response_xml(row["response_xml"]) for row in pages]
    raw_items = [item for payload in xml_pages for item in parse_page(payload)[1]]
    st.caption(f"원본 {len(pages)}페이지 · {len(raw_items):,}행. 광교 수집의 원본에는 API 조회 단위인 영통구 전체가 포함됩니다.")
    st.dataframe(pd.DataFrame(raw_items), hide_index=True, width="stretch")
    st.download_button("전체 필드 JSON 다운로드", json.dumps(raw_items, ensure_ascii=False, indent=2).encode(),
                       file_name=f"api-run-{run_id}.json", mime="application/json")
    page = st.selectbox("XML 페이지", range(len(pages)), format_func=lambda i: f"{pages[i]['page_no']}페이지")
    st.download_button("응답 원문 XML 다운로드", xml_pages[page],
                       file_name=f"api-run-{run_id}-page-{pages[page]['page_no']}.xml", mime="application/xml")

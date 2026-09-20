# 실제 데이터 수집과 자동화

업데이트: 2026-09-19

## 현재 설정

| 표시 지역 | API 지역코드 | 주소 지역명 | 분석용 법정동 |
|---|---|---|---|
| 용인 수지 | 41465 | 경기도 용인시 수지구 | 전체 |
| 성남 분당 | 41135 | 경기도 성남시 분당구 | 전체 |
| 수원 광교 | 41117 | 경기도 수원시 영통구 | 이의동, 하동, 원천동 |

매일 **오전 06:00 한국시간**, 최근 **12개월**을 재수집한다. 초기 데이터는 2000년 1월부터 현재월까지 조회해 저장한다.
API 제공 이전의 빈 월도 성공 수집 이력으로 남으므로 초기 수집을 재개할 때 다시 호출하지 않는다.
실거래 통계에서는 해제 거래를 제외하므로 화면의 건수는 저장 건수보다 작을 수 있다.

‘광교’는 독립된 API 시군구 코드가 아니다. API 요청은 영통구 단위로 실행하고 분석 테이블에는 설정한 법정동만 반영한다.
원천동 전체를 포함하는 편의상 범위로, 광교신도시의 정확한 경계나 행정동 경계와 일치하지 않는다. 웹에서 법정동을 변경할 수 있다.
API 원본 보관에는 영통구 전체 응답이 남는다. [영통구의 광교 분동 안내](https://yt.suwon.go.kr/_bbsplus/view.asp?bd_gubn=1&code=tbl_bbs_sub0209&mnuflag=&no=MjcwOCAg&page=1200)를 참고했다.

## 인증과 엔드포인트

환경변수/.env 설정이 있으면 우선 사용하고, 없으면 프로젝트 루트의 `api-key.txt`, `end-point.txt`를 읽는다.
이전 파일명인 `일반인증키.txt`, `엔드포인트.txt`도 호환한다.
키 원문은 화면/로그/요청 메타데이터에 출력하지 않으며 두 파일은 Git 제외 목록에 추가했다.
현재 파일의 일반 API 기본 주소 뒤에 `/getRTMSDataSvcAptTrade`를 자동으로 붙인다.
일반/상세 아파트 매매 API의 공공데이터포털 HTTPS 주소만 허용한다. 임의 호스트에 키를 전송하지 않는다.

현재 연결: [국토교통부 아파트 매매 실거래가 자료](https://www.data.go.kr/data/15126469/openapi.do).
이 API는 아파트 매매 신고자료를 제공한다. 현재 매물 광고나 지도 좌표는 제공하지 않는다.
좌표를 지도에 표시하려면 기존의 카카오 키 설정 및 주소 변환을 별도로 실행해야 한다.

## 웹 사용법

1. 실제 데이터 → 데이터 관리로 이동한다.
2. ‘수집할 지역 선택’에서 기존 지역 또는 ‘새 지역 직접 입력’을 선택한다.
3. 지역코드, 시도·시군구 전체 이름, 표시 이름, 법정동 범위를 입력한다. 법정동이 비어 있으면 구 전체다.
4. ‘매일 지정 시각’ 또는 ‘일정 간격’을 선택하고 수집 개월 수를 설정한 후 저장한다.
5. 즉시 필요하면 계약월 범위를 입력하고 ‘선택 지역 지금 수집’을 누른다. ‘저장한 모든 지역 지금 수집’도 가능하다.
6. 작업 상태는 5초마다 갱신된다. 완료 후 왼쪽 새로고침으로 통계·수집 범위·원본 목록을 갱신한다.

한 지역에 대기/실행 중인 작업이 있으면 중복 요청과 범위 변경을 막는다.
자동 수집 중지는 이후 자동 요청과 대기 중인 자동 작업을 취소한다. 직접 요청 및 이미 실행 중인 작업은 계속 처리한다.
대기 작업은 취소 가능하다. 실패 시 완료된 월은 보존되며 같은 범위를 다시 요청할 수 있다.
수집 개월 수/범위는 최대 300개월이며 그중 원천 API가 실제 제공하는 자료만 저장된다. 기본값은 전체 역사 기간이 아닌 최근 12개월이다.

## 자동 실행 방식

- SQLite의 `collection_targets`가 실제 예약의 기준이다. 웹에서 변경한 시각/주기/범위가 다음 실행에 반영된다.
- 웹 서버가 살아 있으면 별도 스레드가 대기열을 처리한다. 브라우저를 닫아도 서버 프로세스가 살아 있으면 계속 실행된다.
- Windows 작업 `KH-Property-Collector`는 5분마다 예약을 확인하는 Python 프로세스를 시작한다. API를 5분마다 수집한다는 뜻은 아니다.
- 등록된 일일 시각이 지나거나 직접 요청한 대기 작업이 있을 때만 수집한다. 웹 서버가 꺼져 있어도 처리할 수 있다.
- Windows 로그인 세션이 있는 상태에서 실행하며 PC 전원 꺼짐/절전/로그아웃 상태에서 동작을 보장하지 않는다.
- 놓친 예약은 다음 실행 시 한 번 처리한다. 지난 여러 날의 예약을 한꺼번에 반복하지 않는다.
- OS 파일 잠금으로 웹/작업 스케줄러/별도 워커 중 하나만 대기열을 처리한다. 종료 시 잠금은 OS에서 해제된다.
- 프로세스 중단 후에는 미완료 월부터 작업을 재개한다. 원본은 회차별로 남고 분석 데이터는 지역·월 단위로 원자 교체한다.

등록/삭제 명령:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_collector.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_collector.ps1 -Remove
```

명령줄에서 워커만 계속 실행하려면:

```powershell
.\.venv\Scripts\python.exe -m estate.worker
```

예약 확인과 대기 작업 처리 후 종료하려면 `--once`를 추가한다.
현재 윈도우 작업은 사용자 로그온 방식으로 등록되며 별도 암호를 저장하지 않는다.
실행 원리는 [Windows 작업 스케줄러 Principal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal)에 따른다.

## API 응답 전체 보존

화면에 당장 사용하지 않는 필드도 버리지 않는다.

| 테이블 | 저장 내용 |
|---|---|
| trades | 선택 지역·법정동의 현재 정규화 거래와 item 전체 raw_json |
| api_pages | 회차/페이지별 zlib 압축 원문 XML BLOB, 엔드포인트, 인증키 제외 요청조건, 수신 시각. 모든 item 필드 보존 |
| api_items | 이전 스키마 호환용 테이블. 신규 수집은 원문 XML과 trades.raw_json의 중복 저장을 피함 |
| collection_runs | 월별 API 수집 결과, 실패 여부, 반영 건수 |
| collection_targets | 관심 지역, 법정동, 주기, 다음 실행 시각 |
| collection_jobs | 사용자/자동 요청, 진행 월, 완료 개월, 건수, 성공·실패·취소 |
| worker_state | 처리기의 최근 생존 신호 |

실제 일반 API에서 확인한 20개 필드는 `aptDong`, `aptNm`, `buildYear`, `buyerGbn`, `cdealDay`, `cdealType`,
`dealAmount`, `dealDay`, `dealMonth`, `dealYear`, `dealingGbn`, `estateAgentSggNm`, `excluUseAr`, `floor`, `jibun`,
`landLeaseholdGbn`, `rgstDate`, `sggCd`, `slerGbn`, `umdNm`이다. 원천이 비워 둔 값도 원본에는 그대로 남는다.
파싱·정규화에 실패한 회차의 이미 수신한 응답도 보관한다. 분석용 현재 거래는 해당 월 검증이 전부 통과한 뒤에만 교체한다.
원문에서 인증키가 그대로 반사되어 돌아오는 경우 해당 문자열은 `[REDACTED]`로 대체한다.

‘API 전체 필드·수집 원문’에서 최근 100개 회차를 선택해 전체 필드를 표로 보거나 JSON/XML을 내려받을 수 있다.
더 오래된 회차도 DB에는 남아 있다. SQL 활용 예:

```sql
SELECT region_code, deal_date, apartment,
       json_extract(raw_json, '$.dealingGbn') AS dealing_type,
       json_extract(raw_json, '$.rgstDate') AS registration_date,
       json_extract(raw_json, '$.buyerGbn') AS buyer_type
FROM trades;

-- 전체 원천 필드는 웹의 ‘API 전체 필드·원본 조회’에서 XML을 해제해 표/JSON으로 확인
```

원본 이력은 자동 삭제하지 않는다. 매일 같은 월을 재수집하면 원본 누적 크기가 증가하므로 백업·보존 용량을 관리해야 한다.
스키마 버전은 2이며 기존 DB를 지우지 않고 새 테이블과 설정 열을 추가한다.

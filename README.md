# 집의 흐름 — 한국 아파트 데이터 지도

Windows · Python · Streamlit · SQLite로 만든 아파트 매매 실거래·매물 분석 MVP입니다.
**실제 공공데이터만 사용하며 첫 화면은 용인시 수지구입니다.** 저장소에는 용인 수지·성남 분당·수원 광교의 2000년 이후 조회 결과가 압축 초기 DB로 포함됩니다.

## 바로 실행

이 작업 폴더에는 Python 3.12 가상환경과 실행 패키지가 준비되어 있습니다.

```powershell
.\run.bat
```

브라우저에서 http://localhost:8501 에 접속합니다. 이 화면과 Streamlit Cloud 배포본은 **조회 전용**입니다. 왼쪽 지역 필터로 조회 범위를 변경합니다.
수집 지역 설정과 수집은 이 PC의 별도 관리자 앱에서 합니다.

```powershell
.\run-admin.bat
```

관리자 화면은 기본적으로 http://127.0.0.1:8502 에서 열립니다. 8502가 이미 사용 중이면 실행 창에 표시되는 다음 빈 포트(최대 8511)로 열립니다. `127.0.0.1` 바인딩과 로컬 실행 플래그가 모두 있어야 관리자 기능이 열립니다. 관리자 앱은 외부 네트워크나 Streamlit Cloud에서 실행되지 않습니다. 여러 Windows 계정이 한 PC를 공유한다면 프로젝트 폴더와 실행 계정의 접근 권한도 제한하세요.
명령으로 직접 실행하려면:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

새 Windows PC에서는 Python 3.12 이상을 설치한 뒤 다음을 실행합니다. Python 3.12에서 검증했습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Python 실행 파일을 직접 지정할 수도 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Python "C:\Python312\python.exe"
```

활성화 스크립트 없이 `.venv\Scripts\python.exe`를 사용합니다. 실행 정책 변경은 위 프로세스에만 적용됩니다.
운영체제 PATH의 기존 Python 3.9와 프로젝트 Python 3.12는 분리되어 있습니다.

## 구현 기능

- 국토교통부 아파트 매매 상세 API: 지역·월별 전체 페이지 수집, 정규화, 원본 필드 보존
- 재수집 시 지역·월을 원자적으로 교체해 정정·해제 반영, 실패 시 기존 자료 유지
- 매물 CSV/JSON 검증·가져오기, HTTPS 표준 JSON 피드 CLI 연동
- 매물 확인 시각별 스냅샷, 가격·상태 이력, 오래된/종료 매물 제외
- 카카오 주소 API 좌표 변환 및 SQLite 캐시, 좌표 미확정 자료 분리
- 첫 화면 지도 탐색: 지도 마커에서 단지별 실거래가와 현재 매물을 함께 확인
- 지도 단지 선택 상세, 지역·계약일·면적·금액·주소·반경 필터, 관심 단지 저장
- 관심 단지 대시보드: 최근 1년 중위 실거래가·3개월 변화·거래량·활성 매물 호가 비교
- 지도 아파트명·최근 3개월 평균가격 라벨, 거래가 없으면 단지의 최근 거래월 평균과 계산 기간 표시
- 실거래 중위가격, 거래량, 평당가격, 법정동·월별 통계, 유사 면적 호가 비교
- UTF-8 BOM CSV 내려받기, 수집 범위/기록 조회, SQLite 온라인 백업

현재 범위는 **아파트 매매**입니다. 전월세·오피스텔·토지, 임의 매물 사이트 크롤러, 사용자 계정은 포함하지 않습니다.
지도 배경 타일에는 인터넷 연결이 필요합니다.
관심 단지는 계정 없이 사용할 수 있도록 각 사용자의 브라우저 주소와 세션에 최대 20개까지 저장됩니다.

## 실제 데이터 연결

1. `.env.example`을 `.env`로 복사하거나 로컬에서는 `api-key.txt`를 사용합니다.
2. 공공데이터포털에서 [아파트 매매 실거래가 상세 자료](https://www.data.go.kr/data/15126468/openapi.do)를 신청하고 `MOLIT_SERVICE_KEY`를 설정합니다.
3. [행정안전부 주소 검색 API](https://www.data.go.kr/data/15057017/openapi.do) 승인키가 있으면 `JUSO_ADDRESS_SEARCH_KEY`에 설정합니다. 검색 응답과 지번 일치 여부는 로컬 DB에 저장됩니다. 이 API만으로는 좌표가 나오지 않습니다.
4. 좌표제공 검색 API 승인키는 `JUSO_COORDINATE_SEARCH_KEY`에 따로 저장합니다. 현재 이 키가 없어도 실거래·주소 검색·기존 좌표 보강은 작동합니다. 좌표제공 API 연동은 승인 후 추가합니다.
5. 선택적으로 [카카오 로컬 API](https://developers.kakao.com/docs/ko/local/dev-guide) REST API 키를 `KAKAO_REST_API_KEY`에 설정할 수 있습니다.
6. `run-admin.bat`을 실행한 뒤 ‘수집 지역’에서 지역·주기를 저장하고 ‘실거래 수집’에서 한 지역·한 달을 먼저 검증하세요.
7. 매물 제공처의 사용 가능한 파일을 표준 양식에 맞춰 가져옵니다. 기본 양식은 `examples/listings_template.csv`, 상세 명세는 [데이터 명세](docs/DATA_CONTRACT.md)를 참고합니다.

```dotenv
MOLIT_SERVICE_KEY=발급받은키
JUSO_ADDRESS_SEARCH_KEY=주소검색승인키
JUSO_COORDINATE_SEARCH_KEY=
```

키는 커밋하지 않습니다. 배포본은 `data/estate.sqlite3.gz`를 첫 실행에 `data/estate.sqlite3`로 복원합니다. 배포 앱에는 수집·관리 메뉴와 수집 워커가 없습니다.

### 지도에 거래 원이 없는 경우

국토부 실거래 API 응답에는 단지 위도·경도가 없으므로 주소 좌표 변환이 별도로 필요합니다.
배경지도는 좌표 유무와 관계없이 표시하며, 지도 오버레이에는 좌표가 확인된 개별 아파트만 표시합니다. 지역 중심점이나 지역 평균을 아파트 위치처럼 표시하지 않습니다.
관리자 화면의 **데이터 품질·매물 → 공식 주소 검색·저장**에서 주소 검색 결과를 저장할 수 있습니다. 주소 검색 API 자체는 좌표를 주지 않습니다. **주소 좌표 보강**은 좌표가 부족할 때 기존 ArcGIS 필지 검증 경로로 실행되며 카카오 키가 있으면 카카오 주소 API를 먼저 사용합니다.
좌표 수집은 왼쪽에서 선택한 지역을 대상으로 하며 성공한 주소는 SQLite에 캐시합니다.
지도 중심 기본값은 화면 이동용이며 단지 좌표로 사용하지 않습니다. 검색 결과가 없어도 배경지도는 유지됩니다.
아파트 대시보드는 좌표 없이도 사용할 수 있습니다. 지도는 겹침 방지 카드에 단지명, 전용면적, 최근 평균가격, 실거래·매물 건수를 표시하며 확대하면 주변 카드가 추가로 나타납니다.

초기 좌표 캐시는 OpenStreetMap의 정확한 단지명 자료와 필지 주소 검색 결과를 함께 사용합니다. 필지·법정동 일치, 지역 범위, 후보 간 거리 검증을 모두 통과한 좌표만 저장하며 행정동 중심점으로 대체하지 않습니다. 좌표 출처에는 © OpenStreetMap contributors([ODbL](https://www.openstreetmap.org/copyright)), Esri ArcGIS World Geocoding Service, 도로명주소 조회 자료가 포함됩니다. 신규 실거래 수집이 끝나면 미등록 주소를 자동으로 보강하며, `KAKAO_REST_API_KEY`가 있으면 카카오 주소 API를 먼저 사용합니다. 데이터 관리 화면에서 좌표 커버리지와 미확정 건수를 확인할 수 있습니다.

```powershell
python scripts/import_osm_geocodes.py
python scripts/import_juso_geocodes.py
```
단지 통계는 지역·법정동·주소·단지명으로 구분하며 선택한 기간·면적·금액 조건을 따릅니다.
‘최근일 중위가’는 해당 단지의 가장 최근 계약일에 발생한 모든 거래의 중앙값입니다. 면적 구성 변화에 따라 달라지므로 가격 상승률로 해석하지 않습니다.

## 수집 명령

```powershell
# 최근 3개월을 매번 다시 조회해 지연 신고·해제·정정을 반영
.\.venv\Scripts\python.exe -m estate.cli refresh --region 11680 --region-name "서울특별시 강남구" --months 3

# 지정 기간 수집 (모든 지역은 법정동 코드 앞 5자리를 입력)
.\.venv\Scripts\python.exe -m estate.cli collect --region 11710 --region-name "서울특별시 송파구" --start 202601 --end 202608

# 기본 3개 지역을 2000년 1월부터 수집하고 배포용 압축 DB 생성 (중단 후 같은 명령으로 재개)
.\.venv\Scripts\python.exe -m estate.cli baseline --start 200001 --package

# 좌표 변환, 매물 가져오기
.\.venv\Scripts\python.exe -m estate.cli geocode --limit 100
.\.venv\Scripts\python.exe -m estate.cli import-listings .\my_listings.csv

# .env의 LISTINGS_FEED_URL / LISTINGS_FEED_TOKEN으로 표준 JSON 피드 연결
.\.venv\Scripts\python.exe -m estate.cli fetch-listings

# 상태 및 온라인 백업 (대상 파일은 새 파일이어야 함)
.\.venv\Scripts\python.exe -m estate.cli status
.\.venv\Scripts\python.exe -m estate.cli backup .\backups\estate-20260919.sqlite3
```

국토부 지역코드와 전체 지역명은 정확히 맞춰 입력해야 합니다. 지역 목록을 전국에 대해 자동 다운로드하는 기능은 후속 범위입니다.
매물 JSON 피드는 표준 배열을 한 응답으로 제공하는 공급자를 대상으로 하며 공급자별 페이지네이션은 별도 어댑터가 필요합니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

테스트는 임시 DB·모의 API 응답으로 수행합니다. 운영 API 키 없이 실제 거래/매물 제공처의 인증 호출을 검증할 수는 없습니다.
외부 연결 전 한 지역·한 달의 결과를 공식 제공 자료와 대조해야 합니다.

## 문서와 파일

- [프로젝트 계획서](docs/PROJECT_PLAN.md): 목표, 범위, 구조, 일정, 검수 기준
- [데이터 명세](docs/DATA_CONTRACT.md): DB·파일·통계 정의
- [운영 가이드](docs/OPERATIONS.md): Windows 수집 작업·백업·복구·장애 대응
- `app.py`: Streamlit 화면
- `estate/`: 수집, 데이터 검증, SQLite 저장, 지도·통계 계산, CLI
- `requirements-lock.txt`: 검증 환경의 전체 패키지 버전

네트워크 공유 폴더가 아닌 로컬 디스크에 SQLite를 두고, 첫 운영은 단일 PC·단일 수집 작업으로 시작합니다.

## 로컬 수집 데이터 배포

1. 로컬 관리자 화면에서 수집 작업이 끝난 것을 확인합니다.
2. **배포 데이터 → 배포용 스냅샷 생성**을 누릅니다. SQLite 온라인 백업으로 `data/estate.sqlite3.gz`를 만들며 수집 작업·API 원문·인증정보를 제외합니다.
3. `data/estate.sqlite3.gz`와 필요한 코드 변경을 GitHub `main`에 커밋·푸시합니다. Streamlit Cloud가 다시 배포되면 새 데이터가 나타납니다. 로컬 DB는 그대로 유지됩니다.

```powershell
git add data/estate.sqlite3.gz
git commit -m "Update public apartment data"
git push origin main
```

## Streamlit Community Cloud 배포

배포 진입점은 `app.py`, Python은 3.12를 사용합니다. Cloud에는 국토부·카카오 API 키를 설정할 필요가 없습니다. 공개 앱은 저장소의 압축 데이터만 표시하고 API 수집과 지역 설정을 실행하지 않습니다. 키는 로컬 `.env` 또는 Git 제외된 TXT에만 보관하세요.

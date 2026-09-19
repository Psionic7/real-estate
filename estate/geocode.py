from estate.db import connect, now_iso
from estate.http import DataSourceError, get, session


def geocode_pending(path, key, limit=100):
    if not key.strip():
        raise ValueError("KAKAO_REST_API_KEY를 설정하세요.")
    with connect(path) as conn:
        addresses = conn.execute("""
            SELECT DISTINCT a.address FROM (
                SELECT address FROM trades WHERE latitude IS NULL
                UNION SELECT address FROM listing_snapshots WHERE latitude IS NULL
            ) a LEFT JOIN geocodes g ON a.address=g.address
            WHERE g.address IS NULL AND a.address != '' ORDER BY a.address LIMIT ?
        """, (limit,)).fetchall()
    matched, unresolved = 0, 0
    with session() as client:
        for row in addresses:
            response = get(client, "https://dapi.kakao.com/v2/local/search/address.json",
                           headers={"Authorization": f"KakaoAK {key}"},
                           params={"query": row["address"], "analyze_type": "exact", "size": 2})
            try:
                documents = response.json()["documents"]
                # Ambiguous or missing matches remain absent, never fall back to a district centroid.
                if len(documents) != 1:
                    unresolved += 1
                    continue
                doc = documents[0]
                # A district/dong-only result cannot identify an apartment parcel.
                if not (doc.get("address") or {}).get("main_address_no"):
                    unresolved += 1
                    continue
                lat, lon = float(doc["y"]), float(doc["x"])
                if not (32 <= lat <= 39.5 and 124 <= lon <= 132):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise DataSourceError("주소 좌표 응답 검증에 실패했습니다.") from None
            with connect(path) as conn:
                conn.execute("INSERT INTO geocodes VALUES(?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET "
                             "latitude=excluded.latitude,longitude=excluded.longitude,updated_at=excluded.updated_at",
                             (row["address"], lat, lon, "kakao", now_iso()))
            matched += 1
    return matched, unresolved

"""Map view defaults are camera positions, never substitute property coordinates."""
import base64
from functools import lru_cache
from html import escape

import pydeck as pdk

DEFAULT_REGION = "41465"
REGION_VIEWS = {
    "41465": (37.322, 127.097, 12),  # 용인시 수지구
    "41135": (37.382, 127.119, 12),  # 성남시 분당구
    "41117": (37.294, 127.047, 12),  # 수원 광교
    "11680": (37.496, 127.062, 12),
    "11710": (37.505, 127.115, 12),
    "11440": (37.557, 126.909, 12),
    "26350": (35.174, 129.166, 12),
}

MAX_MARKERS = 1600


def _short_name(name, limit=11):
    name = str(name or "아파트")
    return name if len(name) <= limit else name[:limit - 1] + "…"


def _marker_content(point):
    area = str(point.get("area_text") or "면적 미상")
    average = point.get("average_price")
    asking = point.get("listing_median")
    if average is not None:
        price = f"{float(average):.1f}억"
        price_kind = "실"
        tone = "sale" if point.get("period_kind") == "최근 3개월" else "history"
    elif asking is not None:
        price = f"{float(asking):.1f}억"
        price_kind = "호"
        tone = "listing"
    else:
        price, price_kind, tone = "가격 미상", "—", "history"

    period_badge = ""
    if tone == "history":
        last_month = str(point.get("period") or "").split("~")[-1]
        if len(last_month) == 7 and last_month[4] == "-":
            period_badge = last_month[2:].replace("-", ".")
    badge = period_badge or (f"매물 {point['listing_count']}" if point.get("listing_count") else "")
    name = _short_name(point.get("apartment"), 8 if badge else 11)
    return area, price_kind, price, name, badge, tone


@lru_cache(maxsize=4096)
def _marker_icon(area, price_kind, price, name, badge, tone):
    colors = {
        "sale": ("#087F8C", "#E8F7F7", "#B9DDDF"),
        "history": ("#62758C", "#F0F3F7", "#D3DDE8"),
        "listing": ("#C36B2D", "#FFF2E5", "#EACBAE"),
    }
    accent, tint, stroke = colors[tone]
    area, price_kind, price, name, badge = map(escape, (area, price_kind, price, name, badge))
    badge_svg = (f'<rect x="124" y="43" width="43" height="19" rx="7" fill="{tint}"/>'
                 f'<text x="145.5" y="56.5" text-anchor="middle" font-size="9" font-weight="700" '
                 f'fill="{accent}">{badge}</text>') if badge else ""
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="180" height="84" viewBox="0 0 180 84">
<defs><filter id="shadow" x="-25%" y="-25%" width="150%" height="160%"><feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#10233E" flood-opacity=".19"/></filter></defs>
<g filter="url(#shadow)"><rect x="3" y="2" width="174" height="67" rx="12" fill="#FFFFFF" stroke="{stroke}" stroke-width="1.2"/>
<path d="M84 68 L90 77 L96 68" fill="#FFFFFF" stroke="{stroke}" stroke-width="1.2"/></g>
<rect x="3" y="3" width="4" height="64" rx="2" fill="{accent}"/>
<rect x="13" y="11" width="70" height="23" rx="7" fill="{tint}"/>
<text x="48" y="27" text-anchor="middle" font-family="Malgun Gothic,Apple SD Gothic Neo,sans-serif" font-size="11" font-weight="700" fill="#3C5568">{area}</text>
<text x="94" y="26" font-family="Malgun Gothic,Apple SD Gothic Neo,sans-serif" font-size="10" font-weight="700" fill="#708194">{price_kind}</text>
<text x="169" y="27" text-anchor="end" font-family="Malgun Gothic,Apple SD Gothic Neo,sans-serif" font-size="14" font-weight="800" fill="{accent}">{price}</text>
<line x1="13" y1="39" x2="167" y2="39" stroke="#E9EEF2"/>
<text x="14" y="57" font-family="Malgun Gothic,Apple SD Gothic Neo,sans-serif" font-size="12" font-weight="800" fill="#172B4D">{name}</text>
{badge_svg}
<circle cx="90" cy="78" r="3.5" fill="{accent}" stroke="#FFFFFF" stroke-width="1.5"/>
</svg>'''
    # The source is embedded in the map; no external image server is needed.
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {"url": "data:image/svg+xml;base64," + encoded,
            "width": 180, "height": 84, "anchorX": 90, "anchorY": 78}


def housing_deck(points, region, show_labels=True):
    """Render a basemap even with no geocoded properties or no matching trades."""
    if points:
        # Use all available points for the camera, independent of marker truncation.
        import pandas as pd

        lat = float(pd.Series([p["lat"] for p in points]).median())
        lon = float(pd.Series([p["lon"] for p in points]).median())
        zoom = 12 if region != "전체" else 7
    else:
        lat, lon, zoom = REGION_VIEWS.get(region, (36.3, 127.8, 7))
    shown = sorted(points, key=lambda point: point.get("priority", 0), reverse=True)[:MAX_MARKERS]
    layers = []
    if show_labels:
        if shown:
            cards = [dict(point, marker_icon=_marker_icon(*_marker_content(point))) for point in shown]
            layers.append(pdk.Layer(
                "IconLayer", id="apartment-cards", data=cards,
                get_position="[lon, lat]", get_icon="marker_icon", get_size=84,
                size_units="pixels", size_scale=1, alpha_cutoff=-1,
                pickable=True, auto_highlight=True,
                extensions=[{"@@type": "CollisionFilterExtension"}], collision_enabled=True,
                collision_group="apartment-cards", get_collision_priority="priority",
                collision_test_props={"sizeScale": 1.12},
            ))
    elif shown:
        layers.append(pdk.Layer(
            "ScatterplotLayer", id="apartment-pins", data=shown,
            get_position="[lon, lat]", get_radius=7, radius_units="pixels",
            get_fill_color="card_color", get_line_color=[255, 255, 255, 255],
            get_line_width=2, line_width_units="pixels", stroked=True, pickable=True,
        ))
    return pdk.Deck(
        map_provider="carto", map_style="road",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        layers=layers,
        tooltip={"text": "{apartment}\n{area_text}\n{summary}\n{address}",
                 "style": {"backgroundColor": "#10233e", "color": "white", "fontSize": "12px"}},
    )

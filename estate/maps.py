"""Map view defaults are camera positions, never substitute property coordinates."""
import pydeck as pdk

from estate.area import format_area_range

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


def _marker_details(point):
    """Keep map labels short while retaining the full period in the tooltip."""
    name = " ".join(str(point.get("apartment") or "아파트").split())
    if len(name) > 13:
        name = f"{name[:12]}…"
    area = str(point.get("area_text") or "면적 미상")
    price = point.get("average_price")
    listings = int(point.get("listing_count") or 0)
    if price is None:
        amount = point.get("listing_median")
        headline = f"{area}  매물 {amount:.1f}억" if amount is not None else f"{area}  매물"
        detail = f"{name} · {listings}건" if listings else name
        return headline + "\n" + detail, [154, 79, 24, 255], [255, 246, 229, 250]

    headline = f"{area}  실 {price:.1f}억"
    if point.get("period_kind") not in (None, "최근 3개월"):
        month = str(point.get("period") or "").split("~")[-1]
        period_note = month[2:].replace("-", ".") if len(month) == 7 else month
        detail = f"{name} · {period_note}" if period_note else name
        return headline + "\n" + detail, [63, 79, 107, 255], [247, 249, 253, 250]
    detail = f"{name} · 매물 {listings}" if listings else name
    return headline + "\n" + detail, [10, 97, 107, 255], [245, 255, 254, 250]


def housing_deck(points, region, show_labels=True, area_unit="㎡"):
    """Render a basemap even with no geocoded properties or no matching trades."""
    if points:
        # Use all available points for the camera, independent of marker truncation.
        import pandas as pd

        lat = float(pd.Series([p["lat"] for p in points]).median())
        lon = float(pd.Series([p["lon"] for p in points]).median())
        zoom = 12 if region != "전체" else 7
    else:
        lat, lon, zoom = REGION_VIEWS.get(region, (36.3, 127.8, 7))
    shown = []
    for point in points[:5000]:
        area = (format_area_range(point["min_area"], point["max_area"], area_unit)
                if "min_area" in point and "max_area" in point else point.get("area_text", "면적 미상"))
        shown.append(dict(point, area_text=area))
    layers = []
    if show_labels:
        if shown:
            cards = []
            for point in shown:
                label, color, background = _marker_details(point)
                cards.append(dict(point, marker_label=label,
                                  marker_text_color=color, marker_background=background))
            layers.append(pdk.Layer(
                "TextLayer", id="apartment-cards", data=cards,
                get_position="[lon, lat]", get_text="marker_label", get_size=12,
                get_color="marker_text_color", get_background_color="marker_background",
                get_text_anchor="'middle'", get_alignment_baseline="'center'",
                background=True, background_padding=[7, 5], billboard=True,
                font_family="'Malgun Gothic'", font_weight=700, line_height=1.18,
                character_set="'auto'",
                pickable=True, auto_highlight=True,
                extensions=[{"@@type": "CollisionFilterExtension"}], collision_enabled=True,
                collision_group="apartment-cards", get_collision_priority="priority",
                collision_test_props={"sizeScale": 1.35},
            ))
    elif shown:
        pins = []
        for point in shown:
            _, color, _ = _marker_details(point)
            pins.append(dict(point, marker_text_color=color))
        layers.append(pdk.Layer(
            "TextLayer", id="apartment-pins", data=pins,
            get_position="[lon, lat]", get_text="'◆'", get_size=18,
            get_color="marker_text_color", get_text_anchor="'middle'",
            get_alignment_baseline="'center'", pickable=True,
        ))
    return pdk.Deck(
        map_provider="carto", map_style="road",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        layers=layers,
        tooltip={"html": "<b>{apartment}</b><br>{area_text}<br>{summary}<br><span>{address}</span>",
                 "style": {"backgroundColor": "#10233e", "color": "white"}},
    )

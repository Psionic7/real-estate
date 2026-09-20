"""Map view defaults are camera positions, never substitute property coordinates."""
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


def housing_deck(points, region):
    """Render a basemap even with no geocoded properties or no matching trades."""
    if points:
        # Use all available points for the camera, independent of marker truncation.
        import pandas as pd

        lat = float(pd.Series([p["lat"] for p in points]).median())
        lon = float(pd.Series([p["lon"] for p in points]).median())
        zoom = 12 if region != "전체" else 7
    else:
        lat, lon, zoom = REGION_VIEWS.get(region, (36.3, 127.8, 7))
    shown = points[:5000]
    layers = [
        pdk.Layer("ScatterplotLayer", data=[p for p in shown if p["kind"] == kind],
                  id=layer_id, get_position="[lon, lat]", get_fill_color="color",
                  get_radius="radius", radius_min_pixels=min_pixels, radius_max_pixels=max_pixels,
                  stroked=True, get_line_color=[255, 255, 255, 200], line_width_min_pixels=1,
                  pickable=True, auto_highlight=True)
        for kind, layer_id, min_pixels, max_pixels in [("실거래", "trades", 12, 35),
                                                      ("매물 호가", "listings", 6, 20)]
    ]
    return pdk.Deck(
        map_provider="carto", map_style="road",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        layers=layers,
        tooltip={"text": "{apartment}\n{kind} {count}건 · 중위 {median_price}억원\n{address}"},
    )

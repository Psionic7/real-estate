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
    shown = points[:5000]
    layers = [
        pdk.Layer("ScatterplotLayer", data=[p for p in shown if p["kind"] == kind],
                  id=layer_id, get_position="[lon, lat]", get_fill_color="color",
                  get_radius="radius", radius_min_pixels=min_pixels, radius_max_pixels=max_pixels,
                  stroked=True, get_line_color=[255, 255, 255, 230], line_width_min_pixels=2,
                  pickable=True, auto_highlight=True)
        for kind, layer_id, min_pixels, max_pixels in [("지역 요약", "region-summary", 34, 55),
                                                      ("아파트", "apartments", 16, 38)]
    ]
    if show_labels:
        labels = sorted((p for p in shown if "label" in p),
                        key=lambda p: p["count"], reverse=True)[:100]
        if labels:
            characters = "".join(sorted(set("".join(point["label"] for point in labels))))
            layers.append(pdk.Layer(
                "TextLayer", id="apartment-labels", data=labels,
                get_position="[lon, lat]", get_text="label", get_size=13,
                get_color=[23, 43, 77], get_pixel_offset=[0, -30],
                get_text_anchor="middle", get_alignment_baseline="bottom",
                background=True, get_background_color=[255, 255, 255, 230],
                background_padding=[5, 3], font_family="Arial, 'Malgun Gothic', sans-serif",
                character_set=characters, pickable=True,
            ))
    return pdk.Deck(
        map_provider="carto", map_style="road",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        layers=layers,
        tooltip={"text": "{apartment}\n{summary}\n{address}"},
    )

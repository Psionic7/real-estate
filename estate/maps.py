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
    layers = []
    if show_labels:
        if shown:
            layers.append(pdk.Layer(
                "TextLayer", id="apartment-cards", data=shown,
                get_position="[lon, lat]", get_text="card_label", get_size=13,
                get_color=[255, 255, 255, 255], get_background_color="card_color",
                get_text_anchor="'middle'", get_alignment_baseline="'center'",
                background=True, background_padding=[8, 6], billboard=True,
                font_family="'Malgun Gothic'", font_weight=700, line_height=1.22,
                character_set="'auto'",
                pickable=True, auto_highlight=True,
                extensions=[{"@@type": "CollisionFilterExtension"}], collision_enabled=True,
                collision_group="apartment-cards", get_collision_priority="priority",
                collision_test_props={"sizeScale": 1.35},
            ))
    elif shown:
        layers.append(pdk.Layer(
            "TextLayer", id="apartment-pins", data=shown,
            get_position="[lon, lat]", get_text="'◆'", get_size=18,
            get_color="card_color", get_text_anchor="'middle'",
            get_alignment_baseline="'center'", pickable=True,
        ))
    return pdk.Deck(
        map_provider="carto", map_style="road",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        layers=layers,
        tooltip={"html": "<b>{apartment}</b><br>{area_text}<br>{summary}<br><span>{address}</span>",
                 "style": {"backgroundColor": "#10233e", "color": "white"}},
    )

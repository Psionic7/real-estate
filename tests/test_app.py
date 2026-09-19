from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_demo_filters_and_empty_live(tmp_path, monkeypatch):
    monkeypatch.setenv("REAL_ESTATE_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert len(app.tabs) == 4
    assert app.metric[0].value != "0건"
    app.selectbox(key="region_True").select("11680").run()
    assert not app.exception
    app.checkbox(key="radius_enabled").check().run()
    assert not app.exception
    app.checkbox(key="radius_enabled").uncheck().run()
    app.text_input(key="search").set_value("NO SUCH APARTMENT").run()
    assert not app.exception
    assert app.metric[0].value == "0건"
    app.radio(key="mode").set_value("실제 데이터").run()
    assert not app.exception
    assert app.metric[0].value == "0건"
    assert not app.button(key="request_collection").disabled

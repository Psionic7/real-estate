import pytest


@pytest.fixture(autouse=True)
def isolate_worker(monkeypatch):
    monkeypatch.setenv("ESTATE_DISABLE_WORKER", "1")
    monkeypatch.setenv("JUSO_ADDRESS_SEARCH_KEY", "")

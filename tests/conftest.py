import pytest


@pytest.fixture(autouse=True)
def isolate_worker(monkeypatch):
    monkeypatch.setenv("ESTATE_DISABLE_WORKER", "1")
    monkeypatch.setenv("ESTATE_DEFAULT_MODE", "demo")

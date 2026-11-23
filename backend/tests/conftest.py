import pytest

from solstice import runtime_store


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    """Tests write tickets/requests to a temp dir, never to data/runtime."""
    monkeypatch.setattr(runtime_store, "_dir", lambda: tmp_path)
    yield

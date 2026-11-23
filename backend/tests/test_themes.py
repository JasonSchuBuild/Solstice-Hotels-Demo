"""Website theme: validation, persistence (file and Azure Blob backends), admin-only writes, no flash on page load."""
import pytest
from fastapi.testclient import TestClient

from solstice import settings_store, themes
from solstice.web import app as web
from solstice.web.limits import UsageLimiter
from solstice.web.sessions import SessionStore


@pytest.fixture(autouse=True)
def _fresh_theme_state(monkeypatch):
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.setattr(themes, "_backend", None)
    themes.reset_cache()
    yield
    themes.reset_cache()


class ResourceNotFoundError(Exception):
    """Same class name the Azure SDK raises for a missing blob."""


class FakeContainer:
    """Stands in for azure.storage.blob.ContainerClient; `blobs` is the 'cloud' that outlives the app."""
    def __init__(self, blobs):
        self.blobs = blobs

    def get_blob_client(self, name):
        blobs = self.blobs

        class Blob:
            def download_blob(self):
                if name not in blobs:
                    raise ResourceNotFoundError()
                data = blobs[name]
                return type("D", (), {"readall": lambda s: data})()

            def upload_blob(self, data, overwrite=False):
                blobs[name] = data
        return Blob()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "store", SessionStore())
    monkeypatch.setattr(web, "limiter", UsageLimiter())
    return TestClient(web.app)


def _admin(c):
    return {"Authorization": "Bearer " + c.post("/api/sessions", json={"view": "admin", "pin": "4321"}).json()["token"]}


def test_default_theme_until_one_is_saved():
    assert themes.current() == themes.default_id() == "solstice"


def test_save_rejects_unknown_theme():
    with pytest.raises(ValueError):
        themes.save("neon-disco")


def test_file_backend_persists_across_cache_reset():
    themes.save("shoreline")
    themes.reset_cache()
    assert themes.current() == "shoreline"


def test_blob_backend_survives_a_restart():
    cloud = {}
    themes._backend = settings_store.BlobBackend("https://x.blob.core.windows.net", "theme.json", FakeContainer(cloud))
    themes.save("metropolis")
    assert "metropolis" in cloud["theme.json"]
    # "Restart": brand-new backend object and empty cache, same storage account.
    themes._backend = settings_store.BlobBackend("https://x.blob.core.windows.net", "theme.json", FakeContainer(cloud))
    themes.reset_cache()
    assert themes.current() == "metropolis"


def test_blob_backend_missing_blob_means_default():
    themes._backend = settings_store.BlobBackend("https://x.blob.core.windows.net", "theme.json", FakeContainer({}))
    assert themes.current() == "solstice"


def test_unreadable_store_falls_back_to_default_instead_of_failing():
    class Broken:
        name = "broken"
        def read(self): raise ConnectionError("storage down")
        def write(self, data): raise ConnectionError("storage down")
    themes._backend = Broken()
    assert themes.current() == "solstice"


def test_corrupt_saved_value_is_ignored():
    themes.backend().write({"theme": "not-a-theme"})
    assert themes.current() == "solstice"


def test_every_listed_theme_has_a_css_block():
    from solstice.web.app import STATIC
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for t in themes.available():
        assert t["id"] == "solstice" or f'[data-theme="{t["id"]}"]' in css


def test_only_admin_can_change_the_theme(client):
    assert client.put("/api/admin/theme", json={"theme": "shoreline"}).status_code == 401
    guest = client.post("/api/sessions", json={"view": "guest"}).json()["token"]
    assert client.put("/api/admin/theme", json={"theme": "shoreline"},
                      headers={"Authorization": f"Bearer {guest}"}).status_code == 403
    assert themes.current() == "solstice"


def test_admin_sets_theme_and_every_page_uses_it(client):
    h = _admin(client)
    assert client.put("/api/admin/theme", json={"theme": "metropolis"}, headers=h).json()["current"] == "metropolis"
    assert client.get("/api/theme").json() == {"theme": "metropolis"}
    for path in ("/", "/staff", "/admin"):
        r = client.get(path)
        assert 'data-theme="metropolis"' in r.text
        assert r.headers["cache-control"] == "no-store"


def test_unknown_theme_is_a_400(client):
    assert client.put("/api/admin/theme", json={"theme": "nope"}, headers=_admin(client)).status_code == 400


def test_storage_failure_on_save_is_a_clean_503(client, monkeypatch):
    def boom(*a, **k): raise ConnectionError("storage down")
    monkeypatch.setattr(themes.backend(), "write", boom)
    assert client.put("/api/admin/theme", json={"theme": "shoreline"}, headers=_admin(client)).status_code == 503
    assert themes.current() == "solstice"   # nothing half-applied

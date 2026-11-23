"""Demo open access: an admin switch that lets a blank PIN sign in to staff/admin. Off unless switched on,
off if storage fails, off when the master switch is off, and never grantable by the browser."""
import pytest
from fastapi.testclient import TestClient

from solstice import open_access, runtime_store, settings_store
from solstice.web import app as web
from solstice.web.limits import UsageLimiter
from solstice.web.sessions import SessionStore
from tests.test_themes import FakeContainer


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.setattr(open_access, "_backend", None)
    open_access.reset_cache()
    yield
    open_access.reset_cache()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "store", SessionStore())
    monkeypatch.setattr(web, "limiter", UsageLimiter())
    return TestClient(web.app)


def _start(c, view, pin):
    return c.post("/api/sessions", json={"view": view, "pin": pin})


def _admin(c, pin="4321"):
    return {"Authorization": "Bearer " + _start(c, "admin", pin).json()["token"]}


@pytest.mark.parametrize("view", ["admin", "front_desk", "group_sales"])
@pytest.mark.parametrize("pin", ["", None, "   "])
def test_blank_pin_is_refused_until_switched_on(client, view, pin):
    assert _start(client, view, pin).status_code == 401


@pytest.mark.parametrize("view", ["admin", "front_desk", "group_sales"])
def test_blank_pin_signs_in_once_switched_on(client, view):
    open_access.set_enabled(True)
    assert _start(client, view, "").status_code == 200


def test_wrong_pin_still_fails_and_real_pin_still_works_when_on(client):
    open_access.set_enabled(True)
    assert _start(client, "admin", "9999").status_code == 401
    assert _start(client, "admin", "4321").status_code == 200


def test_only_an_admin_can_flip_it(client):
    assert client.put("/api/admin/open-access", json={"enabled": True}).status_code == 401
    guest = client.post("/api/sessions", json={"view": "guest"}).json()["token"]
    assert client.put("/api/admin/open-access", json={"enabled": True},
                      headers={"Authorization": f"Bearer {guest}"}).status_code == 403
    assert not open_access.is_on()


def test_admin_flips_it_on_and_off_instantly(client):
    h = _admin(client)
    assert client.put("/api/admin/open-access", json={"enabled": True}, headers=h).json()["enabled"] is True
    assert 'data-open-access="true"' in client.get("/staff").text
    assert _start(client, "front_desk", "").status_code == 200
    assert client.put("/api/admin/open-access", json={"enabled": False}, headers=h).json()["enabled"] is False
    assert "data-open-access" not in client.get("/staff").text
    assert _start(client, "front_desk", "").status_code == 401


def test_master_switch_off_blocks_everything(client, monkeypatch):
    h = _admin(client)
    monkeypatch.setattr(open_access, "allowed", lambda: False)
    assert client.put("/api/admin/open-access", json={"enabled": True}, headers=h).status_code == 403
    open_access.backend().write({"enabled": True})   # even a stored "on" is ignored
    open_access.reset_cache()
    assert _start(client, "admin", "").status_code == 401


def test_unreadable_storage_means_off(client):
    class Broken:
        name = "broken"
        def read(self): raise ConnectionError("storage down")
        def write(self, data): raise ConnectionError("storage down")
    open_access.backend().write({"enabled": True})
    open_access._backend = Broken()
    open_access.reset_cache()
    assert not open_access.is_on()
    assert _start(client, "admin", "").status_code == 401


def test_storage_failure_on_save_is_a_clean_503_and_stays_off(client):
    h = _admin(client)
    class Broken:
        name = "broken"
        def read(self): return None
        def write(self, data): raise ConnectionError("storage down")
    open_access._backend = Broken()
    assert client.put("/api/admin/open-access", json={"enabled": True}, headers=h).status_code == 503
    assert not open_access.is_on()


def test_survives_a_restart_in_azure_blob():
    cloud = {}
    open_access._backend = settings_store.BlobBackend("https://x.blob.core.windows.net", "open_access.json", FakeContainer(cloud))
    open_access.set_enabled(True)
    open_access._backend = settings_store.BlobBackend("https://x.blob.core.windows.net", "open_access.json", FakeContainer(cloud))
    open_access.reset_cache()
    assert open_access.is_on()


def test_browser_demo_switch_cannot_grant_it(client):
    assert client.post("/api/sessions?demo=on", json={"view": "admin", "pin": ""}).status_code == 401


def test_every_change_and_blank_sign_in_is_audited(client):
    h = _admin(client)
    client.put("/api/admin/open-access", json={"enabled": True}, headers=h)
    _start(client, "admin", "")
    events = runtime_store.read_all("audit")
    assert any(e.get("event") == "open_access_changed" and e.get("enabled") for e in events)
    assert any(e.get("open_access") for e in events)

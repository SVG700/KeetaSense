"""Demo reliability: reset endpoint, dashboard served by the backend, no internet needed."""
import socket

from sqlmodel import Session, select

from backend import db
from backend.models import TapeSection
from backend.tests.conftest import tape_jpeg


def test_reset_demo_restores_seeded_state(client):
    client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(5), "image/jpeg")},
                data={"trap_id": "T1-polyhouse", "source": "upload"})
    r = client.post("/api/reset-demo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["removed"]["TapeSection"] == 1 and body["sections_created"] == 28
    with Session(db.get_engine()) as s:
        sections = s.exec(select(TapeSection)).all()
    assert len(sections) == 28
    assert all(x.source == "seed" and x.simulated and x.detector_mode == "demo_detector" for x in sections)
    assert client.get("/api/alerts").json() == []
    # images of the reset data are served
    assert client.get(client.get("/api/traps").json()[0]["latest_section"]["annotated_url"]).status_code == 200


def test_reset_demo_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("KEETA_ALLOW_RESET", "0")
    assert client.post("/api/reset-demo").status_code == 403


def test_backend_serves_built_dashboard(client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>KeetaSense dashboard</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("KEETA_DASHBOARD_DIR", str(dist))
    assert "KeetaSense dashboard" in client.get("/").text
    assert "KeetaSense dashboard" in client.get("/traps/T1-polyhouse").text   # client-side route
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/../backend/main.py").status_code in (200, 404)        # never escapes dist
    assert "def " not in client.get("/..%2Fbackend%2Fmain.py").text


def test_full_flow_makes_no_internet_connections(client, monkeypatch):
    """With every non-local network lookup blocked, the whole flow must still work."""
    attempts = []
    real_getaddrinfo = socket.getaddrinfo

    def guarded(host, *args, **kwargs):
        if host not in ("localhost", "127.0.0.1", "::1", "testserver"):
            attempts.append(host)
            raise socket.gaierror("blocked by test: no internet")
        return real_getaddrinfo(host, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", guarded)

    assert client.get("/api/health").status_code == 200
    r = client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(30, 1), "image/jpeg")},
                    data={"trap_id": "T1-polyhouse"})
    assert r.status_code == 200
    assert client.post("/api/phone-check", files={"image": ("p.jpg", tape_jpeg(5), "image/jpeg")}).status_code == 200
    for path in ("/api/traps", "/api/summary", "/api/model", "/api/traps/T1-polyhouse/history"):
        assert client.get(path).status_code == 200
    assert attempts == []


def test_telegram_failure_does_not_block_the_api(client, monkeypatch):
    import time
    from backend import alerts
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    async def offline(text):
        raise OSError("no internet")
    monkeypatch.setattr(alerts, "_send_telegram", offline)
    t0 = time.time()
    for i in range(3):   # pushes the decision to SPRAY -> alert
        assert client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(40, 0, seed=i), "image/jpeg")},
                           data={"trap_id": "T1-polyhouse"}).status_code == 200
    assert time.time() - t0 < 20
    deadline = time.time() + 5
    while time.time() < deadline:
        statuses = {a["status"] for a in client.get("/api/alerts").json()}
        if statuses == {"failed"}:
            break
        time.sleep(0.1)
    assert statuses == {"failed"}

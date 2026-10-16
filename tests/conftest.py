import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.odoo_client import OdooClient, OdooKonfig
from mock_odoo.server import lag_app


def _ledig_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def mock_odoo_url(tmp_path):
    """Starter mock-Odoo med egen SQLite-fil i en tråd. Ekte HTTP, samme protokoll som Odoo."""
    port = _ledig_port()
    server = uvicorn.Server(uvicorn.Config(lag_app(tmp_path / "test.db"), host="127.0.0.1", port=port,
                                           log_level="error"))
    traad = threading.Thread(target=server.run, daemon=True)
    traad.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(url + "/")
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield url
    server.should_exit = True
    traad.join(timeout=5)


@pytest.fixture()
def odoo(mock_odoo_url):
    return OdooClient(OdooKonfig(mock_odoo_url, "strai", "demo@strai.no", "demo"))


@pytest.fixture(autouse=True)
def egen_ai_logg(tmp_path, monkeypatch):
    """Testene skal ikke skrive i den ekte AI-loggen."""
    monkeypatch.setenv("AI_LOGG", str(tmp_path / "ai_logg.jsonl"))

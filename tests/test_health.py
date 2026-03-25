"""
tests/test_health.py

Unit tests for GET /v1/health endpoint.
Uses FastAPI TestClient with DB pool mocked so no real DB is required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient


def _make_client():
    """Import app fresh inside a mocked DB init_pool context."""
    import api.main as main_module

    # Patch init_pool so startup doesn't require a real DB
    with patch.object(main_module.database, "init_pool", return_value=None):
        client = TestClient(main_module.app, raise_server_exceptions=False)
    return main_module, client


class TestHealthEndpoint:

    def test_health_returns_200(self):
        import api.main as main_module

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch.object(main_module.database, "init_pool", return_value=None):
            with patch.object(main_module.database, "get_conn") as mock_get_conn:
                mock_get_conn.return_value.__enter__ = lambda s: mock_conn
                mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
                client = TestClient(main_module.app, raise_server_exceptions=False)
                resp = client.get("/v1/health")

        assert resp.status_code == 200

    def test_health_contains_required_fields(self):
        import api.main as main_module

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(main_module.database, "init_pool", return_value=None):
            with patch.object(main_module.database, "get_conn") as mock_get_conn:
                mock_get_conn.return_value.__enter__ = lambda s: mock_conn
                mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
                client = TestClient(main_module.app, raise_server_exceptions=False)
                resp = client.get("/v1/health")

        body = resp.json()
        assert "status" in body
        assert "uptime_seconds" in body
        assert "db" in body
        assert "status" in body["db"]

    def test_health_db_ok_when_pool_works(self):
        import api.main as main_module

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(main_module.database, "init_pool", return_value=None):
            with patch.object(main_module.database, "get_conn") as mock_get_conn:
                mock_get_conn.return_value.__enter__ = lambda s: mock_conn
                mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
                client = TestClient(main_module.app, raise_server_exceptions=False)
                resp = client.get("/v1/health")

        body = resp.json()
        assert body["db"]["status"] == "ok"

    def test_health_db_error_when_pool_fails(self):
        import api.main as main_module

        with patch.object(main_module.database, "init_pool", return_value=None):
            with patch.object(main_module.database, "get_conn") as mock_get_conn:
                mock_get_conn.return_value.__enter__ = MagicMock(
                    side_effect=RuntimeError("DB pool not initialized")
                )
                mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
                client = TestClient(main_module.app, raise_server_exceptions=False)
                resp = client.get("/v1/health")

        body = resp.json()
        assert body["status"] == "ok"       # API itself is up
        assert body["db"]["status"] == "error"
        assert "error" in body["db"]

    def test_health_uptime_is_non_negative(self):
        import api.main as main_module

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(main_module.database, "init_pool", return_value=None):
            with patch.object(main_module.database, "get_conn") as mock_get_conn:
                mock_get_conn.return_value.__enter__ = lambda s: mock_conn
                mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
                client = TestClient(main_module.app, raise_server_exceptions=False)
                resp = client.get("/v1/health")

        body = resp.json()
        assert isinstance(body["uptime_seconds"], (int, float))
        assert body["uptime_seconds"] >= 0

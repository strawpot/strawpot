"""Shared fixtures for GUI tests."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from strawpot_gui.app import create_app


@pytest.fixture
def app(tmp_path):
    """Create a test app with a temp database."""
    db_path = str(tmp_path / "test_gui.db")
    return create_app(db_path=db_path)


@pytest.fixture
def client(app):
    """TestClient for making requests to the test app."""
    with patch("strawpot_gui.app._ensure_imu_role"):
        with TestClient(app) as c:
            yield c

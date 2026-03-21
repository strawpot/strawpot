"""Shared test fixtures for the strawpot CLI test suite."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_pypi_check():
    """Prevent tests from hitting PyPI during the auto-update check."""
    with patch("strawpot.cli._check_update_async", return_value=None):
        yield

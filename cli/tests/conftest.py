"""Shared test fixtures for the strawpot CLI test suite."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_pypi_check():
    """Prevent tests from hitting PyPI during the auto-update check."""
    with patch("strawpot.cli._check_update_async", return_value=None), \
         patch("strawpot.cli._check_pypi_version", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _no_system_prereq_check():
    """Default system prerequisite check to pass in tests.

    Tests that specifically exercise the pre-flight check override this
    via ``@patch("strawpot.cli._check_system_prerequisites", ...)``.
    """
    with patch("strawpot.cli._check_system_prerequisites", return_value=[]):
        yield

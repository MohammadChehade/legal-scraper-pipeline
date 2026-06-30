"""Pytest configuration shared across the suite."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run integration tests that hit the live website",
    )


def pytest_collection_modifyitems(config, items):
    # Skip live/integration tests unless --integration is passed, and attach a
    # clear reason so a plain run shows why rather than silently selecting nothing.
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="live test; pass --integration to run it")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)

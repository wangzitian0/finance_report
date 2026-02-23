import pytest


@pytest.fixture(autouse=True)
def patch_database_connection():
    """Override the global autouse fixture to avoid database connections in unit tests."""
    yield
